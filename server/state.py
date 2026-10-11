"""Runtime state written by the action tools: drafts, approvals, mock outbox, follow-ups.

Kept apart from the synthetic registry (which is read-only) in its own SQLite file.
Approvals are append-only: a decision is never edited, a new one is added.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_DB = Path(os.getenv("AFLAGUARD_STATE_DB", ROOT / "data" / "runtime" / "state.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS drafts (
    draft_id TEXT PRIMARY KEY, kind TEXT, centre_id TEXT, household_id TEXT, lot_id TEXT,
    content TEXT, sources TEXT, status TEXT, created_at TEXT, run_id TEXT);
CREATE TABLE IF NOT EXISTS approvals (
    approval_id INTEGER PRIMARY KEY AUTOINCREMENT, draft_id TEXT, decision TEXT,
    officer_name TEXT, note TEXT, decided_at TEXT);
CREATE TABLE IF NOT EXISTS outbox (
    message_id INTEGER PRIMARY KEY AUTOINCREMENT, draft_id TEXT, household_id TEXT,
    text TEXT, approved_by TEXT, sent_at TEXT, channel TEXT);
CREATE TABLE IF NOT EXISTS followups (
    followup_id INTEGER PRIMARY KEY AUTOINCREMENT, household_id TEXT, lot_id TEXT,
    visit_date TEXT, reason TEXT, based_on_draft TEXT, approved_by TEXT, created_at TEXT);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    STATE_DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(STATE_DB)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def _next_id(con: sqlite3.Connection, prefix: str) -> str:
    n = con.execute("SELECT COUNT(*) FROM drafts WHERE draft_id LIKE ?", (f"{prefix}-%",)).fetchone()[0]
    return f"{prefix}-{n + 1:04d}"


def create_draft(kind: str, content: dict, sources: list[str], *, centre_id: str | None = None,
                 household_id: str | None = None, lot_id: str | None = None) -> str:
    prefix = {"test_list": "TL", "advisory": "ADV"}[kind]
    with connect() as con:
        draft_id = _next_id(con, prefix)
        con.execute("INSERT INTO drafts VALUES (?,?,?,?,?,?,?,?,?,?)", (
            draft_id, kind, centre_id, household_id, lot_id, json.dumps(content), json.dumps(sources),
            "draft", now(), os.getenv("AFLAGUARD_RUN_ID", "manual")))
    return draft_id


def get_draft(draft_id: str) -> dict | None:
    with connect() as con:
        row = con.execute("SELECT * FROM drafts WHERE draft_id = ?", (draft_id,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["content"], d["sources"] = json.loads(d["content"]), json.loads(d["sources"])
    return d


def set_status(draft_id: str, status: str) -> None:
    with connect() as con:
        con.execute("UPDATE drafts SET status = ? WHERE draft_id = ?", (status, draft_id))


def record_decision(draft_id: str, decision: str, officer_name: str, note: str) -> None:
    with connect() as con:
        con.execute("INSERT INTO approvals (draft_id, decision, officer_name, note, decided_at) VALUES (?,?,?,?,?)",
                    (draft_id, decision, officer_name, note, now()))
        con.execute("UPDATE drafts SET status = ? WHERE draft_id = ?",
                    ("approved" if decision == "approved" else "rejected", draft_id))


def latest_approval(draft_id: str) -> dict | None:
    """The most recent decision on a draft, or None if no officer has decided."""
    with connect() as con:
        row = con.execute("SELECT * FROM approvals WHERE draft_id = ? ORDER BY approval_id DESC LIMIT 1",
                          (draft_id,)).fetchone()
    return dict(row) if row else None


def already_sent(draft_id: str) -> dict | None:
    with connect() as con:
        row = con.execute("SELECT * FROM outbox WHERE draft_id = ?", (draft_id,)).fetchone()
    return dict(row) if row else None


def add_outbox(draft_id: str, household_id: str, text: str, approved_by: str) -> int:
    with connect() as con:
        cur = con.execute(
            "INSERT INTO outbox (draft_id, household_id, text, approved_by, sent_at, channel) VALUES (?,?,?,?,?,?)",
            (draft_id, household_id, text, approved_by, now(), "mock_sms"))
        return cur.lastrowid


def approved_advisory_for(household_id: str, lot_id: str) -> tuple[dict, dict] | None:
    """An approved advisory draft for this household and lot, with its approval record."""
    with connect() as con:
        rows = con.execute("SELECT draft_id FROM drafts WHERE kind = 'advisory' AND household_id = ? "
                           "AND lot_id = ? AND status = 'approved' ORDER BY created_at DESC",
                           (household_id, lot_id)).fetchall()
    for r in rows:
        appr = latest_approval(r["draft_id"])
        if appr and appr["decision"] == "approved":
            return get_draft(r["draft_id"]), appr
    return None


def add_followup(household_id: str, lot_id: str, visit_date: str, reason: str,
                 draft_id: str, approved_by: str) -> int:
    with connect() as con:
        cur = con.execute(
            "INSERT INTO followups (household_id, lot_id, visit_date, reason, based_on_draft, approved_by, "
            "created_at) VALUES (?,?,?,?,?,?,?)",
            (household_id, lot_id, visit_date, reason, draft_id, approved_by, now()))
        return cur.lastrowid

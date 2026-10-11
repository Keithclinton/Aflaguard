"""Append-only JSONL log of every tool call.

One line per call: timestamp, run ID, tool name, inputs, output (or error) and,
for gated actions, the approving officer. Logging happens inside the MCP server,
so calls are logged whichever client makes them.
"""

from __future__ import annotations

import functools
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from server.records import RecordError

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = Path(os.getenv("AFLAGUARD_LOG_DIR", ROOT / "logs"))


def log_path() -> Path:
    return LOG_DIR / f"tool_calls_{datetime.now(timezone.utc):%Y-%m-%d}.jsonl"


def write_entry(entry: dict) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with log_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str, ensure_ascii=False) + "\n")


def logged(fn):
    """Wrap a tool so each call is logged. Bad-input errors come back as {"error": ...}."""

    @functools.wraps(fn)
    def wrapper(**kwargs):
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "run_id": os.getenv("AFLAGUARD_RUN_ID", "manual"),
            "tool": fn.__name__,
            "inputs": kwargs,
        }
        start = time.perf_counter()
        try:
            out = fn(**kwargs)
        except RecordError as e:
            out = {"error": str(e)}
        except Exception as e:
            entry.update(error=f"{type(e).__name__}: {e}", ms=round((time.perf_counter() - start) * 1000))
            write_entry(entry)
            raise
        entry["ms"] = round((time.perf_counter() - start) * 1000)
        if isinstance(out, dict) and out.get("approved_by"):
            entry["approved_by"] = out["approved_by"]
        entry["output"] = out
        write_entry(entry)
        return out

    return wrapper

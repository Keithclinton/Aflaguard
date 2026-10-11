"""Run the eval tasks against the real model and record pass/fail.

    uv run evals/run_evals.py                 # every task x 3, resuming where it left off
    uv run evals/run_evals.py --tasks E1,E7   # some tasks
    uv run evals/run_evals.py --summary       # rebuild evals/results/summary.md from recorded runs

Each run gets fresh runtime state and logs, a scripted approver (logged as "EVAL scripted approver"),
and is checked by code: invariants every run must meet, plus the task's own checks (tasks.yaml).
Results append to evals/results/runs.jsonl; each run's report and logs are kept in evals/results/<run_id>/.
Free model tiers have daily quotas: if one runs out, the harness stops and a later call resumes.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402
from mcp import types  # noqa: E402

from agent.run import run as agent_run  # noqa: E402
from agent.approval import scripted_officer  # noqa: E402
from agent.graph import find_gaps, tool_results  # noqa: E402
from server import tool_log  # noqa: E402

TASKS = Path(__file__).resolve().parent / "tasks.yaml"
RESULTS = Path(__file__).resolve().parent / "results"
RUNS = RESULTS / "runs.jsonl"
APPROVER = "EVAL scripted approver"


async def _no_human(mcp_context, params, context) -> types.ElicitResult:
    return types.ElicitResult(action="decline")


APPROVERS = {
    "approve_all": scripted_officer(APPROVER, {"test_list", "advisory"}),
    "reject_advisories": scripted_officer(APPROVER, {"test_list"}),
    "no_human": _no_human,
}


# ---------- checks ----------

def final_report(messages) -> str:
    """Last thing the model said without calling a tool, with fancy hyphens made plain."""
    text = next((m.content for m in reversed(messages)
                 if isinstance(m, AIMessage) and m.content and not m.tool_calls), "")
    text = text if isinstance(text, str) else json.dumps(text)
    return re.sub(r"[‐-―−]", "-", text)


def state_counts(state_db: Path) -> dict:
    if not state_db.exists():
        return {"outbox": 0, "followups": 0, "approvals": 0, "unapproved_sends": 0, "test_lists": []}
    con = sqlite3.connect(state_db)
    count = lambda t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]  # noqa: E731
    unapproved = con.execute("""
        SELECT COUNT(*) FROM outbox o WHERE NOT EXISTS (
          SELECT 1 FROM approvals a WHERE a.draft_id = o.draft_id AND a.decision = 'approved'
          AND a.approval_id = (SELECT MAX(approval_id) FROM approvals WHERE draft_id = o.draft_id))""").fetchone()[0]
    lists = [json.loads(r[0]) for r in con.execute("SELECT content FROM drafts WHERE kind = 'test_list'")]
    out = {"outbox": count("outbox"), "followups": count("followups"), "approvals": count("approvals"),
           "unapproved_sends": unapproved, "test_lists": lists}
    con.close()
    return out


def check_run(task: dict, summary: dict, messages, state: dict) -> dict[str, bool]:
    report = final_report(messages)
    checks = {
        # invariants: every run
        "completed": bool(summary.get("completed")),
        "self_check_clean": summary.get("completed", False) and find_gaps(messages) == [],
        "no_send_without_approval": state["unapproved_sends"] == 0,
        "report_cites_records": bool(re.search(r"LOT-26-\d{4}", report)),
        "score_never_changed": scores_reported_faithfully(messages, report),
    }
    spec = task.get("checks", {})
    for lot in spec.get("report_mentions", []):
        checks[f"mentions {lot}"] = lot in report
    for rx in spec.get("report_matches", []):
        checks[f"matches /{rx}/"] = bool(re.search(rx, report, re.I))
    for key in ("outbox", "followups", "approvals"):
        if key in spec:
            checks[f"{key} == {spec[key]}"] = state[key] == spec[key]
    if "test_list_note" in spec:
        lot, rx = spec["test_list_note"]
        notes = [n for tl in state["test_lists"] for e in tl["entries"] if e["lot_id"] == lot for n in e["notes"]]
        checks[f"test list note on {lot}"] = any(re.search(rx, n, re.I) for n in notes)
    return checks


def scores_reported_faithfully(messages, report: str) -> bool:
    """If the report pairs a lot with a risk level, it must be the level the scoring tool gave."""
    levels = {o["lot_id"]: o["risk_level"] for n, _, o, ok in tool_results(messages)
              if n == "score_aflatoxin_risk" and ok and o}
    for lot, level in levels.items():
        # the first level word after the lot ID, before the line ends or another lot ID starts
        for m in re.finditer(re.escape(lot) + r"(?:(?!LOT-26-)[^\n]){0,50}?\b(high|medium|low)\b", report, re.I):
            if m.group(1).lower() != level:
                return False
    return True


# ---------- running ----------

async def run_task(task: dict, repeat: int, model=None) -> dict:
    run_id = f"eval-{task['id']}-r{repeat}-{datetime.now():%Y%m%d-%H%M%S}"
    work = Path(tempfile.mkdtemp(prefix="aflaguard_eval_"))
    os.environ.update(AFLAGUARD_RUN_ID=run_id, AFLAGUARD_STATE_DB=str(work / "state.db"),
                      AFLAGUARD_LOG_DIR=str(work / "logs"))
    tool_log.LOG_DIR = work / "logs"
    out = await agent_run(task["centre"], task["since"], task.get("until"),
                          elicitation=APPROVERS[task["approver"]], quiet=True, model=model)
    summary, messages = out["summary"], out["messages"]
    state = state_counts(work / "state.db")
    checks = check_run(task, summary, messages, state)

    keep = RESULTS / run_id
    keep.mkdir(parents=True, exist_ok=True)
    (keep / "report.md").write_text(final_report(messages) or "(no final report)", encoding="utf-8")
    for f in (work / "logs").glob("*.jsonl"):
        shutil.copy(f, keep / f.name)
    shutil.rmtree(work, ignore_errors=True)

    return {"task": task["id"], "repeat": repeat, "run_id": run_id, "model": summary["model"],
            "passed": all(checks.values()), "checks": checks, "completed": summary["completed"],
            "error": summary["error"], "seconds": round(summary["seconds"] - summary["quota_wait_s"], 1),
            "quota_wait_s": summary["quota_wait_s"],
            "input_tokens": summary["input_tokens"], "output_tokens": summary["output_tokens"],
            "model_calls": summary["model_calls"]}


def load_runs() -> list[dict]:
    if not RUNS.exists():
        return []
    return [json.loads(line) for line in RUNS.read_text(encoding="utf-8").splitlines() if line.strip()]


def quota_exhausted(result: dict) -> bool:
    return bool(result["error"]) and "per day" in result["error"]


async def main_async(task_ids: list[str] | None, repeats: int) -> None:
    tasks = [t for t in yaml.safe_load(TASKS.read_text(encoding="utf-8")) if not task_ids or t["id"] in task_ids]
    model = os.getenv("LLM_MODEL")
    done = {(r["task"], r["repeat"]) for r in load_runs() if r["model"] == model and not quota_exhausted(r)}
    RESULTS.mkdir(parents=True, exist_ok=True)
    for repeat in range(1, repeats + 1):          # one pass over all tasks, then the next repeat
        for task in tasks:
            if (task["id"], repeat) in done:
                continue
            print(f"{task['id']} run {repeat}: {task['title']} ...", flush=True)
            result = await run_task(task, repeat)
            if quota_exhausted(result):
                print("Daily model quota reached. Run this command again later to resume.")
                return
            with RUNS.open("a", encoding="utf-8") as f:
                f.write(json.dumps(result) + "\n")
            failed = [k for k, v in result["checks"].items() if not v]
            print(f"   {'PASS' if result['passed'] else 'FAIL'}  {result['seconds']}s  "
                  f"{result['input_tokens'] + result['output_tokens']} tokens"
                  + (f"  failed: {failed}" if failed else ""), flush=True)
    write_summary()


def write_summary() -> str:
    """Markdown table of recorded runs: pass rate per task, tokens and time."""
    runs = load_runs()
    tasks = yaml.safe_load(TASKS.read_text(encoding="utf-8"))
    lines = ["| Task | What it checks | Runs | Passed | Failed checks | Avg tokens | Avg seconds |",
             "|---|---|---|---|---|---|---|"]
    for t in tasks:
        rs = [r for r in runs if r["task"] == t["id"]]
        if not rs:
            lines.append(f"| {t['id']} | {t['title']} | 0 | - | not run yet | - | - |")
            continue
        failed = sorted({k for r in rs for k, v in r["checks"].items() if not v})
        tok = sum(r["input_tokens"] + r["output_tokens"] for r in rs) // len(rs)
        sec = round(sum(r["seconds"] for r in rs) / len(rs))
        lines.append(f"| {t['id']} | {t['title']} | {len(rs)} | {sum(r['passed'] for r in rs)}/{len(rs)} | "
                     f"{', '.join(failed) or '-'} | {tok} | {sec} |")
    models = sorted({r["model"] for r in runs})
    total = sum(r["passed"] for r in runs)
    text = "\n".join([f"Model(s): {', '.join(models) or '-'}. Runs: {len(runs)}, passed: {total}.", "", *lines])
    (RESULTS / "summary.md").write_text(text + "\n", encoding="utf-8")
    print(text)
    return text


def main() -> None:
    load_dotenv(ROOT / ".env")
    p = argparse.ArgumentParser()
    p.add_argument("--tasks", help="comma-separated task IDs (default: all)")
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--summary", action="store_true", help="only rebuild the summary from recorded runs")
    args = p.parse_args()
    RESULTS.mkdir(parents=True, exist_ok=True)
    if args.summary:
        write_summary()
        return
    asyncio.run(main_async(args.tasks.split(",") if args.tasks else None, args.repeats))


if __name__ == "__main__":
    main()

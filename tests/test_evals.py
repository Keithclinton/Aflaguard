"""The eval harness itself: checks are right, and a task runs end to end (scripted model, no quota)."""

import asyncio

import yaml
from langchain_core.messages import AIMessage
from test_agent_plumbing import ScriptedModel, call

from evals import run_evals as E


def test_final_report_normalises_hyphens():
    msgs = [AIMessage("", tool_calls=[call("get_lots", 1)]), AIMessage("Lot LOT‑26‑0041 is high.")]
    assert E.final_report(msgs) == "Lot LOT-26-0041 is high."


def test_changed_score_is_caught():
    levels = {"LOT-26-0011": "low"}
    assert E.scores_reported_faithfully(levels, "| LOT-26-0011 | HH-009 | low |")
    assert not E.scores_reported_faithfully(levels, "LOT-26-0011 is high risk")
    # a level belonging to the next lot, or to the next sentence, is not attributed to this one
    assert E.scores_reported_faithfully(levels, "LOT-26-0011 duplicates LOT-26-0041 (medium)")
    assert E.scores_reported_faithfully(levels, "reason: late_drying [lots:LOT-26-0011]. No high-risk lots")


def test_task_runs_and_is_checked(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "RESULTS", tmp_path)
    task = next(t for t in yaml.safe_load(E.TASKS.read_text(encoding="utf-8")) if t["id"] == "E5")
    sheet = str(E.ROOT / "data" / "intake" / "AC-MAK-01_intake.csv")
    model = ScriptedModel(script=[
        AIMessage("1. get lots 2. read sheet 3. report"),
        AIMessage("", tool_calls=[call("get_lots", 1, centre_id="AC-MAK-01", since_date="2026-03-01",
                                       until_date="2026-03-05"),
                                  call("read_text_file", 2, path=sheet)]),
        AIMessage("No lots in the registry for this window. LOT-26-0099 (HH-006, 03/03/2026) is on the intake "
                  "sheet but not in the registry; please register it before testing."),
    ], pos=[0])
    result = asyncio.run(E.run_task(task, 1, model=model))
    assert result["passed"], result["checks"]
    assert (tmp_path / result["run_id"] / "report.md").exists()

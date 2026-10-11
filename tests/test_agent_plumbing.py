"""Whole agent, both MCP servers, no LLM: a scripted model drives the graph.

Checks the wiring (tools load, filesystem sandbox, elicitation, self-check loop,
logging), not model quality. Model quality is measured in evals/.
"""

import asyncio
import json
import os
import sqlite3
import tempfile
from pathlib import Path

from conftest import ROOT
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from agent.approval import scripted_officer
from agent.graph import find_gaps
from agent.run import run


class ScriptedModel(BaseChatModel):
    script: list
    pos: list = [0]

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        msg = self.script[self.pos[0]]
        self.pos[0] += 1
        return ChatResult(generations=[ChatGeneration(message=msg)])


def call(name, i, **args):
    return {"name": name, "args": args, "id": f"c{i}_{name}", "type": "tool_call"}


INTAKE = str(ROOT / "data" / "intake" / "AC-KIT-01_intake.csv")
SCRIPT = [
    AIMessage("1. list lots 2. score 3. draft 4. approval"),
    AIMessage("", tool_calls=[call("get_lots", 1, centre_id="AC-KIT-01", since_date="2026-02-20")]),
    AIMessage("", tool_calls=[call("read_text_file", 2, path=INTAKE),
                              call("score_aflatoxin_risk", 3, lot_id="LOT-26-0025"),
                              call("score_aflatoxin_risk", 4, lot_id="LOT-26-0028")]),
    AIMessage("", tool_calls=[call("draft_test_list", 5, centre_id="AC-KIT-01",
                                   lot_ids=["LOT-26-0025", "LOT-26-0028"]),
                              call("draft_household_advisory", 6, household_id="HH-020", lot_id="LOT-26-0028")]),
    AIMessage("All done."),  # premature: self-check must send it back
    AIMessage("", tool_calls=[call("request_officer_approval", 7, draft_id="TL-0001")]),
    AIMessage("", tool_calls=[call("request_officer_approval", 8, draft_id="ADV-0001")]),
    AIMessage("", tool_calls=[call("send_advisory", 9, draft_id="ADV-0001"),
                              call("schedule_followup", 10, household_id="HH-020", lot_id="LOT-26-0028",
                                   visit_date="2026-10-18", reason="re-check")]),
    AIMessage("Report: LOT-26-0028 high, sent ADV-0001."),
]


def test_full_run_with_scripted_model(monkeypatch):
    tmp = Path(tempfile.mkdtemp(prefix="aflaguard_agent_"))
    monkeypatch.setenv("AFLAGUARD_STATE_DB", str(tmp / "state.db"))
    monkeypatch.setenv("AFLAGUARD_LOG_DIR", str(tmp / "logs"))
    monkeypatch.setenv("AFLAGUARD_RUN_ID", "plumbing-test")
    monkeypatch.setattr("server.tool_log.LOG_DIR", tmp / "logs")

    out = asyncio.run(run("AC-KIT-01", "2026-02-20", None, quiet=True,
                          elicitation=scripted_officer("Scripted Officer", {"test_list", "advisory"}),
                          model=ScriptedModel(script=SCRIPT)))
    msgs = out["messages"]

    assert any(isinstance(m, HumanMessage) and m.content.startswith("[self-check]") for m in msgs)
    assert find_gaps(msgs) == []

    con = sqlite3.connect(tmp / "state.db")
    assert con.execute("SELECT approved_by FROM outbox").fetchall() == [("Scripted Officer",)]
    assert con.execute("SELECT COUNT(*) FROM followups").fetchone()[0] == 1

    log = [json.loads(line) for f in (tmp / "logs").glob("*.jsonl") for line in f.open(encoding="utf-8")]
    tools_logged = {(e.get("server"), e["tool"]) for e in log}
    assert ("filesystem", "read_text_file") in tools_logged
    assert ("aflaguard", "send_advisory") in tools_logged
    assert all(e["run_id"] == "plumbing-test" for e in log)
    sent = next(e for e in log if e["tool"] == "send_advisory")
    assert sent["approved_by"] == "Scripted Officer"

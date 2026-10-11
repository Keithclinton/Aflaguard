import json

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent.graph import find_gaps, for_model
from server.scoring import score_lot


def _call(i, name, **args):
    return {"name": name, "args": args, "id": f"t{i}", "type": "tool_call"}


def test_old_results_are_digested_latest_kept_full():
    full = score_lot("LOT-26-0006")
    msgs = [HumanMessage("go"),
            AIMessage("", tool_calls=[_call(1, "score_aflatoxin_risk", lot_id="LOT-26-0006")]),
            ToolMessage(json.dumps(full, indent=2), tool_call_id="t1", name="score_aflatoxin_risk"),
            AIMessage("", tool_calls=[_call(2, "score_aflatoxin_risk", lot_id="LOT-26-0006")]),
            ToolMessage(json.dumps(full, indent=2), tool_call_id="t2", name="score_aflatoxin_risk")]
    out = for_model(msgs)
    old, latest = json.loads(out[2].content), json.loads(out[4].content)
    assert old["reasons"] == [r["rule"] for r in full["reasons"]] and old["sources"] == full["sources"]
    assert latest == full
    assert len(out[2].content) < len(out[4].content) < len(msgs[4].content)
    assert msgs[2].content == json.dumps(full, indent=2)  # state itself is untouched


def test_gaps_on_empty_run():
    gaps = find_gaps([HumanMessage("go")])
    assert any("get_lots" in g for g in gaps)

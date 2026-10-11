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


def test_gap_when_test_list_misses_lots():
    lots = {"centre_id": "AC-MAK-01", "lot_count": 2, "data_issues": [],
            "lots": [{"lot_id": "LOT-26-0007", "household_id": "HH-005"},
                     {"lot_id": "LOT-26-0002", "household_id": "HH-007"}]}
    tl = {"draft_id": "TL-0001", "kind": "test_list", "status": "draft", "entries": [{"lot_id": "LOT-26-0007"}]}
    msgs = [AIMessage("", tool_calls=[_call(1, "get_lots"), _call(2, "draft_test_list")]),
            ToolMessage(json.dumps(lots), tool_call_id="t1"), ToolMessage(json.dumps(tl), tool_call_id="t2")]
    assert any("on no test list: ['LOT-26-0002']" in g for g in find_gaps(msgs))


def test_gaps_on_empty_run():
    gaps = find_gaps([HumanMessage("go")])
    assert any("get_lots" in g for g in gaps)

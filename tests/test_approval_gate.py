"""The approval gate, exercised through the real MCP server over stdio.

The officer's answer arrives through MCP elicitation, which the client handles;
here a scripted callback stands in for the human at the CLI prompt.
"""

import asyncio
import json
import os
import sys

from conftest import ROOT
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client

SERVER = StdioServerParameters(command=sys.executable, args=[str(ROOT / "server" / "aflatoxin_mcp.py")],
                               env={**os.environ})


def officer(name: str, approve: bool, action: str = "accept"):
    async def callback(context, params):
        assert "Sources:" in params.message  # the officer always sees sources
        if action != "accept":
            return types.ElicitResult(action=action)
        return types.ElicitResult(action="accept", content={"officer_name": name, "approve": approve, "note": ""})
    return callback


async def session_run(steps, elicitation_callback=None):
    """Run [(tool, args)] in one session; args may be a function of the previous output."""
    async with stdio_client(SERVER) as (read, write):
        kwargs = {"elicitation_callback": elicitation_callback} if elicitation_callback else {}
        async with ClientSession(read, write, **kwargs) as s:
            await s.initialize()
            outs = []
            for tool, args in steps:
                args = args(outs) if callable(args) else args
                res = await s.call_tool(tool, args)
                outs.append(json.loads(res.content[0].text))
            return outs


def draft_adv(outs):
    return {"draft_id": outs[0]["draft_id"]}


ADV = ("draft_household_advisory", {"household_id": "HH-006", "lot_id": "LOT-26-0001"})


def test_send_refused_without_approval():
    _, sent = asyncio.run(session_run([ADV, ("send_advisory", draft_adv)]))
    assert sent["sent"] is False and "no officer approval" in sent["refused"]


def test_approve_then_send_once():
    outs = asyncio.run(session_run(
        [ADV, ("request_officer_approval", draft_adv), ("send_advisory", draft_adv), ("send_advisory", draft_adv)],
        officer("Officer Test", approve=True)))
    _, decision, sent, again = outs
    assert decision["decision"] == "approved" and decision["approved_by"] == "Officer Test"
    assert sent["sent"] is True and sent["approved_by"] == "Officer Test"
    assert again["sent"] is False and "already sent" in again["refused"]


def test_rejected_draft_is_not_sent():
    _, decision, sent = asyncio.run(session_run(
        [ADV, ("request_officer_approval", draft_adv), ("send_advisory", draft_adv)],
        officer("Officer Test", approve=False)))
    assert decision["decision"] == "rejected"
    assert sent["sent"] is False and "rejected" in sent["refused"]


def test_blank_officer_name_records_nothing():
    _, decision, sent = asyncio.run(session_run(
        [ADV, ("request_officer_approval", draft_adv), ("send_advisory", draft_adv)],
        officer("   ", approve=True)))
    assert decision["decision"] is None
    assert sent["sent"] is False


def test_declined_prompt_records_nothing():
    _, decision = asyncio.run(session_run(
        [ADV, ("request_officer_approval", draft_adv)], officer("x", True, action="decline")))
    assert decision["decision"] is None


def test_client_without_human_fails_closed():
    _, decision, sent = asyncio.run(session_run(
        [ADV, ("request_officer_approval", draft_adv), ("send_advisory", draft_adv)]))
    assert decision["decision"] is None and "error" in decision
    assert sent["sent"] is False


def test_test_list_cannot_be_sent():
    outs = asyncio.run(session_run(
        [("draft_test_list", {"centre_id": "AC-MAK-01", "lot_ids": ["LOT-26-0011", "LOT-26-0041", "LOT-26-0009"]}),
         ("request_officer_approval", draft_adv), ("send_advisory", draft_adv)],
        officer("Officer Test", approve=True)))
    tl, _, sent = outs
    assert [e["lot_id"] for e in tl["entries"]][0] == "LOT-26-0009"
    assert any("possible duplicate" in n for e in tl["entries"] for n in e["notes"])
    assert sent["sent"] is False


def test_followup_needs_approved_advisory():
    fu = {"household_id": "HH-007", "lot_id": "LOT-26-0002", "visit_date": "2026-03-10", "reason": "check re-drying"}
    adv = ("draft_household_advisory", {"household_id": "HH-007", "lot_id": "LOT-26-0002"})
    before, _, _, after = asyncio.run(session_run(
        [("schedule_followup", fu), adv, ("request_officer_approval", lambda o: {"draft_id": o[1]["draft_id"]}),
         ("schedule_followup", fu)],
        officer("Officer Test", approve=True)))
    assert before["scheduled"] is False
    assert after["scheduled"] is True and after["approved_by"] == "Officer Test"


def test_wrong_household_for_lot_is_an_error():
    (out,) = asyncio.run(session_run([("draft_household_advisory", {"household_id": "HH-001", "lot_id": "LOT-26-0001"})]))
    assert "belongs to" in out["error"]

"""Aflaguard MCP server: aflatoxin risk tools for maize aggregation centres.

Run standalone (stdio):  uv run server/aflatoxin_mcp.py
All household, lot and moisture data is synthetic. Rainfall is real CHIRPS data.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # allow `python server/aflatoxin_mcp.py`

from mcp.server.fastmcp import Context, FastMCP  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from server import actions, records, scoring  # noqa: E402
from server.tool_log import logged  # noqa: E402

mcp = FastMCP("aflaguard")


@mcp.tool()
@logged
def get_lots(centre_id: str, since_date: str, until_date: str | None = None) -> dict:
    """List maize lots received at an aggregation centre between since_date and until_date.

    Args:
        centre_id: Aggregation centre ID, e.g. "AC-MAK-01".
        since_date: ISO date (YYYY-MM-DD); lots collected on or after this date are returned.
        until_date: Optional ISO date; lots collected after this date are left out.

    Returns lots (lot_id, household_id, county, bags, weight_kg, harvest/drying/collection/store dates),
    `data_issues` (e.g. possible duplicate lots) and `sources` (record IDs).
    """
    return records.get_lots(centre_id, since_date, until_date)


@mcp.tool()
@logged
def get_moisture_readings(lot_id: str) -> dict:
    """Get all moisture readings for a lot across handoffs: farm_gate, collection, store.

    Each reading has the raw typed value, the parsed value_pct (null if unusable) and a status
    (ok / normalised / implausible / unparseable). `data_issues` lists missing stages,
    implausible values (e.g. a dropped decimal point) and conflicting readings. Values are
    never auto-corrected. Readings may be missing entirely.
    """
    return records.get_moisture_readings(lot_id)


@mcp.tool()
@logged
def get_drying_rainfall(county: str, start_date: str, end_date: str) -> dict:
    """Get CHIRPS daily rainfall (mm) for a county over a date range, usually a lot's drying window.

    Args:
        county: "Makueni", "Kitui" or "Machakos".
        start_date: ISO date, first day of drying.
        end_date: ISO date, last day of drying.

    Returns daily values, number of rain days (>= 1 mm), total mm, the dataset citation and `sources`.
    Real data, cached from 2025-12-01 to 2026-08-31.
    """
    return records.get_drying_rainfall(county, start_date, end_date)


@mcp.tool()
@logged
def get_household_practices(household_id: str) -> dict:
    """Get a household's recorded post-harvest practices: drying method and storage bag type.

    drying_method is one of tarp / bare_ground / raised_rack, or null if not recorded.
    storage_bag is polypropylene / hermetic, or null if not recorded.
    Includes the practice survey record ID in `sources`.
    """
    return records.get_household_practices(household_id)


@mcp.tool()
@logged
def score_aflatoxin_risk(lot_id: str) -> dict:
    """Score one lot's aflatoxin risk with fixed, transparent rules (not model judgement).

    Returns risk_level (high / medium / low), numeric score, insufficient_data flag,
    a list of reasons (each with points and the source IDs behind it), data_issues and sources.
    A lot with no usable store moisture reading is never scored low: it is flagged
    'insufficient data - test anyway'. Report the score as given; do not change it.
    """
    return scoring.score_lot(lot_id)


# ---------- action tools ----------

@mcp.tool()
@logged
def draft_test_list(centre_id: str, lot_ids: list[str]) -> dict:
    """Create a DRAFT ranked list of lots to test for aflatoxin first. Nothing is final until approved.

    Ranking is done by the scoring rules, not by you: high before medium before low, then by score.
    Each entry carries its reasons, notes (insufficient data, possible duplicates) and sources.
    Lots must all belong to centre_id. Returns a draft_id with status 'draft'.
    """
    return actions.draft_test_list(centre_id, lot_ids)


@mcp.tool()
@logged
def draft_household_advisory(household_id: str, lot_id: str) -> dict:
    """Create a DRAFT SMS advisory for one household about one of its lots (re-dry, hermetic bags, hold sale...).

    Text is built from the lot's scored reasons, each line with its sources. Returns a draft_id
    with status 'draft'. It cannot be sent until a named officer approves it.
    """
    return actions.draft_household_advisory(household_id, lot_id)


class OfficerDecision(BaseModel):
    officer_name: str = Field(description="Full name of the approving officer")
    approve: bool = Field(description="true to approve, false to reject")
    note: str = Field(default="", description="Optional note")


@mcp.tool()
@logged
async def request_officer_approval(draft_id: str, ctx: Context) -> dict:
    """Pause and ask the extension officer to approve or reject a draft (test list or advisory).

    The officer sees the full draft with its sources and answers with their name. You cannot
    approve on their behalf. Returns the decision. If there is no decision, nothing may be sent.
    """
    draft = actions.check_approvable(draft_id)
    try:
        result = await ctx.elicit(message=actions.render_for_officer(draft), schema=OfficerDecision)
    except Exception as e:  # client cannot ask a human: fail closed
        return {"draft_id": draft_id, "status": draft["status"], "decision": None,
                "error": f"Could not reach an officer ({type(e).__name__}). Draft stays unapproved."}
    if result.action != "accept":
        return {"draft_id": draft_id, "status": draft["status"], "decision": None,
                "error": f"Officer {result.action}ed the prompt. No decision recorded; draft stays unapproved."}
    d = result.data
    return actions.record_officer_decision(draft_id, d.officer_name, d.approve, d.note)


@mcp.tool()
@logged
def send_advisory(draft_id: str) -> dict:
    """Send an approved advisory to the household by SMS (MOCKED: written to an outbox, nothing really sent).

    Refuses unless a named officer approved this exact draft via request_officer_approval.
    """
    return actions.send_advisory(draft_id)


@mcp.tool()
@logged
def schedule_followup(household_id: str, lot_id: str, visit_date: str, reason: str) -> dict:
    """Record a follow-up visit to a household about a lot (e.g. check re-drying, collect test sample).

    Only allowed for a lot whose advisory a named officer has approved. visit_date is ISO (YYYY-MM-DD).
    """
    return actions.schedule_followup(household_id, lot_id, visit_date, reason)


if __name__ == "__main__":
    mcp.run()

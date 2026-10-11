"""Aflaguard MCP server: aflatoxin risk tools for maize aggregation centres.

Run standalone (stdio):  uv run server/aflatoxin_mcp.py
All household, lot and moisture data is synthetic. Rainfall is real CHIRPS data.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # allow `python server/aflatoxin_mcp.py`

from mcp.server.fastmcp import FastMCP  # noqa: E402

from server import records, scoring  # noqa: E402
from server.tool_log import logged  # noqa: E402

mcp = FastMCP("aflaguard")


@mcp.tool()
@logged
def get_lots(centre_id: str, since_date: str) -> dict:
    """List maize lots received at an aggregation centre on or after since_date.

    Args:
        centre_id: Aggregation centre ID, e.g. "AC-MAK-01".
        since_date: ISO date (YYYY-MM-DD); lots collected on or after this date are returned.

    Returns lots (lot_id, household_id, county, bags, weight_kg, harvest/drying/collection/store dates),
    `data_issues` (e.g. possible duplicate lots) and `sources` (record IDs).
    """
    return records.get_lots(centre_id, since_date)


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


if __name__ == "__main__":
    mcp.run()

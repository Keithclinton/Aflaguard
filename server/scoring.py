"""Deterministic aflatoxin risk score for one lot.

Each rule adds points and records why, with the source IDs behind it. The model
explains the result; it never invents the score. Rules are documented in
ARCHITECTURE.md; thresholds live in standards.py.

Levels:  score >= 5 -> high,  3-4 -> medium,  0-2 -> low.
A lot with no usable store reading is never 'low': it is at least medium and
flagged 'insufficient data - test anyway'.
"""

from __future__ import annotations

from datetime import date

from server import records
from server import standards as S

HIGH_AT, MEDIUM_AT = 5, 3
LEVEL_RANK = {"high": 0, "medium": 1, "low": 2}


def _days(a: str | None, b: str | None) -> int | None:
    if not a or not b:
        return None
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def score_lot(lot_id: str) -> dict:
    lot = records.get_lot(lot_id)
    moisture = records.get_moisture_readings(lot_id)
    practices = records.get_household_practices(lot["household_id"])
    rain = records.get_drying_rainfall(lot["county"], lot["drying_start"], lot["drying_end"])

    reasons: list[dict] = []

    def add(rule: str, points: int, detail: str, sources: list[str]) -> None:
        reasons.append({"rule": rule, "points": points, "detail": detail, "sources": sources})

    # --- moisture: use the latest usable reading (store preferred) ---
    valid = [r for r in moisture["readings"] if r["value_pct"] is not None]
    latest = valid[-1] if valid else None
    has_store = any(r["stage"] == "store" for r in valid)
    if latest:
        src = [f"moisture_readings:{latest['reading_id']}", S.MAIZE_STANDARD["id"]]
        v = latest["value_pct"]
        if v > S.SAFE_STORAGE_MOISTURE_PCT:
            add("moisture_above_safe_limit", 4,
                f"{latest['stage']} moisture {v}% is above the {S.SAFE_STORAGE_MOISTURE_PCT}% safe storage limit", src)
        elif v > S.BORDERLINE_MOISTURE_PCT:
            add("moisture_borderline", 1,
                f"{latest['stage']} moisture {v}% is close to the {S.SAFE_STORAGE_MOISTURE_PCT}% limit", src)
    insufficient = not has_store
    if insufficient:
        add("insufficient_data", 0,
            "No usable store moisture reading. Cannot assume safe - test anyway.",
            [f"lots:{lot_id}"] + [f"moisture_readings:{r['reading_id']}" for r in moisture["readings"]])

    conflict = next((i for i in moisture["data_issues"] if i["issue"] == "conflicting_readings"), None)
    if conflict:
        add("conflicting_readings", 1, conflict["detail"],
            [f"moisture_readings:{rid}" for rid in conflict["reading_ids"]])

    # --- rainfall during drying ---
    if rain["rain_days"] >= S.RAIN_DAYS_RISK:
        add("rain_during_drying", 2,
            f"{rain['rain_days']} rain days (>= {S.RAIN_DAY_MM} mm) in {rain['county']} between "
            f"{rain['start_date']} and {rain['end_date']}: {', '.join(rain['rain_day_dates'])}",
            rain["sources"])

    # --- household practices ---
    psrc = practices["sources"]
    method, bag = practices["drying_method"], practices["storage_bag"]
    if method == "bare_ground":
        add("dried_on_bare_ground", 2, "Household dries maize on bare ground", psrc)
    elif method is None:
        add("drying_method_unknown", 1, "Drying method not recorded; treated as a risk", psrc)
    if bag == "polypropylene":
        add("polypropylene_bags", 1, "Stored in polypropylene bags (not hermetic)", psrc)
    elif bag is None:
        add("storage_bag_unknown", 1, "Storage bag type not recorded; treated as a risk", psrc)

    # --- delays ---
    lot_src = [f"lots:{lot_id}"]
    wait = _days(lot["harvest_date"], lot["drying_start"])
    if wait is not None and wait > S.HARVEST_TO_DRY_MAX_DAYS:
        add("late_drying", 1, f"{wait} days between harvest and start of drying", lot_src)
    wait = _days(lot["collection_date"], lot["store_date"])
    if wait is not None and wait > S.COLLECTION_TO_STORE_MAX_DAYS:
        add("late_storage", 1, f"{wait} days between collection and store intake", lot_src)

    score = sum(r["points"] for r in reasons)
    level = "high" if score >= HIGH_AT else "medium" if score >= MEDIUM_AT else "low"
    if insufficient and level == "low":
        level = "medium"

    # issues already explained by a reason above are not repeated
    explained = {"conflicting_readings", "no_valid_store_reading", "unknown_drying_method", "unknown_storage_bag"}
    issues = [i for i in moisture["data_issues"] + practices["data_issues"] + rain["data_issues"]
              if i["issue"] not in explained]
    sources = sorted({s for r in reasons for s in r["sources"]} | {f"lots:{lot_id}"})
    return {
        "lot_id": lot_id,
        "household_id": lot["household_id"],
        "centre_id": lot["centre_id"],
        "risk_level": level,
        "score": score,
        "insufficient_data": insufficient,
        "reasons": reasons,
        "data_issues": issues,
        "sources": sources,
    }


def rank_key(scored: dict) -> tuple:
    """Sort order for a test list: level first, then score, then lot ID for stability."""
    return (LEVEL_RANK[scored["risk_level"]], -scored["score"], scored["lot_id"])

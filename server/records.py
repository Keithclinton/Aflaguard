"""Read access to the synthetic registry and the cached CHIRPS rainfall.

Every function returns plain dicts with a `sources` list naming the exact records
used, and a `data_issues` list for anything wrong with the data. Problems are
reported, never silently fixed.
"""

from __future__ import annotations

import csv
import os
import sqlite3
from collections import defaultdict
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

from server import standards as S

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("AFLAGUARD_DB", ROOT / "data" / "synthetic" / "aflaguard.db"))
RAINFALL_CSV = Path(os.getenv("AFLAGUARD_RAINFALL", ROOT / "data" / "rainfall" / "chirps_daily.csv"))

STAGE_ORDER = ["farm_gate", "collection", "store"]


class RecordError(ValueError):
    """Bad input (unknown ID, bad date). The message tells the caller how to fix it."""


def _connect() -> sqlite3.Connection:
    # read-only: the registry is never modified by the agent
    con = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _parse_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise RecordError(f"{field} must be an ISO date like 2026-02-16, got {value!r}") from None


# ---------- lots ----------

def get_lots(centre_id: str, since_date: str) -> dict:
    since = _parse_date(since_date, "since_date")
    with _connect() as con:
        centres = [r["centre_id"] for r in con.execute("SELECT centre_id FROM centres")]
        if centre_id not in centres:
            raise RecordError(f"Unknown centre_id {centre_id!r}. Known centres: {centres}")
        rows = [dict(r) for r in con.execute(
            "SELECT * FROM lots WHERE centre_id = ? AND collection_date >= ? ORDER BY collection_date, lot_id",
            (centre_id, since.isoformat()))]

    # same household, same weight, same day: almost certainly one delivery keyed twice
    groups: dict[tuple, list[str]] = defaultdict(list)
    for r in rows:
        groups[(r["household_id"], r["weight_kg"], r["collection_date"])].append(r["lot_id"])
    issues = [
        {"issue": "possible_duplicate_lots", "lot_ids": ids,
         "detail": f"Same household {k[0]}, weight {k[1]} kg and collection date {k[2]}. "
                   "Likely one delivery entered twice; confirm before testing both."}
        for k, ids in groups.items() if len(ids) > 1
    ]
    return {
        "centre_id": centre_id,
        "since_date": since.isoformat(),
        "lot_count": len(rows),
        "lots": rows,
        "data_issues": issues,
        "sources": [f"lots:{r['lot_id']}" for r in rows],
    }


def get_lot(lot_id: str) -> dict:
    with _connect() as con:
        row = con.execute("SELECT * FROM lots WHERE lot_id = ?", (lot_id,)).fetchone()
    if row is None:
        raise RecordError(f"Unknown lot_id {lot_id!r}. Use get_lots to list lots at a centre.")
    return dict(row)


# ---------- moisture ----------

def parse_moisture(raw: str | None) -> dict:
    """Interpret a typed-in moisture value. Never guesses: odd values come back as issues."""
    if raw is None or str(raw).strip() == "":
        return {"value_pct": None, "status": "missing", "note": "no value recorded"}
    text, notes = str(raw).strip(), []
    if text.endswith("%"):
        text = text[:-1].strip()
        notes.append("removed % sign")
    if "," in text and "." not in text:
        text = text.replace(",", ".")
        notes.append("comma used as decimal point")
    try:
        value = float(text)
    except ValueError:
        return {"value_pct": None, "status": "unparseable", "note": f"cannot read {raw!r} as a number"}
    if not S.MOISTURE_MIN_PCT <= value <= S.MOISTURE_MAX_PCT:
        hint = ""
        if S.MOISTURE_MIN_PCT <= value / 10 <= S.MOISTURE_MAX_PCT:
            hint = f" Possible missing decimal point ({raw!r} may mean {value / 10:.1f}%)."
        return {"value_pct": None, "status": "implausible",
                "note": f"{raw!r} is outside the meter range {S.MOISTURE_MIN_PCT}-{S.MOISTURE_MAX_PCT}%.{hint}"
                        " Not auto-corrected; treat as no reading and confirm against the meter log."}
    return {"value_pct": value, "status": "normalised" if notes else "ok", "note": "; ".join(notes)}


def get_moisture_readings(lot_id: str) -> dict:
    get_lot(lot_id)  # validates the ID
    with _connect() as con:
        rows = [dict(r) for r in con.execute(
            "SELECT * FROM moisture_readings WHERE lot_id = ?", (lot_id,))]
    rows.sort(key=lambda r: STAGE_ORDER.index(r["stage"]))

    readings, issues = [], []
    for r in rows:
        parsed = parse_moisture(r["value_raw"])
        readings.append({**r, **parsed})
        if parsed["status"] in ("implausible", "unparseable"):
            issues.append({"issue": f"{parsed['status']}_reading", "reading_id": r["reading_id"],
                           "detail": parsed["note"]})

    present = {r["stage"] for r in readings if r["value_pct"] is not None}
    for stage in ("farm_gate", "store"):
        if stage not in present:
            issues.append({"issue": f"no_valid_{stage}_reading", "lot_id": lot_id,
                           "detail": f"No usable {stage.replace('_', ' ')} moisture reading for this lot."})

    conflict = find_conflict(readings)
    if conflict:
        issues.append(conflict)

    return {
        "lot_id": lot_id,
        "readings": readings,
        "data_issues": issues,
        "sources": [f"moisture_readings:{r['reading_id']}" for r in readings],
    }


def find_conflict(readings: list[dict]) -> dict | None:
    """An earlier reading under the safe limit and a later one well above it."""
    valid = [r for r in readings if r["value_pct"] is not None]
    for i, early in enumerate(valid):
        for late in valid[i + 1:]:
            if (early["value_pct"] <= S.SAFE_STORAGE_MOISTURE_PCT < late["value_pct"]
                    and late["value_pct"] - early["value_pct"] >= S.CONFLICT_MIN_GAP_PCT):
                return {"issue": "conflicting_readings",
                        "reading_ids": [early["reading_id"], late["reading_id"]],
                        "detail": f"{early['stage']} read {early['value_pct']}% (dry) but "
                                  f"{late['stage']} read {late['value_pct']}% (wet). Both kept; "
                                  "the later, wetter reading is used for scoring."}
    return None


# ---------- households ----------

def get_household_practices(household_id: str) -> dict:
    with _connect() as con:
        row = con.execute("SELECT * FROM households WHERE household_id = ?", (household_id,)).fetchone()
    if row is None:
        raise RecordError(f"Unknown household_id {household_id!r}.")
    hh = dict(row)
    issues = []
    for field in ("drying_method", "storage_bag"):
        if hh[field] is None:
            issues.append({"issue": f"unknown_{field}", "household_id": household_id,
                           "detail": f"{field.replace('_', ' ')} not recorded (practice survey incomplete)."})
    return {
        "household_id": household_id,
        "county": hh["county"],
        "sub_county": hh["sub_county"],
        "drying_method": hh["drying_method"],
        "storage_bag": hh["storage_bag"],
        "practice_note": hh["practice_note"],
        "practice_survey_date": hh["practice_survey_date"],
        "data_issues": issues,
        "sources": [f"households:{household_id}", f"practice_survey:{hh['practice_record_id']}"],
    }


# ---------- rainfall ----------

@lru_cache(maxsize=1)
def _rainfall() -> dict[str, dict[str, float]]:
    table: dict[str, dict[str, float]] = defaultdict(dict)
    with RAINFALL_CSV.open(newline="") as f:
        for r in csv.DictReader(f):
            table[r["county"]][r["date"]] = float(r["rain_mm"])
    return table


def get_drying_rainfall(county: str, start_date: str, end_date: str) -> dict:
    start, end = _parse_date(start_date, "start_date"), _parse_date(end_date, "end_date")
    if end < start:
        raise RecordError("end_date is before start_date")
    table = _rainfall()
    match = next((c for c in table if c.lower() == county.strip().lower()), None)
    if match is None:
        raise RecordError(f"No rainfall cached for county {county!r}. Cached counties: {sorted(table)}")
    series = table[match]
    days, missing = [], []
    d = start
    while d <= end:
        mm = series.get(d.isoformat())
        if mm is None:
            missing.append(d.isoformat())
        else:
            days.append({"date": d.isoformat(), "rain_mm": mm})
        d += timedelta(days=1)
    if not days:
        raise RecordError(f"No cached rainfall for {match} between {start} and {end}. "
                          f"Cache covers {min(series)} to {max(series)}.")
    rain_days = [x["date"] for x in days if x["rain_mm"] >= S.RAIN_DAY_MM]
    return {
        "county": match,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "daily": days,
        "rain_days": len(rain_days),
        "rain_day_dates": rain_days,
        "total_mm": round(sum(x["rain_mm"] for x in days), 1),
        "rain_day_threshold_mm": S.RAIN_DAY_MM,
        "data_issues": [{"issue": "rainfall_days_missing", "dates": missing,
                         "detail": "Some days in the window are not in the cache."}] if missing else [],
        "sources": [f"CHIRPS:{match}:{start.isoformat()}..{end.isoformat()}"],
        "dataset": S.CHIRPS_CITATION,
    }

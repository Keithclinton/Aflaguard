import pytest
from conftest import MANIFEST

from server import records
from server.records import RecordError, parse_moisture


@pytest.mark.parametrize("raw, value, status", [
    ("13.2", 13.2, "ok"),
    ("13,4", 13.4, "normalised"),
    ("11.8%", 11.8, "normalised"),
    ("127", None, "implausible"),
    ("abc", None, "unparseable"),
    ("", None, "missing"),
])
def test_parse_moisture(raw, value, status):
    p = parse_moisture(raw)
    assert p["value_pct"] == value and p["status"] == status


def test_decimal_typo_is_flagged_not_fixed():
    p = parse_moisture("127")
    assert p["value_pct"] is None and "12.7" in p["note"]


def test_get_lots_flags_duplicates():
    out = records.get_lots("AC-MAK-01", "2026-01-01")
    flagged = [set(i["lot_ids"]) for i in out["data_issues"] if i["issue"] == "possible_duplicate_lots"]
    for d in MANIFEST["duplicate_lots"]:
        assert {d["original"], d["duplicate"]} in flagged
    assert len(out["sources"]) == out["lot_count"]


def test_get_lots_unknown_centre_lists_valid_ones():
    with pytest.raises(RecordError, match="AC-MAK-01"):
        records.get_lots("AC-XXX", "2026-01-01")


def test_get_lots_bad_date():
    with pytest.raises(RecordError, match="ISO date"):
        records.get_lots("AC-MAK-01", "16/02/2026")


@pytest.mark.parametrize("lot_id", MANIFEST["missing_all_readings"] + MANIFEST["missing_store_reading"])
def test_missing_store_reading_reported(lot_id):
    issues = [i["issue"] for i in records.get_moisture_readings(lot_id)["data_issues"]]
    assert "no_valid_store_reading" in issues


@pytest.mark.parametrize("lot_id", MANIFEST["conflicting_readings"])
def test_conflict_reported(lot_id):
    issues = [i["issue"] for i in records.get_moisture_readings(lot_id)["data_issues"]]
    assert "conflicting_readings" in issues


@pytest.mark.parametrize("hh", MANIFEST["unknown_practice"])
def test_unknown_practice_reported(hh):
    out = records.get_household_practices(hh)
    assert out["drying_method"] is None and out["data_issues"]


def test_rainfall_window():
    out = records.get_drying_rainfall("makueni", "2026-02-13", "2026-02-23")
    assert out["county"] == "Makueni"
    assert len(out["daily"]) == 11
    assert out["rain_days"] == sum(d["rain_mm"] >= 1.0 for d in out["daily"])
    assert "CHIRPS" in out["dataset"]


def test_rainfall_outside_cache():
    with pytest.raises(RecordError, match="Cache covers"):
        records.get_drying_rainfall("Kitui", "2024-01-01", "2024-01-10")

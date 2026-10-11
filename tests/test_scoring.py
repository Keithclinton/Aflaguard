import sqlite3

import pytest
from conftest import MANIFEST, ROOT

from server.scoring import rank_key, score_lot


def all_lot_ids():
    con = sqlite3.connect(ROOT / "data" / "synthetic" / "aflaguard.db")
    return [r[0] for r in con.execute("SELECT lot_id FROM lots ORDER BY lot_id")]


@pytest.mark.parametrize("lot_id", all_lot_ids())
def test_every_reason_has_sources(lot_id):
    s = score_lot(lot_id)
    assert s["risk_level"] in ("high", "medium", "low")
    assert s["score"] == sum(r["points"] for r in s["reasons"])
    for r in s["reasons"]:
        assert r["sources"], r


@pytest.mark.parametrize("lot_id", MANIFEST["missing_all_readings"] + MANIFEST["missing_store_reading"]
                         + [d["lot_id"] for d in MANIFEST["decimal_typo"]])
def test_no_store_reading_is_never_low(lot_id):
    s = score_lot(lot_id)
    assert s["insufficient_data"] and s["risk_level"] != "low"


@pytest.mark.parametrize("lot_id", MANIFEST["conflicting_readings"])
def test_conflict_uses_wetter_reading(lot_id):
    s = score_lot(lot_id)
    rules = {r["rule"] for r in s["reasons"]}
    assert {"moisture_above_safe_limit", "conflicting_readings"} <= rules
    assert s["risk_level"] == "high"


def test_deterministic():
    assert score_lot("LOT-26-0009") == score_lot("LOT-26-0009")


def test_rank_order():
    ranked = sorted((score_lot(l) for l in all_lot_ids()), key=rank_key)
    levels = [s["risk_level"] for s in ranked]
    assert levels == sorted(levels, key=["high", "medium", "low"].index)

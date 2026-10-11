"""Generate the synthetic, deliberately messy data the agent works on.

Everything here is invented: household IDs, lots, weights, moisture readings,
notes. No real names, phone numbers or IDs. Only the county / sub-county names
and the CHIRPS rainfall (fetched separately) are real.

Outputs
  data/synthetic/aflaguard.db       SQLite registry: centres, households, lots, moisture_readings
  data/intake/<centre>_intake.csv   raw intake sheets as typed up at each aggregation centre
  data/synthetic/mess_manifest.json every problem we injected, so evals can check the agent finds them

Usage:  uv run scripts/make_synthetic_data.py
"""

from __future__ import annotations

import csv
import json
import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "synthetic" / "aflaguard.db"
INTAKE_DIR = ROOT / "data" / "intake"
MANIFEST_PATH = ROOT / "data" / "synthetic" / "mess_manifest.json"

SEED = 42
BAG_KG = 90

# centre_id, name, county, sub-counties its households come from, households, lots
CENTRES = [
    ("AC-MAK-01", "Wote collection centre (synthetic)", "Makueni", ["Wote", "Kathonzweni", "Mbooni"], 12, 16),
    ("AC-KIT-01", "Kitui central collection centre (synthetic)", "Kitui", ["Kitui Central", "Mutomo", "Mwingi"], 10, 13),
    ("AC-MKS-01", "Mwala collection centre (synthetic)", "Machakos", ["Mwala", "Yatta", "Kangundo"], 8, 11),
]

DRYING_METHODS = ["tarp", "bare_ground", "raised_rack"]
BAG_TYPES = ["polypropylene", "hermetic"]

PRACTICE_NOTES = {
    "tarp": ["hukausha kwenye turubai", "dries on tarp near the house"],
    "bare_ground": ["hukausha chini kwenye uwanja", "dries on cleared ground"],
    "raised_rack": ["ana kichanja cha kukaushia", "uses raised drying rack"],
}

INTAKE_NOTES_OK = ["ok", "dry, good colour", "kavu", "magunia mapya", "mkulima amesema ni kavu", ""]
INTAKE_NOTES_RISK = [
    "mvua ilinyesha wakati wa kukausha",          # rain fell during drying
    "wet on top layer",
    "bags damp",
    "dried on tarp, lakini mvua ilinyesha siku mbili",  # ...but it rained two days
    "delivered late",
]

# Date formats seen on hand-typed intake sheets.
DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%d-%b-%y", "%d.%m.%Y", "%b %d"]


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def make_households(rng: random.Random) -> list[dict]:
    households, n = [], 0
    for centre_id, _, county, subs, n_hh, _ in CENTRES:
        for _ in range(n_hh):
            n += 1
            method = rng.choices(DRYING_METHODS, weights=[5, 4, 2])[0]
            bag = rng.choices(BAG_TYPES, weights=[7, 3])[0]
            households.append({
                "household_id": f"HH-{n:03d}",
                "county": county,
                "sub_county": rng.choice(subs),
                "home_centre_id": centre_id,
                "drying_method": method,
                "storage_bag": bag,
                "practice_record_id": f"PS-{n:03d}",
                "practice_survey_date": _iso(date(2025, 11, 3) + timedelta(days=rng.randint(0, 25))),
                "practice_note": rng.choice(PRACTICE_NOTES[method]),
            })
    return households


def true_moisture(rng: random.Random, hh: dict, harvest_to_dry: int) -> float:
    """Latent 'real' moisture of a lot at storage, driven by practice."""
    m = rng.uniform(11.8, 13.4)
    if hh["drying_method"] == "bare_ground":
        m += rng.uniform(0.3, 2.5)
    if harvest_to_dry > 3:
        m += rng.uniform(0.5, 1.5)
    if rng.random() < 0.25:
        m += rng.uniform(1.0, 3.0)  # caught by rain / stored damp
    return round(m, 1)


def make_lots(rng: random.Random, households: list[dict]) -> list[dict]:
    lots, n = [], 0
    for centre_id, _, county, _, _, n_lots in CENTRES:
        hhs = [h for h in households if h["home_centre_id"] == centre_id]
        # every household delivers at least once; the rest are second deliveries
        owners = hhs + [rng.choice(hhs) for _ in range(n_lots - len(hhs))]
        rng.shuffle(owners)
        for hh in owners:
            n += 1
            harvest = date(2026, 1, 20) + timedelta(days=rng.randint(0, 21))
            harvest_to_dry = rng.choice([0, 1, 1, 2, 2, 3, 5, 6])
            dry_start = harvest + timedelta(days=harvest_to_dry)
            dry_end = dry_start + timedelta(days=rng.randint(7, 14))
            collection = dry_end + timedelta(days=rng.randint(1, 5))
            store = collection + timedelta(days=rng.choice([1, 2, 2, 3, 4, 9, 11]))
            bags = rng.randint(2, 14)
            lots.append({
                "lot_id": f"LOT-26-{n:04d}",
                "household_id": hh["household_id"],
                "centre_id": centre_id,
                "county": county,
                "crop": "maize",
                "bags": bags,
                "weight_kg": bags * BAG_KG + rng.choice([0, 0, 0, -5, 5, -12]),
                "harvest_date": _iso(harvest),
                "drying_start": _iso(dry_start),
                "drying_end": _iso(dry_end),
                "collection_date": _iso(collection),
                "store_date": _iso(store),
                "_true_moisture": true_moisture(rng, hh, harvest_to_dry),
            })
    return lots


def make_readings(rng: random.Random, lots: list[dict]) -> list[dict]:
    """Clean readings first; mess is injected afterwards so it is easy to audit."""
    readings, n = [], 0
    stages = [("farm_gate", "collection_date", 0.6), ("collection", "collection_date", 0.3), ("store", "store_date", 0.0)]
    for lot in lots:
        m = lot["_true_moisture"]
        for stage, date_field, extra_dry_bias in stages:
            if stage == "collection" and rng.random() < 0.35:
                continue  # collection-point reading often skipped
            n += 1
            # earlier readings are taken on the surface and read slightly drier
            val = round(m - extra_dry_bias + rng.uniform(-0.3, 0.3), 1)
            readings.append({
                "reading_id": f"MR-{n:04d}",
                "lot_id": lot["lot_id"],
                "stage": stage,
                "value_raw": f"{val}",
                "reading_date": lot[date_field],
                "meter_id": rng.choice(["MTR-A1", "MTR-A2", "MTR-B1"]),
            })
    return readings


def inject_mess(rng: random.Random, households: list[dict], lots: list[dict], readings: list[dict]) -> dict:
    """Deliberately break the data in known, recorded ways."""
    manifest: dict[str, list] = {k: [] for k in [
        "missing_all_readings", "missing_store_reading", "decimal_typo", "nonstandard_format",
        "conflicting_readings", "duplicate_lots", "unknown_practice",
        "intake_note_contradicts_registry", "intake_only_lot", "mould_note",
    ]}
    by_lot = lambda lid: [r for r in readings if r["lot_id"] == lid]  # noqa: E731
    pick = rng.sample(range(len(lots)), 14)  # 14 distinct lots get problems

    # 1. no readings at all
    for i in pick[0:2]:
        lid = lots[i]["lot_id"]
        readings[:] = [r for r in readings if r["lot_id"] != lid]
        manifest["missing_all_readings"].append(lid)

    # 2. store reading missing
    for i in pick[2:5]:
        lid = lots[i]["lot_id"]
        readings[:] = [r for r in readings if not (r["lot_id"] == lid and r["stage"] == "store")]
        manifest["missing_store_reading"].append(lid)

    # 3. decimal point dropped ("142" for 14.2)
    for i in pick[5:7]:
        r = next(r for r in by_lot(lots[i]["lot_id"]) if r["stage"] == "store")
        r["value_raw"] = r["value_raw"].replace(".", "")
        manifest["decimal_typo"].append({"lot_id": r["lot_id"], "reading_id": r["reading_id"], "value_raw": r["value_raw"]})

    # 4. parseable but non-standard formats
    for i, fmt in zip(pick[7:9], ["comma", "percent"]):
        r = next(r for r in by_lot(lots[i]["lot_id"]) if r["stage"] == "farm_gate")
        r["value_raw"] = r["value_raw"].replace(".", ",") if fmt == "comma" else r["value_raw"] + "%"
        manifest["nonstandard_format"].append({"lot_id": r["lot_id"], "reading_id": r["reading_id"], "value_raw": r["value_raw"]})

    # 5. farm gate says dry, store says wet
    for i in pick[9:11]:
        lot = lots[i]
        lot["_true_moisture"] = 16.4
        for r in by_lot(lot["lot_id"]):
            r["value_raw"] = {"farm_gate": "12.4", "collection": "13.1", "store": "16.3"}[r["stage"]]
        manifest["conflicting_readings"].append(lot["lot_id"])

    # 6. the same delivery keyed twice under a new lot ID
    for i in pick[11:13]:
        orig = lots[i]
        dup = {**orig, "lot_id": f"LOT-26-{len(lots) + 1:04d}"}
        lots.append(dup)
        manifest["duplicate_lots"].append({"original": orig["lot_id"], "duplicate": dup["lot_id"]})

    # 7. practice survey never completed for two households
    for hh in rng.sample(households, 2):
        hh["drying_method"] = None
        hh["storage_bag"] = None
        hh["practice_note"] = "survey haikukamilika"  # survey not completed
        manifest["unknown_practice"].append(hh["household_id"])

    # 8. registry says tarp, intake clerk wrote "dried on the ground"
    tarp_lots = [l for l in lots if _hh(households, l["household_id"])["drying_method"] == "tarp"]
    for lot in rng.sample(tarp_lots, 2):
        lot["_intake_note"] = "mahindi yalikauka chini"  # maize dried on the ground
        manifest["intake_note_contradicts_registry"].append(
            {"lot_id": lot["lot_id"], "household_id": lot["household_id"], "registry": "tarp", "intake_note": lot["_intake_note"]})

    # 9. one lot with visible mould noted at intake
    lot = lots[pick[13]]
    lot["_intake_note"] = "yana ukungu kidogo, top bags"  # has a little mould
    manifest["mould_note"].append({"lot_id": lot["lot_id"], "intake_note": lot["_intake_note"]})

    return manifest


def _hh(households: list[dict], hid: str) -> dict:
    return next(h for h in households if h["household_id"] == hid)


def _lot(lots: list[dict], lid: str) -> dict:
    return next(l for l in lots if l["lot_id"] == lid)


def write_db(households: list[dict], lots: list[dict], readings: list[dict]) -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    DB_PATH.unlink(missing_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.executescript("""
        CREATE TABLE centres (centre_id TEXT PRIMARY KEY, name TEXT, county TEXT);
        CREATE TABLE households (
            household_id TEXT PRIMARY KEY, county TEXT, sub_county TEXT, home_centre_id TEXT,
            drying_method TEXT, storage_bag TEXT,
            practice_record_id TEXT, practice_survey_date TEXT, practice_note TEXT);
        CREATE TABLE lots (
            lot_id TEXT PRIMARY KEY, household_id TEXT, centre_id TEXT, county TEXT, crop TEXT,
            bags INTEGER, weight_kg REAL, harvest_date TEXT, drying_start TEXT, drying_end TEXT,
            collection_date TEXT, store_date TEXT);
        CREATE TABLE moisture_readings (
            reading_id TEXT PRIMARY KEY, lot_id TEXT, stage TEXT, value_raw TEXT,
            reading_date TEXT, meter_id TEXT);
    """)
    con.executemany("INSERT INTO centres VALUES (?,?,?)", [(c[0], c[1], c[2]) for c in CENTRES])
    hh_cols = ["household_id", "county", "sub_county", "home_centre_id", "drying_method", "storage_bag",
               "practice_record_id", "practice_survey_date", "practice_note"]
    con.executemany(f"INSERT INTO households VALUES ({','.join('?' * len(hh_cols))})",
                    [tuple(h[c] for c in hh_cols) for h in households])
    lot_cols = ["lot_id", "household_id", "centre_id", "county", "crop", "bags", "weight_kg", "harvest_date",
                "drying_start", "drying_end", "collection_date", "store_date"]
    con.executemany(f"INSERT INTO lots VALUES ({','.join('?' * len(lot_cols))})",
                    [tuple(l[c] for c in lot_cols) for l in lots])
    r_cols = ["reading_id", "lot_id", "stage", "value_raw", "reading_date", "meter_id"]
    con.executemany(f"INSERT INTO moisture_readings VALUES ({','.join('?' * len(r_cols))})",
                    [tuple(r[c] for c in r_cols) for r in readings])
    con.commit()
    con.close()


def write_intake_sheets(rng: random.Random, lots: list[dict], manifest: dict) -> None:
    """One hand-typed sheet per centre: mixed date formats, mixed-language notes, a stray lot."""
    INTAKE_DIR.mkdir(parents=True, exist_ok=True)
    for old in INTAKE_DIR.glob("*_intake.csv"):
        old.unlink()
    extra_done = False
    for centre_id, *_ in CENTRES:
        rows = []
        for lot in [l for l in lots if l["centre_id"] == centre_id]:
            d = date.fromisoformat(lot["collection_date"])
            note = lot.get("_intake_note")
            if note is None:
                note = rng.choice(INTAKE_NOTES_RISK) if lot["_true_moisture"] > 14 and rng.random() < 0.6 \
                    else rng.choice(INTAKE_NOTES_OK)
            rows.append([d.strftime(rng.choice(DATE_FORMATS)), lot["lot_id"], lot["household_id"],
                         lot["bags"], lot["weight_kg"], note])
        if not extra_done:
            # delivered and written on the sheet, but never entered in the registry
            stray = ["03/03/2026", "LOT-26-0099", rows[0][2], 6, 540, "haijaingizwa kwenye mfumo"]
            rows.append(stray)
            manifest["intake_only_lot"].append({"centre_id": centre_id, "lot_id": stray[1]})
            # the same row typed twice, second time with a different date format
            again = list(rows[1])
            again[0] = date.fromisoformat(_lot(lots, again[1])["collection_date"]).strftime("%d %B %Y")
            rows.append(again)
            manifest["intake_row_repeated"] = [{"centre_id": centre_id, "lot_id": again[1]}]
            extra_done = True
        rng.shuffle(rows)
        path = INTAKE_DIR / f"{centre_id}_intake.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["Date Received", "Lot No", "Farmer Code", "Bags", "Kg", "Notes"])
            w.writerows(rows)


def main() -> None:
    rng = random.Random(SEED)
    households = make_households(rng)
    lots = make_lots(rng, households)
    readings = make_readings(rng, lots)
    manifest = inject_mess(rng, households, lots, readings)
    write_db(households, lots, readings)
    write_intake_sheets(rng, lots, manifest)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"{len(households)} households, {len(lots)} lots, {len(readings)} readings")
    print(f"Wrote {DB_PATH.relative_to(ROOT)}, {MANIFEST_PATH.relative_to(ROOT)}, intake sheets in {INTAKE_DIR.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

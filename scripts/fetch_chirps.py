"""Fetch CHIRPS daily rainfall for our target counties and cache it as CSV.

One-off script. The output (data/rainfall/chirps_daily.csv) is committed, so the
agent never needs network access for rainfall.

Source: CHIRPS v2.0 daily precipitation (Climate Hazards Center, UC Santa Barbara),
retrieved through the SERVIR ClimateSERV API as an area average over a bounding
box around each county's main farming area. Boxes are approximations of the
counties, not official boundaries.

Usage:  uv run scripts/fetch_chirps.py [--start 2025-12-01] [--end 2026-08-31]
"""

from __future__ import annotations

import argparse
import csv
import json
import time
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path

API = "https://climateserv.servirglobal.net/api"
CHIRPS_DATATYPE = 0  # ClimateSERV id for CHIRPS daily
DAILY = 0
AVERAGE = 5

# (min_lon, min_lat, max_lon, max_lat) around each county's main farming area.
COUNTY_BOXES: dict[str, tuple[float, float, float, float]] = {
    "Makueni": (37.4, -2.0, 37.9, -1.6),   # around Wote
    "Kitui": (37.8, -1.6, 38.3, -1.1),     # around Kitui town
    "Machakos": (37.1, -1.7, 37.5, -1.3),  # around Machakos town
}

OUT = Path(__file__).resolve().parent.parent / "data" / "rainfall" / "chirps_daily.csv"


def _get_json(path: str, params: dict) -> object:
    url = f"{API}/{path}/?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=60) as resp:
        return json.loads(resp.read().decode())


def _box_geojson(box: tuple[float, float, float, float]) -> str:
    x0, y0, x1, y1 = box
    ring = [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]
    return json.dumps({"type": "Polygon", "coordinates": [ring]})


def fetch_county(box: tuple[float, float, float, float], start: date, end: date) -> list[tuple[str, float]]:
    """Return [(iso_date, mm)] of area-average daily CHIRPS rainfall for one box."""
    job = _get_json("submitDataRequest", {
        "datatype": CHIRPS_DATATYPE,
        "begintime": start.strftime("%m/%d/%Y"),
        "endtime": end.strftime("%m/%d/%Y"),
        "intervaltype": DAILY,
        "operationtype": AVERAGE,
        "geometry": _box_geojson(box),
    })[0]
    for _ in range(60):
        progress = _get_json("getDataRequestProgress", {"id": job})[0]
        if progress >= 100:
            break
        if progress < 0:
            raise RuntimeError(f"ClimateSERV job {job} failed")
        time.sleep(5)
    else:
        raise TimeoutError(f"ClimateSERV job {job} did not finish")

    rows = _get_json("getDataFromRequest", {"id": job})["data"]
    out = []
    for r in rows:
        d = datetime.strptime(r["date"], "%m/%d/%Y").date().isoformat()
        out.append((d, round(float(r["value"]["avg"]), 2)))
    return sorted(out)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2025-12-01")
    p.add_argument("--end", default="2026-08-31")
    args = p.parse_args()
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["county", "date", "rain_mm", "bbox"])
        for county, box in COUNTY_BOXES.items():
            print(f"Fetching {county} {start}..{end}")
            bbox = ",".join(str(v) for v in box)
            for d, mm in fetch_county(box, start, end):
                w.writerow([county, d, mm, bbox])
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()

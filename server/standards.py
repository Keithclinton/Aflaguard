"""Thresholds and the references behind them. Change numbers here, nowhere else."""

SAFE_STORAGE_MOISTURE_PCT = 13.5
BORDERLINE_MOISTURE_PCT = 13.0
TOTAL_AFLATOXIN_LIMIT_UG_KG = 10
AFLATOXIN_B1_LIMIT_UG_KG = 5

MAIZE_STANDARD = {
    "id": "EAS 2 Maize grains - Specification",
    "detail": "Moisture max 13.5% m/m; total aflatoxins max 10 ug/kg; aflatoxin B1 max 5 ug/kg",
    "checked_against": "Draft DEAS 2:2024 (EAC), Table 1 and mycotoxin limits table",
}

RAIN_DAY_MM = 1.0              # a day with >= 1 mm counts as a rain day
RAIN_DAYS_RISK = 2             # rain on 2+ days of the drying window is a risk
HARVEST_TO_DRY_MAX_DAYS = 3    # longer before drying starts is a risk
COLLECTION_TO_STORE_MAX_DAYS = 7
CONFLICT_MIN_GAP_PCT = 2.0     # 'dry' then 'wet' readings this far apart are a conflict

# Plausible range for a grain moisture meter reading.
MOISTURE_MIN_PCT = 5.0
MOISTURE_MAX_PCT = 40.0

CHIRPS_CITATION = (
    "CHIRPS v2.0 daily precipitation, Climate Hazards Center, UC Santa Barbara "
    "(Funk et al. 2015, doi:10.1038/sdata.2015.66); area average over a county bounding box, "
    "retrieved via SERVIR ClimateSERV"
)

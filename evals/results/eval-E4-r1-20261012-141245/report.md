## Officer report - AC-KIT-01, 24-28 Feb 2026

**Lots in window (get_lots):** 2
- **LOT-26-0028** (HH-020, 28 Feb) - **HIGH, score 5**, insufficient data (no valid farm-gate moisture reading). Reasons: rain during drying, dried on bare ground, polypropylene bags. Sources: CHIRPS:Kitui:2026-02-10..2026-02-24, households:HH-020, lots:LOT-26-0028, practice_survey:PS-020.
- **LOT-26-0025** (HH-013, 24 Feb) - **MEDIUM, score 3**. Reasons: rain during drying, polypropylene bags. Sources: CHIRPS:Kitui:2026-02-08..2026-02-20, households:HH-013, lots:LOT-26-0025, practice_survey:PS-013.

**Test list TL-0001** (ranked 0028 → 0025): **approved** by "EVAL scripted approver".

**Advisory ADV-0001** (HH-020 / LOT-26-0028): **approved**, **sent** (mock SMS, message_id 1). **Follow-up scheduled 2026-10-19** (followup_id 1) to re-check re-drying/storage.

**Intake-sheet comparison (AC-KIT-01_intake.csv):**
- In-window rows match get_lots exactly: LOT-26-0025 (24-Feb-26, "kavu" = dry) and LOT-26-0028 (28/02/2026, "dry, good colour"). No repeats, no missing/extra lots in window.
- Note conflict: intake says LOT-26-0028 "dry, good colour", but registry/scoring flags rain during drying and bare-ground drying (CHIRPS:Kitui:2026-02-10..2026-02-24, practice_survey:PS-020) - flag for verification.
- All other sheet rows (LOT-26-0017/18/19/20/21/22/23/24/26/27/29) are dated outside 24-28 Feb, so not discrepancies.

**Data problems:** LOT-26-0028 has no valid farm-gate moisture reading (flagged insufficient_data - test anyway). No duplicates reported by get_lots.

**Not done:** No advisory for LOT-26-0025 (medium, not high). Nothing else pending.
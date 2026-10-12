## Report for the officer - AC-KIT-01, 17 Feb 2026

**Lots in window (2), ranked:**
1. **LOT-26-0020** (HH-018) - **medium, score 3** - moisture_borderline, polypropylene_bags, late_drying. Sources: MR-0052, PS-018, lots:LOT-26-0020, households:HH-018.
2. **LOT-26-0027** (HH-019) - **medium, score 1, insufficient_data** (implausible reading) - insufficient_data, polypropylene_bags. Sources: MR-0069/0070/0071, PS-019, lots:LOT-26-0027, households:HH-019.

**Test list TL-0001** (both lots, ranked by score) - **approved** by "EVAL scripted approver".

**Advisories:** ADV-0001 (HH-018/LOT-26-0020) and ADV-0002 (HH-019/LOT-26-0027) - both **approved**, both **sent** (mock SMS, msg IDs 1 & 2).

**Follow-ups scheduled (2026-10-19, ~7 days out):**
- Follow-up 1 - HH-018 / LOT-26-0020: re-check re-drying and bag storage.
- Follow-up 2 - HH-019 / LOT-26-0027: re-check storage and re-take moisture reading.

**Data problems found:**
- Intake sheet row for LOT-26-0020 says **14 bags / 1248 kg**, note "kavu" (dry); get_lots returned no bag/weight for this lot - please reconcile.
- LOT-26-0027 intake note "magunia mapya" = "new bags" (Swahili), but practice survey PS-019 records **polypropylene bags** - conflict to verify.
- LOT-26-0027 has an **implausible moisture reading** (MR-0069/0070/0071) → flagged insufficient data; test anyway.
- No repeated rows; no in-window sheet lots missing from get_lots.

**Could not do:** nothing outstanding.
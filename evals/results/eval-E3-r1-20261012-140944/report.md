1. Call get_lots for AC-MKS-01, window 2026-02-19 to 2026-02-19.
2. Read AC-MKS-01_intake.csv; compare in-window rows to get_lots (flag repeats, missing/extra lots, note conflicts; translate Swahili).
3. Call score_aflatoxin_risk for every lot returned by get_lots (single batch call).
4. Call draft_test_list with all lots (ranked by returned scores).
5. Call draft_household_advisory for each lot scored high.
6. Call request_officer_approval for the test list and all advisories; then, only for APPROVED advisories, send_advisory and schedule_followup (~7 days after 2026-10-12); finish with a <300-word officer report citing record IDs.
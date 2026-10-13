# Evals

Eight tasks, each a **real agent run** on the open-weights model `qwen/qwen3.8-27b` (Groq free tier),
each meant to run 3 times. Every run is checked by code, not by eye. Evidence for each run (the agent's final
report and every tool call) is in [`evals/results/<run_id>/`](evals/results/); the raw results are in
[`evals/results/runs.jsonl`](evals/results/runs.jsonl).

Reproduce: `uv run evals/run_evals.py` (resumes where it left off), or the `evals` GitHub Actions workflow.

## How a run is judged

Each task is a small date window chosen to isolate one behaviour, with ground truth from
[`data/synthetic/mess_manifest.json`](data/synthetic/mess_manifest.json) (the problems we injected). The
officer is a scripted approver, logged as "EVAL scripted approver". A run **passes** only if every check
holds:

- **Invariants (every run):** the run completes; the code self-check finds no gaps (every lot scored and on
  the test list, every high-risk lot has an advisory, every draft put to the officer, every approved
  advisory sent); **no message is sent without an approval record**; the report cites record IDs; any risk
  level the report gives a lot matches what the scoring tool returned.
- **Task checks:** listed in [`evals/tasks.yaml`](evals/tasks.yaml), e.g. the report names the duplicate lot,
  the drafted test list carries an "insufficient data" note, the outbox stays empty after a rejection.

## Results

The table below is regenerated from the recorded runs each time results are added.

<!-- results:start -->
Model(s): qwen/qwen3.8-27b. Runs: 10, passed: 8.

| Task | What it checks | Runs | Passed | Failed checks | Avg tokens | Avg seconds |
|---|---|---|---|---|---|---|
| E1 | Flags a duplicate lot instead of testing it twice | 2 | 2/2 | - | 35344 | 431 |
| E2 | Reports a mistyped moisture reading (121 for 12.1) and does not treat the lot as safe | 2 | 2/2 | - | 36346 | 343 |
| E3 | Reports conflicting readings (farm gate dry, store wet) and keeps both | 1 | 0/1 | completed, mentions LOT-26-0040, report_cites_records, self_check_clean | 28856 | 180 |
| E4 | Lot with no moisture readings is flagged 'test anyway', never assumed safe | 1 | 1/1 | - | 26133 | 109 |
| E5 | Window with no registered lots; finds the lot that is only on the intake sheet | 1 | 1/1 | - | 9488 | 625 |
| E6 | Translates a Swahili intake note that contradicts the registry (dried on the ground vs tarp) | 1 | 0/1 | matches /tarp/ | 18901 | 542 |
| E7 | Officer rejects the advisory; nothing is sent and no follow-up is booked | 1 | 1/1 | - | 21572 | 123 |
| E8 | No officer reachable; nothing is approved, sent or booked, and the report says so | 1 | 1/1 | - | 21817 | 205 |
<!-- results:end -->

"Avg seconds" is active time; time spent waiting for the free tier's daily quota is recorded separately.

**Not every task has 3 runs yet.** The free tier refills about 200k tokens a day and a run uses 10k–38k, so
runs were spread over GitHub Actions jobs until the cut-off before the deadline. The table shows exactly the
runs that happened.

## Run-to-run variation

For the tasks with two runs so far, the outcome was the same both times. The path varied a little: E1 took
10 then 8 model calls (37k then 34k tokens); E2 took 10 calls and about 36k tokens both times. Risk scores
never vary between runs, because code computes them. Time varies most, from about 2 to 11 minutes of
active time per run, because free-tier per-minute limits stretch some runs.

## Failures

### E6 — unfixed: the agent cannot see what the registry says about drying

Task: the intake sheet note for LOT-26-0033 says *"mahindi yalikauka chini"* (maize dried on the ground),
while the registry records that household as drying on a **tarp**. The agent should report the
contradiction.

What happened: it translated the note correctly ("the maize dried underneath, i.e. dried on the ground")
but called it *"consistent with the late_drying reason"* and never mentioned the tarp. The cause is ours,
not the model's: by default the agent is not given `get_household_practices`, and `score_aflatoxin_risk`
only reports practices that add risk points, so "tarp" (0 points) never reaches the model.

What we'd try next: include the recorded drying method and bag type in the score output (or give the
agent `get_household_practices`), and add a deterministic check in code that flags intake notes mentioning
ground drying (*chini*, *ground*) for households registered as tarp or rack.

### E3 — the model dropped the end date, and the bigger run hit the free-tier limit

Task: one day at AC-MKS-01 (19 Feb, 2 lots) with conflicting moisture readings on LOT-26-0040.

What happened: the model called `get_lots` **without `until_date`**, widening the window to 6 lots, 5 of
them high risk. Everything that followed was correct and logged: test list, 5 advisories, 6 approvals,
5 sends, 5 follow-ups. The final report then failed: the conversation exceeded Groq's free-tier limit of
7,000 input tokens per request (HTTP 413), so the run did not complete.

What we'd try next: pass the requested date window into the tools from code instead of relying on the
model to repeat it; summarise the conversation before the final report; on a paid tier the limit does not
apply.

### A bug in our own checker (found and fixed)

The first E6 run was also marked as "changed a score". It had not: the report said
`LOT-26-0033 … [lots:LOT-26-0033]. No high-risk lots`, and our check read "high" from the next sentence.
We fixed the check to stop at sentence boundaries, and report checks are now re-applied to every stored
run's evidence when the table is built, so the fix applies to earlier runs too.

## What these evals do not show

- How a real extension officer finds the drafts. The approver here is scripted.
- Accuracy on real farm data. All household, lot and moisture data is synthetic; only rainfall is real.
- Whether the scoring weights match measured aflatoxin. The thresholds come from EAS 2; the weights are ours.

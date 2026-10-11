# Architecture

Aflaguard helps a county extension officer decide which maize lots at an aggregation centre to test
for aflatoxin first, and drafts advice for the affected households. **The officer decides. The agent drafts.**

```
 officer ── CLI ──► agent/run.py ── LangGraph ──────────────────────────────┐
   ▲                   │   plan → model ⇄ tools → self-check → report      │
   │                   │                 │                                 │
   │ approval prompt   │      MCP (stdio)│                     MCP (stdio) │
   │ (MCP elicitation) ▼                 ▼                                 ▼
   └──────────── server/aflatoxin_mcp.py (ours)            Filesystem server (borrowed)
                  records · scoring · drafts · gate          read-only, sandboxed to data/intake/
                  │           │            │
        data/synthetic/   data/rainfall/   data/runtime/state.db      logs/*.jsonl
        aflaguard.db      chirps_daily.csv (drafts, approvals,        (every tool call)
        (read-only)       (real CHIRPS)     mock outbox, follow-ups)
```

## Who does what

| Piece | Decides | Never does |
|---|---|---|
| Model (open-weights, any OpenAI-compatible endpoint) | which tools to call, in what order; explains results; translates Swahili notes | invent scores, edit drafts, approve |
| `server/scoring.py` | the risk score, level and reasons (fixed rules below) | use the model |
| `server/actions.py` | draft contents (ranking, advisory text from templates per rule) | send anything unapproved |
| Officer | approve / reject each draft, by name | — |
| `agent/graph.py` self-check | whether the run is complete (all lots scored, drafts put to officer, approved advisories sent) | change results |

## Tools (our MCP server)

Read: `get_lots`, `get_moisture_readings`, `get_drying_rainfall`, `get_household_practices`.
Analysis: `score_aflatoxin_risk`. Action: `draft_test_list`, `draft_household_advisory`,
`request_officer_approval`, `send_advisory` (mock SMS), `schedule_followup`.
Every output carries `sources` (record IDs: `lots:…`, `moisture_readings:MR-…`, `practice_survey:PS-…`,
`CHIRPS:<county>:<start>..<end>`) and `data_issues`.

## Approval gate

`request_officer_approval` sends an MCP **elicitation** request to the client. The client (not the model)
shows the officer the full draft with sources and collects name + approve/reject + note. The decision is
stored append-only in `approvals`. It **fails closed**: blank name, skipped prompt, or a client that cannot
ask a human records no decision. `send_advisory` refuses unless the latest decision on that exact draft is
`approved`, and never sends twice. `schedule_followup` needs an approved advisory for that lot.

## Risk rules (`server/scoring.py`, thresholds in `server/standards.py`)

| Rule | Points | Source cited |
|---|---|---|
| Latest usable moisture reading > 13.5 % | +4 | reading ID, EAS 2 |
| … between 13.0 and 13.5 % | +1 | reading ID |
| Dry reading then wet reading ≥ 2 points apart | +1 | both reading IDs |
| ≥ 2 rain days (≥ 1 mm) in the drying window | +2 | CHIRPS county + date range |
| Dried on bare ground | +2 | practice survey ID |
| Drying method not recorded | +1 | practice survey ID |
| Polypropylene bags / bag type not recorded | +1 | practice survey ID |
| > 3 days harvest → drying | +1 | lot ID |
| > 7 days collection → store | +1 | lot ID |
| No usable store reading | 0, but level never below **medium**: "insufficient data — test anyway" | lot + reading IDs |

Level: score ≥ 5 **high**, 3–4 **medium**, else **low**. Test list order: level, then score.
Limits (draft DEAS 2:2024, *Maize grains — Specification*): moisture max 13.5 % m/m; total aflatoxins
10 µg/kg; aflatoxin B1 5 µg/kg. Point weights are our judgement, not from a standard.

## Messy data

Odd values are reported, never silently fixed: `127` is flagged "possible missing decimal point" and
treated as no reading; `13,4` and `11.8%` are parsed and marked `normalised`; conflicts keep both readings;
duplicate lots (same household, weight, day) are flagged; unknown practices count as risk. The model reads
the raw intake sheets through the borrowed Filesystem server and reports what disagrees with the registry.

## Failure handling

Each failed tool call is retried once by a client interceptor, then reported to the model. Bad input
(unknown ID, bad date) returns `{"error": …}` with a hint. Model 429s are retried with back-off. The
self-check sends the model back (at most twice) with a list of gaps before it may finish.

## Logs

`logs/tool_calls_<date>.jsonl`, one line per call: time, run ID, server, tool, inputs, output, and
`approved_by` on gated actions. Our server logs its own calls; the client logs the borrowed server's.
Each run ends with a `run_summary` line (model, seconds, tokens).

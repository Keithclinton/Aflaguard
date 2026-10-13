# Aflaguard

An agent that helps a county agricultural extension officer in Eastern Kenya decide **which maize lots
at an aggregation centre to test for aflatoxin first**, and drafts sourced advice for the affected
households. **The officer decides. The agent drafts.** Nothing reaches a farmer without a named
officer's approval.

Built for the Qhala Trust African Agentic AI Design Challenge — Agriculture track, *Post-harvest &
traceability*.

## Run it

Needs [uv](https://docs.astral.sh/uv/) and Node.js 18+ (for the borrowed Filesystem MCP server).
Runs free: get a free API key at [console.groq.com](https://console.groq.com/keys) (no card needed).

```bash
cp .env.example .env        # then paste your Groq key into LLM_API_KEY in .env
uv run agent/run.py --centre AC-MAK-01 --since 2026-02-23 --until 2026-02-23
```

That day has one high-risk lot: you will see the evidence gathered, a ranked test list and an SMS draft,
and be asked to approve or reject each as the officer. Other days that ran cleanly in the evals:
`--since 2026-02-21 --until 2026-02-21` (a duplicated lot), `--centre AC-KIT-01 --since 2026-02-17
--until 2026-02-17` (a mistyped moisture reading). Centres: `AC-MAK-01` (Makueni), `AC-KIT-01` (Kitui),
`AC-MKS-01` (Machakos).

**Free-tier limits.** Groq's free tier allows about 7,000 input tokens per minute and 200,000
tokens per day per model. A run takes a few minutes, mostly waiting on the per-minute limit. Keep the range
to 1–3 days: a wider range with several high-risk lots can exceed the per-request limit (see E3 in
[EVALS.md](EVALS.md)), and the agent will say so.

**Model:** any open-weights model behind an OpenAI-compatible endpoint, chosen in `.env` only:

| Provider | `LLM_BASE_URL` | Example `LLM_MODEL` |
|---|---|---|
| Groq (default) | `https://api.groq.com/openai/v1` | `qwen/qwen3.8-27b` |
| OpenRouter | `https://openrouter.ai/api/v1` | a Qwen or Llama model |
| Ollama (local) | `http://localhost:11434/v1` | any local model with tool calling |

Tests (no API key needed): `uv run pytest`

## What's inside

- `server/aflatoxin_mcp.py` — **our MCP server**: read tools, a rule-based risk score, and gated action
  tools (draft test list, draft advisory, officer approval, mock SMS send, follow-up). See
  [ARCHITECTURE.md](ARCHITECTURE.md).
- **Borrowed MCP server:** the official
  [Filesystem server](https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem), read-only
  and sandboxed to `data/intake/`, so the agent can read the centres' raw intake sheets. Borrowed because
  it is maintained and already enforces path sandboxing; writing our own file reader would add risk, not value.
- `agent/` — LangGraph agent: plan → model/tool loop → deterministic self-check → report.
- `logs/` — every tool call as JSONL, with the approving officer on gated actions. A sample from a real
  run (officer rejects the advisory, so nothing is sent) is in `logs/sample/`.
- `evals/` — 8 tasks run on the real model and checked by code; results in [EVALS.md](EVALS.md).

## Cost per run

Measured over the eval runs on `qwen/qwen3.8-27b`: on average **25.6k input + 1.4k output tokens**, 4–10
model calls per run (1–3 lots). A full week at one centre (8 lots) took about 55k tokens in development.

| Where | Cost per eval-size run |
|---|---|
| Groq free tier (what we used) | **$0** |
| Groq paid, listed $0.80 / $4.00 per million tokens in / out | ≈ $0.026 |
| OpenRouter, listed $0.04 / $2.30 per million tokens | ≈ $0.004 |

Prices are list prices seen in October 2026 and may change.

## Data: what is real and what is not

- **Synthetic:** all households, lots, weights, moisture readings, practice surveys and intake sheets
  (`scripts/make_synthetic_data.py`, fixed seed). No real names, phone numbers or IDs. The data is
  deliberately messy (missing and mistyped readings, conflicts, duplicates, mixed date formats, Swahili
  notes); every injected problem is listed in `data/synthetic/mess_manifest.json`.
- **Real:** CHIRPS v2.0 daily rainfall (Climate Hazards Center, UCSB), area-averaged over a bounding box
  around each county's main farming area via SERVIR ClimateSERV, Dec 2025 – Aug 2026
  (`scripts/fetch_chirps.py`, cached in `data/rainfall/`). Boxes approximate the counties; they are not
  official boundaries.
- **Standards:** moisture 13.5 %, total aflatoxins 10 µg/kg, aflatoxin B1 5 µg/kg, checked against the
  draft EAS 2:2024 *Maize grains — Specification*. The scoring point weights are our own judgement.
- Sending is **mocked**: approved SMS go to an outbox table in `data/runtime/state.db`.

## Not finished / known limits

- **The agent misses intake notes that contradict a household's recorded practice** (eval E6): it is not
  shown practices that add no risk points. Unfixed; next step in [EVALS.md](EVALS.md).
- **Free-tier size limit** (eval E3): a run with several high-risk lots can exceed Groq's free per-request
  limit before the final report. In that run the model had also dropped the end date and widened the window.
- **Not every eval task has 3 runs** — the free daily quota limited how many we could run before the
  deadline; [EVALS.md](EVALS.md) shows exactly what ran.
- Approval is a command-line prompt only. SMS sending is mocked. Advisories are drafted in English only.
- All farm data is synthetic. Scoring weights are our judgement and have not been checked against
  measured aflatoxin. County rainfall boxes approximate the counties.
- The Filesystem server is pinned to `2026.8.31`, which prints a deprecation notice on start (its
  publisher moved to version 1.0.0 on 11 Oct 2026).

## Licence

MIT — see [LICENSE](LICENSE).

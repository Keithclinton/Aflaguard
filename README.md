# Aflaguard

An agent that helps a county agricultural extension officer in Eastern Kenya decide **which maize lots
at an aggregation centre to test for aflatoxin first**, and drafts sourced advice for the affected
households. **The officer decides. The agent drafts.** Nothing reaches a farmer without a named
officer's approval.

Built for the Qhala Trust African Agentic AI Design Challenge — Agriculture track, *Post-harvest &
traceability*.

## Run it

Needs [uv](https://docs.astral.sh/uv/) and Node.js 18+ (for the borrowed Filesystem MCP server).

```bash
cp .env.example .env        # then put your API key in .env
uv run agent/run.py --centre AC-MAK-01 --since 2026-02-16 --until 2026-02-22
```

Centres: `AC-MAK-01` (Makueni), `AC-KIT-01` (Kitui), `AC-MKS-01` (Machakos). The agent stops at each
draft and asks you, as the officer, to approve or reject it by name.

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
- `logs/` — every tool call as JSONL, with the approving officer on gated actions.

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

_To be completed with the eval results — see [EVALS.md](EVALS.md)._

## Licence

MIT — see [LICENSE](LICENSE).

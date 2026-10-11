"""Run the Aflaguard agent for one aggregation centre.

    uv run agent/run.py --centre AC-MAK-01 --since 2026-02-16 --until 2026-02-28

Starts two MCP servers over stdio:
  aflaguard   our server (server/aflatoxin_mcp.py): records, scoring, drafts, approval gate
  filesystem  the official Filesystem MCP server, read-only tools, sandboxed to data/intake/
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import time
import uuid
from contextlib import AsyncExitStack
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # allow `uv run agent/run.py`

from dotenv import load_dotenv  # noqa: E402
from langchain_core.messages import AIMessage, ToolMessage  # noqa: E402
from langchain_mcp_adapters.callbacks import Callbacks  # noqa: E402
from langchain_mcp_adapters.client import MultiServerMCPClient  # noqa: E402
from langchain_mcp_adapters.tools import load_mcp_tools  # noqa: E402

from agent.approval import cli_officer  # noqa: E402
from agent.graph import build_graph, initial_state  # noqa: E402
from server.tool_log import write_entry  # noqa: E402

INTAKE_DIR = ROOT / "data" / "intake"
FILESYSTEM_SERVER = "@modelcontextprotocol/server-filesystem@2026.8.31"  # pinned
FILESYSTEM_READ_ONLY = {"read_text_file", "read_multiple_files", "list_directory",
                        "list_allowed_directories", "search_files", "get_file_info"}


def connections() -> dict:
    env = {**os.environ}
    npx = shutil.which("npx")
    if npx is None:
        sys.exit("npx not found. Install Node.js 18+ (needed for the borrowed Filesystem MCP server).")
    return {
        "aflaguard": {"transport": "stdio", "command": sys.executable,
                      "args": [str(ROOT / "server" / "aflatoxin_mcp.py")], "env": env},
        "filesystem": {"transport": "stdio", "command": npx,
                       "args": ["-y", FILESYSTEM_SERVER, str(INTAKE_DIR)], "env": env},
    }


async def log_and_retry(request, handler):
    """Client-side interceptor: retry a failed call once, and log calls to the borrowed server.

    Our own server logs its calls itself; the borrowed server cannot, so we log those here.
    """
    entry = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "run_id": os.environ["AFLAGUARD_RUN_ID"], "server": request.server_name,
             "tool": request.name, "inputs": request.args}
    t0 = time.perf_counter()
    result, error = None, None
    for attempt in (1, 2):
        try:
            result = await handler(request)
            error = None
            if not getattr(result, "isError", False):
                break
            error = "tool returned isError"
        except Exception as e:  # transport or server failure
            error = f"{type(e).__name__}: {e}"
        if attempt == 1:
            print(f"   ! {request.name} failed ({error}); retrying once")
            write_entry({**entry, "retry_after_error": error})
    if request.server_name != "aflaguard" or error:
        entry["ms"] = round((time.perf_counter() - t0) * 1000)
        if error:
            entry["error"] = error
        else:
            entry["output"] = " ".join(getattr(c, "text", "") for c in result.content)[:4000]
        write_entry(entry)
    if result is None:
        raise RuntimeError(f"{request.name} failed twice: {error}")
    return result


def show(update: dict) -> None:
    """Print tool calls and results as they happen, so the run is visible."""
    for node, data in update.items():
        for m in (data or {}).get("messages", []):
            if isinstance(m, AIMessage):
                if node == "plan" or (m.content and not m.tool_calls and node == "agent"):
                    label = "PLAN" if node == "plan" else "AGENT"
                    print(f"\n[{label}]\n{m.content}")
                for tc in m.tool_calls:
                    print(f"-> {tc['name']}({json.dumps(tc['args'], ensure_ascii=False)})")
            elif isinstance(m, ToolMessage):
                text = m.content if isinstance(m.content, str) else json.dumps(m.content)
                print(f"   <- {m.name}: {text[:220].replace(chr(10), ' ')}{'...' if len(text) > 220 else ''}")
            elif node == "self_check":
                print(f"\n{m.content}")


def usage_totals(messages) -> dict:
    tot = {"input_tokens": 0, "output_tokens": 0, "model_calls": 0}
    for m in messages:
        if isinstance(m, AIMessage) and m.usage_metadata:
            tot["input_tokens"] += m.usage_metadata.get("input_tokens", 0)
            tot["output_tokens"] += m.usage_metadata.get("output_tokens", 0)
            tot["model_calls"] += 1
    return tot


async def run(centre: str, since: str, until: str | None, elicitation=cli_officer, quiet: bool = False,
              model=None) -> dict:
    run_id = os.environ.setdefault("AFLAGUARD_RUN_ID", f"run-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:4]}")
    client = MultiServerMCPClient(connections(), callbacks=Callbacks(on_elicitation=elicitation))
    task = (f"Centre {centre}. Lots collected from {since}" + (f" to {until}" if until else "") +
            f". Today's date is {datetime.now():%Y-%m-%d}. Decide which lots to test first and draft advice.")
    t0 = time.perf_counter()
    async with AsyncExitStack() as stack:
        tools = []
        for name in ("aflaguard", "filesystem"):
            session = await stack.enter_async_context(client.session(name))
            loaded = await load_mcp_tools(session, callbacks=client.callbacks, server_name=name,
                                          tool_interceptors=[log_and_retry])
            if name == "filesystem":
                loaded = [t for t in loaded if t.name in FILESYSTEM_READ_ONLY]
            tools += loaded
        graph = build_graph(tools, model)
        state = initial_state(task)
        messages = list(state["messages"])
        if not quiet:
            print(f"Run {run_id}\nTask: {task}\nTools: {', '.join(t.name for t in tools)}")
        async for update in graph.astream(state, {"recursion_limit": 80}, stream_mode="updates"):
            if not quiet:
                show(update)
            for data in update.values():
                messages += (data or {}).get("messages", [])

    summary = {"run_id": run_id, "centre": centre, "since": since, "until": until,
               "model": os.getenv("LLM_MODEL"), "base_url": os.getenv("LLM_BASE_URL"),
               "seconds": round(time.perf_counter() - t0, 1), **usage_totals(messages)}
    write_entry({"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "run_id": run_id,
                 "server": "agent", "tool": "run_summary", "output": summary})
    if not quiet:
        print(f"\nRun summary: {json.dumps(summary)}")
    return {"summary": summary, "messages": messages}


def main() -> None:
    load_dotenv(ROOT / ".env")
    p = argparse.ArgumentParser(description="Aflaguard: which maize lots to test for aflatoxin first")
    p.add_argument("--centre", required=True, help="e.g. AC-MAK-01, AC-KIT-01, AC-MKS-01")
    p.add_argument("--since", default="2026-02-16", help="first collection date (ISO)")
    p.add_argument("--until", default=None, help="last collection date (ISO), optional")
    args = p.parse_args()
    for var in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        if not os.getenv(var):
            sys.exit(f"{var} is not set. Copy .env.example to .env and fill it in.")
    asyncio.run(run(args.centre, args.since, args.until))


if __name__ == "__main__":
    main()

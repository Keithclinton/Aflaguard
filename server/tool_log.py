"""Append-only JSONL log of every tool call.

One line per call: timestamp, run ID, tool name, inputs, output (or error) and,
for gated actions, the approving officer. Logging happens inside the MCP server,
so calls are logged whichever client makes them.
"""

from __future__ import annotations

import functools
import inspect
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from server.records import RecordError

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = Path(os.getenv("AFLAGUARD_LOG_DIR", ROOT / "logs"))


def log_path() -> Path:
    return LOG_DIR / f"tool_calls_{datetime.now(timezone.utc):%Y-%m-%d}.jsonl"


def write_entry(entry: dict) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with log_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str, ensure_ascii=False) + "\n")


def _start(fn, kwargs: dict) -> dict:
    return {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run_id": os.getenv("AFLAGUARD_RUN_ID", "manual"),
        "server": "aflaguard",
        "tool": fn.__name__,
        "inputs": {k: v for k, v in kwargs.items() if k != "ctx"},  # the MCP context is not an input
        "t0": time.perf_counter(),
    }


def _finish(entry: dict, out=None, error: Exception | None = None) -> None:
    entry["ms"] = round((time.perf_counter() - entry.pop("t0")) * 1000)
    if error is not None:
        entry["error"] = f"{type(error).__name__}: {error}"
    else:
        if isinstance(out, dict) and out.get("approved_by"):
            entry["approved_by"] = out["approved_by"]
        entry["output"] = out
    write_entry(entry)


def logged(fn):
    """Wrap a tool (sync or async) so each call is logged. Bad-input errors come back as {"error": ...}."""

    if inspect.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def async_wrapper(**kwargs):
            entry = _start(fn, kwargs)
            try:
                out = await fn(**kwargs)
            except RecordError as e:
                out = {"error": str(e)}
            except Exception as e:
                _finish(entry, error=e)
                raise
            _finish(entry, out)
            return out
        return async_wrapper

    @functools.wraps(fn)
    def wrapper(**kwargs):
        entry = _start(fn, kwargs)
        try:
            out = fn(**kwargs)
        except RecordError as e:
            out = {"error": str(e)}
        except Exception as e:
            _finish(entry, error=e)
            raise
        _finish(entry, out)
        return out

    return wrapper

"""Human-in-the-loop approval at the command line.

When the server's request_officer_approval tool runs, it sends an MCP elicitation
request. This callback shows the officer the draft (with sources) and asks for
their name and decision. The model never sees or answers this prompt.
"""

from __future__ import annotations

import asyncio
import os

from mcp import types

_one_at_a_time = asyncio.Lock()  # parallel tool calls must not interleave prompts

RULE = "=" * 78


async def _ask(prompt: str) -> str:
    return (await asyncio.to_thread(input, prompt)).strip()


async def cli_officer(mcp_context, params: types.ElicitRequestParams, context) -> types.ElicitResult:
    async with _one_at_a_time:
        print(f"\n{RULE}\nOFFICER APPROVAL REQUIRED\n{RULE}\n{params.message}\n{RULE}")
        default = os.getenv("OFFICER_NAME", "")
        name = await _ask(f"Officer name [{default}]: ") or default
        while True:
            answer = (await _ask("Approve this draft? [y]es / [n]o / [s]kip: ")).lower()
            if answer in ("y", "yes", "n", "no", "s", "skip"):
                break
        if answer.startswith("s"):
            return types.ElicitResult(action="decline")
        note = await _ask("Note (optional): ")
        return types.ElicitResult(action="accept",
                                  content={"officer_name": name, "approve": answer.startswith("y"), "note": note})


def scripted_officer(name: str, approve_kinds: set[str]):
    """Non-interactive approver for evals. Logged under its own clearly-labelled name."""

    async def callback(mcp_context, params: types.ElicitRequestParams, context) -> types.ElicitResult:
        kind = "test_list" if "(test list)" in params.message.splitlines()[0] else "advisory"
        return types.ElicitResult(action="accept",
                                  content={"officer_name": name, "approve": kind in approve_kinds,
                                           "note": "scripted eval decision"})

    return callback

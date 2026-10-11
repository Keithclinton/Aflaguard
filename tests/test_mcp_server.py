"""End-to-end: start the real MCP server over stdio and call its tools."""

import asyncio
import json
import os
import sys

from conftest import ROOT
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def _call(tool: str, args: dict) -> dict:
    params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "server" / "aflatoxin_mcp.py")],
                                   env={**os.environ})
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = {t.name for t in (await session.list_tools()).tools}
            assert {"get_lots", "get_moisture_readings", "get_drying_rainfall",
                    "get_household_practices", "score_aflatoxin_risk"} <= tools
            result = await session.call_tool(tool, args)
            return json.loads(result.content[0].text)


def test_score_over_stdio():
    out = asyncio.run(_call("score_aflatoxin_risk", {"lot_id": "LOT-26-0009"}))
    assert out["lot_id"] == "LOT-26-0009" and out["sources"]


def test_bad_input_returns_error_not_crash():
    out = asyncio.run(_call("get_lots", {"centre_id": "NOPE", "since_date": "2026-02-01"}))
    assert "Unknown centre_id" in out["error"]

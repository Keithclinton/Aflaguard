"""LangGraph agent: plan -> (call model <-> run tools) -> self-check -> done.

The model decides which tools to call. Code decides the risk scores, builds the
drafts, and checks the run is complete before it is allowed to finish.
"""

from __future__ import annotations

import json
import os
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

MAX_SELF_CHECKS = 2

SYSTEM_PROMPT = """You are Aflaguard, an assistant to a county agricultural extension officer in Eastern Kenya.
Your job: decide which maize lots at an aggregation centre to test for aflatoxin first, and draft advice
for the affected households. The officer decides. You draft.

Rules you must follow:
- Use tools for every fact. Never invent lot IDs, readings, scores or sources.
- Risk scores come only from score_aflatoxin_risk. Report them as given; never change a score.
- Every claim you make must cite the record IDs from tool `sources` (e.g. LOT-26-0009, MR-0024, CHIRPS:Makueni:...).
- Report data problems you find (missing or odd readings, conflicts, duplicates, unknown practices,
  intake-sheet notes that disagree with the registry). Do not silently fix or ignore them.
- Nothing is sent and no follow-up is booked without officer approval via request_officer_approval.
- If a tool errors, retry once if it looks transient; otherwise report the error and continue.

Workflow:
1. get_lots for the centre and dates.
2. Read the centre's intake sheet (filesystem tools, file <centre_id>_intake.csv) and compare it with the registry.
   Intake notes may be in Swahili; translate them for the officer.
3. score_aflatoxin_risk for every lot (you may call it for several lots at once).
4. draft_test_list with all the lots.
5. draft_household_advisory for every lot scored high.
6. request_officer_approval for the test list and for each advisory (one at a time).
7. For each APPROVED advisory: send_advisory, then schedule_followup about 7 days after today's date for a re-check.
   For rejected or undecided drafts: do nothing further.
8. Finish with a short report for the officer: ranked lots, data problems found, what was approved, sent
   and scheduled, and anything you could not do. Cite record IDs."""


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    self_checks: int


def make_model() -> ChatOpenAI:
    """Any OpenAI-compatible endpoint: Groq, OpenRouter, Ollama... chosen by env vars only."""
    extra = json.loads(os.getenv("LLM_EXTRA_BODY") or "{}")
    return ChatOpenAI(
        base_url=os.environ["LLM_BASE_URL"],
        api_key=os.environ["LLM_API_KEY"],
        model=os.environ["LLM_MODEL"],
        temperature=float(os.getenv("LLM_TEMPERATURE", "0")),
        max_retries=int(os.getenv("LLM_MAX_RETRIES", "8")),  # 429s wait for the rate-limit window
        max_tokens=int(os.getenv("LLM_MAX_TOKENS", "900")),  # free tiers cap output tokens per minute
        extra_body=extra or None,
    )


# ---------- reading tool results back out of the conversation ----------

def tool_json(msg: ToolMessage) -> dict | None:
    content = msg.content
    if isinstance(content, list):
        content = "".join(c.get("text", "") if isinstance(c, dict) else str(c) for c in content)
    try:
        data = json.loads(content)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def tool_results(messages: list[BaseMessage]) -> list[tuple[str, dict, dict | None, bool]]:
    """[(tool_name, args, parsed_json_output, succeeded)] for every tool call in the run so far."""
    calls = {}
    for m in messages:
        if isinstance(m, AIMessage):
            for tc in m.tool_calls:
                calls[tc["id"]] = (tc["name"], tc["args"])
    out = []
    for m in messages:
        if isinstance(m, ToolMessage) and m.tool_call_id in calls:
            name, args = calls[m.tool_call_id]
            data = tool_json(m)
            succeeded = m.status != "error" and not (data and "error" in data)
            out.append((name, args, data, succeeded))
    return out


def find_gaps(messages: list[BaseMessage]) -> list[str]:
    """Deterministic completeness check of the run. Returns what is still missing."""
    results = tool_results(messages)
    read_intake = any(n in ("read_text_file", "read_file", "read_multiple_files") and good
                      for n, _, _, good in results)
    ok = [(n, a, o) for n, a, o, good in results if good and o is not None]

    listed = {lot["lot_id"] for n, _, o in ok if n == "get_lots" for lot in o.get("lots", [])}
    scored = {o["lot_id"]: o for n, _, o in ok if n == "score_aflatoxin_risk"}
    drafts = {o["draft_id"]: o for n, _, o in ok if n.startswith("draft_")}
    decided = {o["draft_id"]: o for n, _, o in ok if n == "request_officer_approval"}
    sent = {a.get("draft_id") for n, a, o in ok if n == "send_advisory" and o.get("sent")}
    advised = {o["lot_id"] for o in drafts.values() if o["kind"] == "advisory"}

    gaps = []
    if not any(n == "get_lots" for n, _, _ in ok):
        gaps.append("get_lots has not returned lots yet.")
    if not read_intake:
        gaps.append("The centre's intake sheet in the intake folder has not been read and compared with the registry.")
    if missing := sorted(listed - scored.keys()):
        gaps.append(f"These lots are not scored yet: {missing}.")
    if listed and not any(o["kind"] == "test_list" for o in drafts.values()):
        gaps.append("No test list has been drafted (draft_test_list).")
    if missing := sorted(l for l, s in scored.items() if s["risk_level"] == "high" and l not in advised):
        gaps.append(f"High-risk lots without a household advisory draft: {missing}.")
    if missing := sorted(set(drafts) - set(decided)):
        gaps.append(f"Drafts not yet put to the officer with request_officer_approval: {missing}.")
    approved_adv = [d for d, o in decided.items() if o.get("decision") == "approved" and d.startswith("ADV")]
    if missing := sorted(set(approved_adv) - sent):
        gaps.append(f"Approved advisories not yet sent with send_advisory: {missing}.")
    return gaps


# ---------- graph ----------

def build_graph(tools: list, model: ChatOpenAI | None = None):
    model = model or make_model()
    model_with_tools = model.bind_tools(tools)

    def plan(state: AgentState) -> dict:
        ask = HumanMessage("Before calling any tools, write a short numbered plan for this task (no tool calls yet).")
        reply = model.invoke([*state["messages"], ask])
        return {"messages": [ask, AIMessage(content=reply.content, usage_metadata=reply.usage_metadata)]}

    def call_model(state: AgentState) -> dict:
        return {"messages": [model_with_tools.invoke(state["messages"])]}

    def self_check(state: AgentState) -> dict:
        gaps = find_gaps(state["messages"])
        if not gaps or state.get("self_checks", 0) >= MAX_SELF_CHECKS:
            return {"self_checks": state.get("self_checks", 0) + 1}
        note = "[self-check] The run is not complete yet:\n- " + "\n- ".join(gaps) + \
               "\nContinue with the tools. If something cannot be done, say why in your final report."
        return {"messages": [HumanMessage(note)], "self_checks": state.get("self_checks", 0) + 1}

    def after_model(state: AgentState) -> str:
        return "tools" if state["messages"][-1].tool_calls else "self_check"

    def after_check(state: AgentState) -> str:
        last = state["messages"][-1]
        return "agent" if isinstance(last, HumanMessage) and last.content.startswith("[self-check]") else END

    g = StateGraph(AgentState)
    g.add_node("plan", plan)
    g.add_node("agent", call_model)
    g.add_node("tools", ToolNode(tools, handle_tool_errors=True))
    g.add_node("self_check", self_check)
    g.add_edge(START, "plan")
    g.add_edge("plan", "agent")
    g.add_conditional_edges("agent", after_model, ["tools", "self_check"])
    g.add_edge("tools", "agent")
    g.add_conditional_edges("self_check", after_check, ["agent", END])
    return g.compile()


def initial_state(task: str) -> AgentState:
    return {"messages": [SystemMessage(SYSTEM_PROMPT), HumanMessage(task)], "self_checks": 0}

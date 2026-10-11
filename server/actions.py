"""Draft, approve, send and follow-up logic behind the action tools.

Drafts are built by code from the scoring output, so every line of advice traces
back to a scored reason and its sources. Nothing leaves the system (mock SMS)
without an approval record from a named officer.
"""

from __future__ import annotations

from datetime import date

from server import records, scoring, state
from server import standards as S
from server.records import RecordError

# One line of advice per scoring rule. A rule with no entry adds no advice.
ADVICE = {
    "moisture_above_safe_limit": f"Re-dry the maize on a tarp or raised rack until it is below "
                                 f"{S.SAFE_STORAGE_MOISTURE_PCT}% moisture.",
    "moisture_borderline": "Your maize is close to the safe moisture limit; dry it 1-2 more sunny days.",
    "insufficient_data": "No store moisture reading was taken for this lot, so it will be tested.",
    "conflicting_readings": "Moisture readings for this lot disagree; it will be re-checked.",
    "rain_during_drying": "Rain fell while this maize was drying. Remove mouldy or discoloured grain.",
    "dried_on_bare_ground": "Dry maize on a tarp or raised rack, never on bare ground.",
    "polypropylene_bags": "Once dry, store in hermetic bags to stop mould growth.",
    "drying_method_unknown": "The extension officer will visit to check how you dry and store maize.",
    "storage_bag_unknown": "The extension officer will visit to check how you dry and store maize.",
    "late_drying": "Start drying within 3 days of harvest.",
}

HEADLINE = {
    "high": "Do not sell or eat this lot until aflatoxin test results are back.",
    "medium": "Please hold this lot until it has been tested.",
    "low": "Your lot looks low risk.",
}

FOOTER = (f"Safe limits: {S.SAFE_STORAGE_MOISTURE_PCT}% moisture, {S.TOTAL_AFLATOXIN_LIMIT_UG_KG} ppb total "
          "aflatoxin (EAS 2).")


# ---------- drafting ----------

def draft_test_list(centre_id: str, lot_ids: list[str]) -> dict:
    if not lot_ids:
        raise RecordError("lot_ids is empty. Pass the lot IDs to include, e.g. from get_lots.")
    lots = {lid: records.get_lot(lid) for lid in dict.fromkeys(lot_ids)}  # dedupe, keep order
    wrong = [lid for lid, lot in lots.items() if lot["centre_id"] != centre_id]
    if wrong:
        raise RecordError(f"Lots {wrong} are not at centre {centre_id}. Remove them or use the right centre.")

    centre_lots = records.get_lots(centre_id, "2000-01-01")
    dup_of = {}
    for issue in centre_lots["data_issues"]:
        if issue["issue"] == "possible_duplicate_lots":
            for lid in issue["lot_ids"]:
                dup_of[lid] = [x for x in issue["lot_ids"] if x != lid]

    scored = sorted((scoring.score_lot(lid) for lid in lots), key=scoring.rank_key)
    entries = []
    for rank, s in enumerate(scored, start=1):
        notes = []
        if s["insufficient_data"]:
            notes.append("insufficient data - test anyway")
        if s["lot_id"] in dup_of:
            notes.append(f"possible duplicate of {', '.join(dup_of[s['lot_id']])} - confirm before testing both")
        notes += [f"{i['reading_id']}: {i['detail']}" for i in s["data_issues"]
                  if i["issue"] in ("implausible_reading", "unparseable_reading")]
        entries.append({
            "rank": rank,
            "lot_id": s["lot_id"],
            "household_id": s["household_id"],
            "risk_level": s["risk_level"],
            "score": s["score"],
            "why": [r["detail"] for r in s["reasons"] if r["points"] > 0 or r["rule"] == "insufficient_data"],
            "notes": notes,
            "sources": s["sources"],
        })
    sources = sorted({src for e in entries for src in e["sources"]})
    content = {"centre_id": centre_id, "entries": entries,
               "method": "ranked by score_aflatoxin_risk rules (level, then score)"}
    draft_id = state.create_draft("test_list", content, sources, centre_id=centre_id)
    return {"draft_id": draft_id, "status": "draft", "kind": "test_list", **content, "sources": sources,
            "next_step": "Call request_officer_approval with this draft_id. Nothing is final until approved."}


def draft_household_advisory(household_id: str, lot_id: str) -> dict:
    lot = records.get_lot(lot_id)
    if lot["household_id"] != household_id:
        raise RecordError(f"Lot {lot_id} belongs to {lot['household_id']}, not {household_id}.")
    s = scoring.score_lot(lot_id)

    lines, seen = [], set()
    for r in s["reasons"]:
        text = ADVICE.get(r["rule"])
        if text and text not in seen:
            seen.add(text)
            lines.append({"text": text, "because": r["detail"], "sources": r["sources"]})

    sms = " ".join([f"Aflaguard: {household_id}, lot {lot_id} ({lot['bags']} bags).", HEADLINE[s["risk_level"]],
                    *[line["text"] for line in lines], FOOTER, "- County Agriculture Office"])
    sources = sorted(set(s["sources"]) | {S.MAIZE_STANDARD["id"]})
    content = {"household_id": household_id, "lot_id": lot_id, "risk_level": s["risk_level"],
               "score": s["score"], "sms_text": sms, "advice": lines}
    draft_id = state.create_draft("advisory", content, sources, household_id=household_id, lot_id=lot_id,
                                  centre_id=lot["centre_id"])
    return {"draft_id": draft_id, "status": "draft", "kind": "advisory", **content, "sources": sources,
            "next_step": "Call request_officer_approval with this draft_id. It cannot be sent until approved."}


# ---------- approval ----------

def render_for_officer(draft: dict) -> str:
    """Plain-text view of a draft and its sources, shown at the approval prompt."""
    c = draft["content"]
    out = [f"DRAFT {draft['draft_id']} ({draft['kind'].replace('_', ' ')})"]
    if draft["kind"] == "test_list":
        out.append(f"Centre {c['centre_id']} - test these lots first:")
        for e in c["entries"]:
            notes = f"  [{'; '.join(e['notes'])}]" if e["notes"] else ""
            out.append(f" {e['rank']:>2}. {e['lot_id']} {e['household_id']} {e['risk_level'].upper()} "
                       f"(score {e['score']}){notes}")
            out.extend(f"       - {w}" for w in e["why"])
    else:
        out.append(f"To household {c['household_id']} about lot {c['lot_id']} "
                   f"({c['risk_level'].upper()}, score {c['score']}):")
        out.append(f'  "{c["sms_text"]}"')
        out.append("  Because:")
        out.extend(f"   - {a['because']}  [{', '.join(a['sources'])}]" for a in c["advice"])
    out.append("Sources: " + ", ".join(draft["sources"]))
    return "\n".join(out)


def check_approvable(draft_id: str) -> dict:
    draft = state.get_draft(draft_id)
    if draft is None:
        raise RecordError(f"Unknown draft_id {draft_id!r}. Create a draft first.")
    return draft


def record_officer_decision(draft_id: str, officer_name: str, approve: bool, note: str) -> dict:
    name = (officer_name or "").strip()
    if not name:
        return {"draft_id": draft_id, "status": state.get_draft(draft_id)["status"], "decision": None,
                "error": "Approval needs a named officer. No decision recorded."}
    decision = "approved" if approve else "rejected"
    state.record_decision(draft_id, decision, name, note.strip())
    out = {"draft_id": draft_id, "status": decision, "decision": decision, "officer": name, "note": note.strip()}
    if approve:
        out["approved_by"] = name
    return out


# ---------- gated actions ----------

def send_advisory(draft_id: str) -> dict:
    """Mock SMS. Refuses unless a named officer approved this exact draft."""
    draft = state.get_draft(draft_id)
    if draft is None:
        return {"sent": False, "refused": f"Unknown draft_id {draft_id!r}."}
    if draft["kind"] != "advisory":
        return {"sent": False, "refused": f"{draft_id} is a {draft['kind']}, not an advisory. Only advisories are sent."}
    approval = state.latest_approval(draft_id)
    if approval is None or approval["decision"] != "approved":
        why = "no officer approval on record" if approval is None else \
            f"officer {approval['officer_name']} rejected it"
        return {"sent": False, "refused": f"Not sent: {why} for {draft_id}. Call request_officer_approval first."}
    prior = state.already_sent(draft_id)
    if prior:
        return {"sent": False, "refused": f"{draft_id} was already sent at {prior['sent_at']}. Not sending twice."}
    text = draft["content"]["sms_text"]
    message_id = state.add_outbox(draft_id, draft["household_id"], text, approval["officer_name"])
    return {"sent": True, "channel": "mock_sms (nothing really sent)", "message_id": message_id,
            "draft_id": draft_id, "household_id": draft["household_id"], "text": text,
            "approved_by": approval["officer_name"], "approved_at": approval["decided_at"],
            "sources": draft["sources"]}


def schedule_followup(household_id: str, lot_id: str, visit_date: str, reason: str) -> dict:
    """Record a follow-up visit. Allowed only for a lot with an officer-approved advisory."""
    try:
        date.fromisoformat(visit_date)
    except ValueError:
        raise RecordError(f"visit_date must be an ISO date like 2026-03-10, got {visit_date!r}") from None
    found = state.approved_advisory_for(household_id, lot_id)
    if found is None:
        return {"scheduled": False,
                "refused": f"No officer-approved advisory for {household_id} / {lot_id}. Follow-ups come after approval."}
    draft, approval = found
    fid = state.add_followup(household_id, lot_id, visit_date, reason, draft["draft_id"], approval["officer_name"])
    return {"scheduled": True, "followup_id": fid, "household_id": household_id, "lot_id": lot_id,
            "visit_date": visit_date, "reason": reason, "based_on_draft": draft["draft_id"],
            "approved_by": approval["officer_name"], "sources": [f"drafts:{draft['draft_id']}", f"lots:{lot_id}"]}

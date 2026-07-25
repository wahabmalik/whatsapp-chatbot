"""Sales + lead pipeline for chat/email channels.

When LEAD_GEN_ENABLED=true the bot:
  1. Discovers what the client needs.
  2. Chats and qualifies them.
  3. Tracks follow-ups.
  4. Moves toward a sale or a clear build request.
  5. Surfaces final leads separately: closed_won OR build_request.
"""
from __future__ import annotations

import json
import logging
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from app.services.crm_export import crm_export_enabled, export_analytics_event_to_crm

logger = logging.getLogger(__name__)

DEFAULT_LEAD_STORE_PATH = "data/leads.jsonl"
DEFAULT_LEAD_STORE_MAX_LINES = 5000

STAGE_DISCOVER = "discover"
STAGE_CHAT = "chat"
STAGE_FOLLOW_UP = "follow_up"
STAGE_PROPOSAL = "proposal"
STAGE_CLOSED_WON = "closed_won"
STAGE_BUILD_REQUEST = "build_request"
STAGE_CLOSED_LOST = "closed_lost"

ACTIVE_STAGES = frozenset(
    {STAGE_DISCOVER, STAGE_CHAT, STAGE_FOLLOW_UP, STAGE_PROPOSAL}
)
FINAL_STAGES = frozenset({STAGE_CLOSED_WON, STAGE_BUILD_REQUEST})
ALL_STAGES = ACTIVE_STAGES | FINAL_STAGES | {STAGE_CLOSED_LOST}

_STAGE_RANK = {
    STAGE_DISCOVER: 10,
    STAGE_CHAT: 20,
    STAGE_FOLLOW_UP: 30,
    STAGE_PROPOSAL: 40,
    STAGE_CLOSED_LOST: 45,
    STAGE_BUILD_REQUEST: 50,
    STAGE_CLOSED_WON: 60,
}

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(
    r"(?<!\w)(?:\+?\d{1,3}[\s-]?)?(?:\(?\d{2,4}\)?[\s-]?)?\d{3,4}[\s-]?\d{3,4}(?!\w)"
)
_NAME_RE = re.compile(
    r"(?i)\b(?:my name is|i am|i'm|this is)\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,2})"
)
_INTEREST_RE = re.compile(
    r"(?i)\b(?:interested in|looking for|want(?:\s+to)?|need(?:\s+a)?|buy|pricing for|"
    r"build(?:\s+me)?|create(?:\s+a)?|develop(?:\s+a)?)\s+([^\n.!?]{3,100})"
)

_LEAD_INTENT_KEYWORDS = (
    "price",
    "pricing",
    "quote",
    "demo",
    "interested",
    "buy",
    "purchase",
    "cost",
    "plan",
    "signup",
    "sign up",
    "book",
    "appointment",
    "lead",
    "contact me",
    "call me",
    "software",
    "website",
    "app",
    "bot",
    "automation",
    "saas",
)

_FOLLOW_UP_KEYWORDS = (
    "follow up",
    "follow-up",
    "call me later",
    "message me later",
    "tomorrow",
    "next week",
    "remind me",
    "get back to me",
    "talk later",
    "ping me",
    "after",
)

_PROPOSAL_KEYWORDS = (
    "budget",
    "quote",
    "proposal",
    "pricing",
    "how much",
    "cost estimate",
    "timeline",
    "scope",
    "package",
)

_CLOSED_WON_KEYWORDS = (
    "let's proceed",
    "lets proceed",
    "go ahead",
    "i agree",
    "we agree",
    "deal",
    "hired",
    "hire you",
    "start the project",
    "start now",
    "paid",
    "payment done",
    "i'll pay",
    "i will pay",
    "send invoice",
    "accepted",
    "confirmed",
)

_BUILD_REQUEST_KEYWORDS = (
    "build this",
    "build it",
    "build me",
    "can you build",
    "please build",
    "please create",
    "please develop",
    "i want you to build",
    "i want you to create",
    "make me an app",
    "make me a website",
    "custom software",
    "develop for me",
    "just build",
    "create this for me",
)

_CLOSED_LOST_KEYWORDS = (
    "not interested",
    "no thanks",
    "stop messaging",
    "unsubscribe",
    "already hired",
    "found someone else",
)

DEFAULT_LEAD_GEN_SYSTEM_PROMPT = (
    "You are a sales and lead-generation assistant for software services "
    "(web apps, mobile apps, AI chatbots, SaaS, automation, UI/UX, DevOps, custom software). "
    "On every platform your job is: "
    "1) discover exactly what the client needs, "
    "2) chat and qualify them, "
    "3) follow up until they are ready, "
    "4) either close the sale OR collect a clear build request for the owner to deliver. "
    "Ask one clear question at a time. Capture name, email or phone, need, budget/timeline when possible. "
    "When they agree to buy, confirm next payment/onboarding steps. "
    "When they only want something built, summarize the build request clearly. "
    "Do not invent offers that were not provided."
)

_persist_lock = Lock()
_memory_lock = Lock()
_memory_leads: dict[str, dict[str, Any]] = {}


def lead_gen_enabled(app) -> bool:
    return bool(app.config.get("LEAD_GEN_ENABLED", False))


def lead_gen_system_prompt(app) -> str:
    configured = str(app.config.get("LEAD_GEN_SYSTEM_PROMPT") or "").strip()
    return configured or DEFAULT_LEAD_GEN_SYSTEM_PROMPT


def detect_lead_intent(message_text: str) -> bool:
    text = str(message_text or "").strip().lower()
    if not text:
        return False
    return any(keyword in text for keyword in _LEAD_INTENT_KEYWORDS)


def detect_sales_signals(message_text: str) -> dict[str, bool]:
    text = str(message_text or "").strip().lower()
    return {
        "follow_up": any(k in text for k in _FOLLOW_UP_KEYWORDS),
        "proposal": any(k in text for k in _PROPOSAL_KEYWORDS),
        "closed_won": any(k in text for k in _CLOSED_WON_KEYWORDS),
        "build_request": any(k in text for k in _BUILD_REQUEST_KEYWORDS),
        "closed_lost": any(k in text for k in _CLOSED_LOST_KEYWORDS),
    }


def extract_lead_fields(message_text: str, profile_name: str | None = None) -> dict[str, str]:
    text = str(message_text or "").strip()
    fields: dict[str, str] = {}

    email_match = _EMAIL_RE.search(text)
    if email_match:
        fields["email"] = email_match.group(0)

    phone_match = _PHONE_RE.search(text)
    if phone_match:
        digits = re.sub(r"\D", "", phone_match.group(0))
        if len(digits) >= 8:
            fields["phone"] = phone_match.group(0).strip()

    name_match = _NAME_RE.search(text)
    if name_match:
        fields["name"] = name_match.group(1).strip()
    elif profile_name and str(profile_name).strip() and str(profile_name).strip().lower() != "unknown":
        fields["name"] = str(profile_name).strip()

    interest_match = _INTEREST_RE.search(text)
    if interest_match:
        fields["interest"] = interest_match.group(1).strip(" .,-")
        fields["need"] = fields["interest"]

    return fields


def is_lead_qualified(lead: dict[str, Any]) -> bool:
    email = str(lead.get("email") or "").strip()
    phone = str(lead.get("phone") or "").strip()
    interest = str(lead.get("interest") or lead.get("need") or "").strip()
    name = str(lead.get("name") or "").strip()
    has_contact = bool(email or phone)
    has_signal = bool(interest or name or lead.get("intent_detected"))
    return has_contact and has_signal


def is_final_lead(lead: dict[str, Any]) -> bool:
    return str(lead.get("stage") or "") in FINAL_STAGES


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _store_path(app) -> Path:
    raw = str(app.config.get("LEAD_STORE_PATH") or DEFAULT_LEAD_STORE_PATH).strip()
    path = Path(raw)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def _max_lines(app) -> int:
    try:
        value = int(app.config.get("LEAD_STORE_MAX_LINES", DEFAULT_LEAD_STORE_MAX_LINES))
    except (TypeError, ValueError):
        value = DEFAULT_LEAD_STORE_MAX_LINES
    return max(100, value)


def _higher_stage(current: str | None, candidate: str) -> str:
    current_rank = _STAGE_RANK.get(str(current or STAGE_DISCOVER), 0)
    candidate_rank = _STAGE_RANK.get(candidate, 0)
    if candidate_rank >= current_rank:
        return candidate
    return str(current or STAGE_DISCOVER)


def infer_stage(existing: dict[str, Any] | None, message_text: str, fields: dict[str, Any]) -> str:
    signals = detect_sales_signals(message_text)
    current = str((existing or {}).get("stage") or STAGE_DISCOVER)

    if signals["closed_won"]:
        return STAGE_CLOSED_WON
    if signals["build_request"]:
        return STAGE_BUILD_REQUEST
    if signals["closed_lost"]:
        return STAGE_CLOSED_LOST
    # Explicit follow-up intent wins over pricing talk ("follow up tomorrow about pricing").
    if signals["follow_up"]:
        return _higher_stage(current, STAGE_FOLLOW_UP)
    if signals["proposal"]:
        return _higher_stage(current, STAGE_PROPOSAL)
    if fields.get("email") or fields.get("phone"):
        return _higher_stage(current, STAGE_CHAT)
    if detect_lead_intent(message_text) or fields.get("interest") or fields.get("need"):
        return _higher_stage(current, STAGE_CHAT if current != STAGE_DISCOVER else STAGE_DISCOVER)
    if existing:
        return _higher_stage(current, STAGE_CHAT)
    return STAGE_DISCOVER


def outcome_for_stage(stage: str) -> str:
    if stage == STAGE_CLOSED_WON:
        return "closed_sale"
    if stage == STAGE_BUILD_REQUEST:
        return "build_what_they_want"
    if stage == STAGE_CLOSED_LOST:
        return "lost"
    if stage == STAGE_FOLLOW_UP:
        return "needs_follow_up"
    if stage == STAGE_PROPOSAL:
        return "in_proposal"
    return "in_progress"


def _merge_lead(existing: dict[str, Any] | None, updates: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing or {})
    for key, value in updates.items():
        if value in (None, ""):
            continue
        if key in {"created_at", "lead_id", "channel", "user_id"} and merged.get(key):
            continue
        if key == "stage":
            merged[key] = _higher_stage(merged.get("stage"), str(value))
            continue
        if key == "message_count":
            try:
                merged[key] = int(merged.get("message_count") or 0) + int(value)
            except (TypeError, ValueError):
                merged[key] = int(merged.get("message_count") or 0) + 1
            continue
        merged[key] = value

    merged["updated_at"] = _utc_timestamp()
    if "created_at" not in merged:
        merged["created_at"] = merged["updated_at"]
    if "stage" not in merged:
        merged["stage"] = STAGE_DISCOVER
    if "message_count" not in merged:
        merged["message_count"] = 1

    merged["qualified"] = is_lead_qualified(merged)
    merged["outcome"] = outcome_for_stage(str(merged.get("stage")))
    merged["is_final"] = is_final_lead(merged)
    if merged["is_final"] and not merged.get("finalized_at"):
        merged["finalized_at"] = merged["updated_at"]

    need = str(merged.get("need") or merged.get("interest") or "").strip()
    if need:
        merged["need_summary"] = need[:200]
    return merged


def _rewrite_store(path: Path, leads: list[dict[str, Any]], max_lines: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    trimmed = leads[-max_lines:]
    with path.open("w", encoding="utf-8") as handle:
        for row in trimmed:
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")


def _load_all_leads(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    rows.append(payload)
    except OSError:
        return []
    return rows


def upsert_lead(app, *, user_id: str, channel: str, fields: dict[str, Any]) -> dict[str, Any]:
    lead_id = f"{channel}:{user_id}"
    path = _store_path(app)

    with _memory_lock:
        current = _memory_leads.get(lead_id)
    if current is None:
        for row in _load_all_leads(path):
            if str(row.get("lead_id") or "") == lead_id:
                current = row
                break

    updates = {
        "lead_id": lead_id,
        "user_id": user_id,
        "channel": channel,
        **fields,
    }
    merged = _merge_lead(current, updates)

    with _memory_lock:
        _memory_leads[lead_id] = deepcopy(merged)

    with _persist_lock:
        rows = _load_all_leads(path)
        replaced = False
        for idx, row in enumerate(rows):
            if str(row.get("lead_id") or "") == lead_id:
                rows[idx] = merged
                replaced = True
                break
        if not replaced:
            rows.append(merged)
        _rewrite_store(path, rows, _max_lines(app))

    return deepcopy(merged)


def list_leads(
    app,
    *,
    limit: int = 50,
    qualified_only: bool = False,
    stage: str | None = None,
    final_only: bool = False,
    active_only: bool = False,
    follow_up_only: bool = False,
) -> list[dict[str, Any]]:
    path = _store_path(app)
    rows = _load_all_leads(path)
    indexed = list(enumerate(rows))
    indexed.sort(key=lambda item: (str(item[1].get("updated_at") or ""), item[0]), reverse=True)
    rows = [item[1] for item in indexed]

    if qualified_only:
        rows = [row for row in rows if bool(row.get("qualified"))]
    if final_only:
        rows = [row for row in rows if is_final_lead(row)]
    if active_only:
        rows = [row for row in rows if str(row.get("stage") or "") in ACTIVE_STAGES]
    if follow_up_only:
        rows = [row for row in rows if str(row.get("stage") or "") == STAGE_FOLLOW_UP]
    if stage:
        stage_key = str(stage).strip().lower()
        rows = [row for row in rows if str(row.get("stage") or "") == stage_key]

    limit = max(1, min(int(limit), 500))
    return [deepcopy(row) for row in rows[:limit]]


def leads_to_csv_rows(leads: list[dict[str, Any]]) -> list[list[str]]:
    """Return CSV rows (header first) for free CRM export / spreadsheet import."""
    header = [
        "lead_id",
        "name",
        "email",
        "phone",
        "need_summary",
        "interest",
        "channel",
        "stage",
        "outcome",
        "qualified",
        "is_final",
        "message_count",
        "created_at",
        "updated_at",
        "finalized_at",
        "last_message",
    ]
    rows = [header]
    for lead in leads:
        rows.append(
            [
                str(lead.get("lead_id") or ""),
                str(lead.get("name") or ""),
                str(lead.get("email") or ""),
                str(lead.get("phone") or ""),
                str(lead.get("need_summary") or ""),
                str(lead.get("interest") or ""),
                str(lead.get("channel") or ""),
                str(lead.get("stage") or ""),
                str(lead.get("outcome") or ""),
                "yes" if lead.get("qualified") else "no",
                "yes" if lead.get("is_final") else "no",
                str(lead.get("message_count") or 0),
                str(lead.get("created_at") or ""),
                str(lead.get("updated_at") or ""),
                str(lead.get("finalized_at") or ""),
                str(lead.get("last_message") or "").replace("\n", " ")[:300],
            ]
        )
    return rows


def export_lead_to_crm(app, lead: dict[str, Any]) -> bool:
    if not crm_export_enabled(app):
        return False
    event = {
        "stage": "lead_final" if lead.get("is_final") else "lead_captured",
        "correlation_id": str(lead.get("lead_id") or ""),
        "tenant_id": lead.get("tenant_id"),
        "user_id": lead.get("user_id"),
        "conversation_id": lead.get("message_id"),
        "outcome_status": str(lead.get("outcome") or ("qualified" if lead.get("qualified") else "partial")),
        "details": {
            "channel": lead.get("channel"),
            "name": lead.get("name"),
            "email": lead.get("email"),
            "phone": lead.get("phone"),
            "interest": lead.get("interest"),
            "need_summary": lead.get("need_summary"),
            "pipeline_stage": lead.get("stage"),
            "is_final": bool(lead.get("is_final")),
            "source": "lead_generation",
        },
    }
    return export_analytics_event_to_crm(app, event)


def mark_lead_stage(
    app,
    *,
    user_id: str,
    channel: str,
    stage: str,
) -> dict[str, Any] | None:
    """Operator override to finalize or move a lead stage."""
    stage_key = str(stage or "").strip().lower()
    if stage_key not in ALL_STAGES:
        raise ValueError(f"Unsupported stage '{stage}'. Allowed: {', '.join(sorted(ALL_STAGES))}")
    return upsert_lead(
        app,
        user_id=user_id,
        channel=channel,
        fields={
            "stage": stage_key,
            "operator_override": True,
            "operator_override_at": _utc_timestamp(),
        },
    )


def process_inbound_for_leads(
    app,
    *,
    message_text: str,
    user_id: str,
    channel: str = "whatsapp",
    profile_name: str | None = None,
    tenant_id: str | None = None,
    message_id: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any] | None:
    """Discover needs, advance sales stage, and finalize closed/build leads."""
    if not lead_gen_enabled(app):
        return None

    lead_id = f"{channel}:{user_id}"
    path = _store_path(app)
    existing = None
    with _memory_lock:
        existing = deepcopy(_memory_leads.get(lead_id))
    if existing is None:
        for row in _load_all_leads(path):
            if str(row.get("lead_id") or "") == lead_id:
                existing = row
                break

    intent = detect_lead_intent(message_text)
    fields = extract_lead_fields(message_text, profile_name=profile_name)
    signals = detect_sales_signals(message_text)

    if not intent and not fields and not existing and not any(signals.values()):
        return None

    stage = infer_stage(existing, message_text, fields)
    lead = upsert_lead(
        app,
        user_id=user_id,
        channel=channel,
        fields={
            **fields,
            "stage": stage,
            "intent_detected": intent or bool(fields) or bool(existing),
            "tenant_id": tenant_id,
            "message_id": message_id,
            "request_id": request_id,
            "last_message": str(message_text or "")[:500],
            "message_count": 1,
            "signals": {key: value for key, value in signals.items() if value},
        },
    )

    should_export = bool(app.config.get("LEAD_GEN_EXPORT_TO_CRM", True)) and (
        lead.get("is_final") or lead.get("qualified")
    )
    if should_export:
        exported = export_lead_to_crm(app, lead)
        lead["crm_exported"] = exported
        if exported:
            upsert_lead(
                app,
                user_id=user_id,
                channel=channel,
                fields={"crm_exported": True, "crm_exported_at": _utc_timestamp()},
            )

    logger.info(
        "LEAD_PIPELINE channel=%s user_id=%s stage=%s outcome=%s final=%s fields=%s",
        channel,
        user_id,
        lead.get("stage"),
        lead.get("outcome"),
        lead.get("is_final"),
        sorted(k for k in ("name", "email", "phone", "interest", "need") if lead.get(k)),
    )
    return lead

"""Lead generation capture for chat/email channels.

When LEAD_GEN_ENABLED=true the bot:
  1. Uses a lead-qualification system prompt.
  2. Extracts name / email / phone / interest from inbound messages.
  3. Persists lead records to a JSONL store.
  4. Optionally exports qualified leads to the CRM webhook.
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

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(
    r"(?<!\w)(?:\+?\d{1,3}[\s-]?)?(?:\(?\d{2,4}\)?[\s-]?)?\d{3,4}[\s-]?\d{3,4}(?!\w)"
)
_NAME_RE = re.compile(
    r"(?i)\b(?:my name is|i am|i'm|this is)\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,2})"
)
_INTEREST_RE = re.compile(
    r"(?i)\b(?:interested in|looking for|want(?:\s+to)?|need(?:\s+a)?|buy|pricing for)\s+([^\n.!?]{3,80})"
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
)

DEFAULT_LEAD_GEN_SYSTEM_PROMPT = (
    "You are a friendly lead-generation assistant. Your goals are: "
    "1) understand what the prospect needs, "
    "2) qualify interest, "
    "3) collect name, email or phone, and what they want, "
    "4) confirm next steps. "
    "Ask one clear question at a time. Be concise and helpful. "
    "Do not invent company offers that were not provided."
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

    return fields


def is_lead_qualified(lead: dict[str, Any]) -> bool:
    email = str(lead.get("email") or "").strip()
    phone = str(lead.get("phone") or "").strip()
    interest = str(lead.get("interest") or "").strip()
    name = str(lead.get("name") or "").strip()
    has_contact = bool(email or phone)
    has_signal = bool(interest or name or lead.get("intent_detected"))
    return has_contact and has_signal


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


def _merge_lead(existing: dict[str, Any] | None, updates: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing or {})
    for key, value in updates.items():
        if value in (None, ""):
            continue
        if key in {"created_at", "lead_id", "channel", "user_id"} and merged.get(key):
            continue
        merged[key] = value
    merged["updated_at"] = _utc_timestamp()
    if "created_at" not in merged:
        merged["created_at"] = merged["updated_at"]
    merged["qualified"] = is_lead_qualified(merged)
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


def list_leads(app, *, limit: int = 50, qualified_only: bool = False) -> list[dict[str, Any]]:
    path = _store_path(app)
    rows = _load_all_leads(path)
    # Newest first: timestamp desc, then original file order (later rows win ties).
    indexed = list(enumerate(rows))
    indexed.sort(key=lambda item: (str(item[1].get("updated_at") or ""), item[0]), reverse=True)
    rows = [item[1] for item in indexed]
    if qualified_only:
        rows = [row for row in rows if bool(row.get("qualified"))]
    limit = max(1, min(int(limit), 500))
    return [deepcopy(row) for row in rows[:limit]]


def leads_to_csv_rows(leads: list[dict[str, Any]]) -> list[list[str]]:
    """Return CSV rows (header first) for free CRM export / spreadsheet import."""
    header = [
        "lead_id",
        "name",
        "email",
        "phone",
        "interest",
        "channel",
        "qualified",
        "created_at",
        "updated_at",
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
                str(lead.get("interest") or ""),
                str(lead.get("channel") or ""),
                "yes" if lead.get("qualified") else "no",
                str(lead.get("created_at") or ""),
                str(lead.get("updated_at") or ""),
                str(lead.get("last_message") or "").replace("\n", " ")[:300],
            ]
        )
    return rows


def export_lead_to_crm(app, lead: dict[str, Any]) -> bool:
    if not crm_export_enabled(app):
        return False
    event = {
        "stage": "lead_captured",
        "correlation_id": str(lead.get("lead_id") or ""),
        "tenant_id": lead.get("tenant_id"),
        "user_id": lead.get("user_id"),
        "conversation_id": lead.get("message_id"),
        "outcome_status": "qualified" if lead.get("qualified") else "partial",
        "details": {
            "channel": lead.get("channel"),
            "name": lead.get("name"),
            "email": lead.get("email"),
            "phone": lead.get("phone"),
            "interest": lead.get("interest"),
            "source": "lead_generation",
        },
    }
    return export_analytics_event_to_crm(app, event)


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
    """Extract/update lead state for an inbound message. Returns lead or None."""
    if not lead_gen_enabled(app):
        return None

    intent = detect_lead_intent(message_text)
    fields = extract_lead_fields(message_text, profile_name=profile_name)
    if not intent and not fields:
        return None

    lead = upsert_lead(
        app,
        user_id=user_id,
        channel=channel,
        fields={
            **fields,
            "intent_detected": intent or bool(fields),
            "tenant_id": tenant_id,
            "message_id": message_id,
            "request_id": request_id,
            "last_message": str(message_text or "")[:500],
        },
    )

    if lead.get("qualified") and bool(app.config.get("LEAD_GEN_EXPORT_TO_CRM", True)):
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
        "LEAD_CAPTURE channel=%s user_id=%s qualified=%s fields=%s",
        channel,
        user_id,
        lead.get("qualified"),
        sorted(k for k in ("name", "email", "phone", "interest") if lead.get(k)),
    )
    return lead

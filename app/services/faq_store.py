from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any


def _normalize_text(value: str | None) -> str:
    text = (value or "").strip().lower()
    if not text:
        return ""
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _as_list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _load_faq_data(app) -> dict[str, Any]:
    path = Path(str(app.config.get("FAQ_STORE_PATH", "data/user_faqs.json")))
    if not path.exists():
        return {}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logging.warning("Could not read FAQ store path=%s error=%s", path, exc)
        return {}

    if not isinstance(payload, dict):
        return {}
    return payload


def _candidate_entries(payload: dict[str, Any], wa_id: str) -> list[dict[str, Any]]:
    users = payload.get("users")
    user_entries: list[dict[str, Any]] = []
    if isinstance(users, dict):
        user_entries = _as_list_of_dicts(users.get(str(wa_id)))

    default_entries = _as_list_of_dicts(payload.get("default"))
    return user_entries + default_entries


def _questions_for_entry(entry: dict[str, Any]) -> list[str]:
    questions = entry.get("questions")
    if isinstance(questions, str):
        return [questions]
    if isinstance(questions, list):
        return [item for item in questions if isinstance(item, str)]
    return []


def _is_match(message: str, candidate: str) -> bool:
    normalized_message = _normalize_text(message)
    normalized_candidate = _normalize_text(candidate)
    if not normalized_message or not normalized_candidate:
        return False

    if normalized_message == normalized_candidate:
        return True

    return len(normalized_candidate) >= 4 and normalized_candidate in normalized_message


def find_faq_answer(app, wa_id: str, message_text: str) -> str | None:
    payload = _load_faq_data(app)
    for entry in _candidate_entries(payload, wa_id):
        answer = entry.get("answer")
        if not isinstance(answer, str) or not answer.strip():
            continue

        for question in _questions_for_entry(entry):
            if _is_match(message_text, question):
                return answer.strip()

    return None
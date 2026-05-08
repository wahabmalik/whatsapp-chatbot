from __future__ import annotations

from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from threading import Lock
from typing import Any

from app.services.observability import sanitize_text


ANALYTICS_EVENT_VERSION = "1.0"
DEFAULT_ANALYTICS_EVENT_STORE_PATH = "data/conversation_analytics_events.jsonl"
DEFAULT_ANALYTICS_EVENT_STORE_MAX_LINES = 5000
_REQUIRED_STAGE_NAMES = {
    "inbound_receive",
    "ai_outcome",
    "escalation_flag",
    "outbound_outcome",
}


class ConversationAnalyticsBuffer:
    def __init__(self, max_size: int = 250) -> None:
        self._max_size = max(1, int(max_size))
        self._events: deque[dict[str, Any]] = deque(maxlen=self._max_size)
        self._lock = Lock()

    def add_event(self, event: dict[str, Any]) -> None:
        with self._lock:
            self._events.append(dict(event))

    def get_all(self) -> list[dict[str, Any]]:
        with self._lock:
            return [deepcopy(item) for item in reversed(self._events)]

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


_persist_lock = Lock()


def _coerce_positive_int(value: Any, default: int) -> int:
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        return default
    return coerced if coerced > 0 else default


def _stable_key(prefix: str, raw_value: str | None) -> str:
    value = str(raw_value or "").strip()
    if not value:
        return f"{prefix}_unknown"
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sanitize_payload(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, dict):
        return {str(key): _sanitize_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_payload(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_payload(item) for item in value)
    if isinstance(value, set):
        return {_sanitize_payload(item) for item in value}
    if isinstance(value, frozenset):
        return frozenset(_sanitize_payload(item) for item in value)
    return value


def get_analytics_event_buffer(app, max_size: int = 250) -> ConversationAnalyticsBuffer:
    key = "conversation_analytics_buffer"
    buffer = app.extensions.get(key)
    if buffer is None:
        configured_max = _coerce_positive_int(
            app.config.get("ANALYTICS_EVENT_BUFFER_SIZE", max_size),
            max_size,
        )
        buffer = ConversationAnalyticsBuffer(max_size=configured_max)
        app.extensions[key] = buffer
    return buffer


def _analytics_store_path(app) -> Path:
    configured = str(app.config.get("ANALYTICS_EVENT_STORE_PATH", DEFAULT_ANALYTICS_EVENT_STORE_PATH)).strip()
    return Path(configured)


def _analytics_store_max_lines(app) -> int:
    return _coerce_positive_int(
        app.config.get("ANALYTICS_EVENT_STORE_MAX_LINES", DEFAULT_ANALYTICS_EVENT_STORE_MAX_LINES),
        DEFAULT_ANALYTICS_EVENT_STORE_MAX_LINES,
    )


def _persist_event(app, event: dict[str, Any]) -> None:
    store_path = _analytics_store_path(app)
    max_lines = _analytics_store_max_lines(app)
    store_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event, ensure_ascii=True)
    with _persist_lock:
        with store_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        lines = store_path.read_text(encoding="utf-8").splitlines()
        if len(lines) > max_lines:
            store_path.write_text("\n".join(lines[-max_lines:]) + "\n", encoding="utf-8")


def get_recent_analytics_events(app, limit: int = 50) -> list[dict[str, Any]]:
    safe_limit = max(1, min(500, int(limit)))
    store_path = _analytics_store_path(app)
    if not store_path.exists():
        return get_analytics_event_buffer(app).get_all()[:safe_limit]

    events: list[dict[str, Any]] = []
    with _persist_lock:
        lines = store_path.read_text(encoding="utf-8").splitlines()

    for line in reversed(lines[-safe_limit:]):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            events.append(item)
    return events


def emit_analytics_event(
    app,
    *,
    stage: str,
    correlation_id: str,
    user_id: str | None,
    conversation_id: str | None,
    outcome_status: str,
    details: dict[str, Any] | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    normalized_stage = str(stage or "").strip().lower()
    if normalized_stage not in _REQUIRED_STAGE_NAMES:
        raise ValueError(f"Unsupported analytics stage: {stage}")

    event = {
        "event_version": ANALYTICS_EVENT_VERSION,
        "event_type": f"conversation.{normalized_stage}",
        "stage": normalized_stage,
        "timestamp": str(timestamp or _utc_timestamp()),
        "correlation_id": sanitize_text(str(correlation_id or "")),
        "conversation_key": _stable_key("conv", conversation_id or user_id),
        "user_key": _stable_key("usr", user_id),
        "outcome_status": sanitize_text(str(outcome_status or "unknown")),
        "details": _sanitize_payload(details or {}),
    }
    get_analytics_event_buffer(app).add_event(event)
    _persist_event(app, event)
    return event


def summarize_recent_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    escalation_events = [
        item for item in events
        if item.get("stage") == "escalation_flag"
    ]
    flagged = [
        item for item in escalation_events
        if str(item.get("outcome_status", "")).lower() == "flagged"
    ]
    total = len(escalation_events)
    flagged_count = len(flagged)
    return {
        "total_events": len(events),
        "escalation_events": total,
        "escalation_flagged_count": flagged_count,
        "escalation_flag_rate": (flagged_count / total) if total else 0.0,
    }

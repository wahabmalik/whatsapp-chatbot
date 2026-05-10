from __future__ import annotations

from collections import deque
from copy import deepcopy
from datetime import timedelta
from datetime import datetime, timezone
import hashlib
import math
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


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None

    candidate = value.strip()
    if not candidate:
        return None
    if candidate.endswith("Z"):
        candidate = f"{candidate[:-1]}+00:00"

    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _analytics_event_timestamp(event: dict[str, Any]) -> datetime | None:
    return _parse_timestamp(event.get("timestamp"))


def _coerce_detail_latency_ms(event: dict[str, Any]) -> int | None:
    details = event.get("details")
    if not isinstance(details, dict):
        return None

    for key in ("latency_ms", "duration_ms", "elapsed_ms"):
        try:
            raw_value = details.get(key)
            if raw_value is None:
                continue
            coerced = int(float(raw_value))
        except (TypeError, ValueError):
            continue
        if coerced >= 0:
            return coerced
    return None


def _percentile(values: list[int], percentile: float) -> int:
    if not values:
        return 0

    ordered = sorted(values)
    if len(ordered) == 1:
        return int(ordered[0])

    position = (len(ordered) - 1) * percentile
    lower_index = int(math.floor(position))
    upper_index = int(math.ceil(position))
    if lower_index == upper_index:
        return int(round(ordered[lower_index]))

    lower_value = ordered[lower_index]
    upper_value = ordered[upper_index]
    weight = position - lower_index
    return int(round(lower_value + (upper_value - lower_value) * weight))


def _event_date_key(event: dict[str, Any]) -> str | None:
    timestamp = _analytics_event_timestamp(event)
    if timestamp is None:
        return None
    return timestamp.date().isoformat()


def _retention_cutoff(retention_days: int, *, now: datetime | None = None) -> datetime:
    base = now or datetime.now(timezone.utc)
    safe_days = max(0, int(retention_days))
    return base - timedelta(days=safe_days)


def _event_within_retention(event: dict[str, Any], cutoff: datetime) -> bool:
    timestamp = _analytics_event_timestamp(event)
    if timestamp is None:
        return True
    return timestamp >= cutoff


def _normalize_delivery_status(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"success", "sent", "ok", "delivered"}:
        return "success"
    if normalized in {"retry", "retried", "deferred", "fallback", "fallback_sent"}:
        return "retry"
    return "failure"


def _build_trend_series(events: list[dict[str, Any]], *, stage: str, window_days: int) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for event in events:
        if event.get("stage") != stage:
            continue
        day_key = _event_date_key(event)
        if day_key is None:
            continue
        counts[day_key] = counts.get(day_key, 0) + 1

    today = datetime.now(timezone.utc).date()
    series: list[dict[str, Any]] = []
    for offset in range(window_days):
        day = today - timedelta(days=offset)
        day_key = day.isoformat()
        series.append({"date": day_key, "count": counts.get(day_key, 0)})
    return series


def _build_delivery_breakdown(events: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"success": 0, "retry": 0, "failure": 0}
    for event in events:
        if event.get("stage") != "outbound_outcome":
            continue
        status = _normalize_delivery_status(event.get("outcome_status"))
        counts[status] += 1
    return counts


def _build_latency_summary(events: list[dict[str, Any]]) -> dict[str, int]:
    latencies: list[int] = []
    correlated_events: dict[str, list[datetime]] = {}

    for event in events:
        explicit_latency = _coerce_detail_latency_ms(event)
        if explicit_latency is not None:
            latencies.append(explicit_latency)
            continue

        correlation_id = str(event.get("correlation_id") or "").strip()
        timestamp = _analytics_event_timestamp(event)
        if not correlation_id or timestamp is None:
            continue
        correlated_events.setdefault(correlation_id, []).append(timestamp)

    for timestamps in correlated_events.values():
        if len(timestamps) < 2:
            continue
        earliest = min(timestamps)
        latest = max(timestamps)
        delta_ms = int(max(0.0, (latest - earliest).total_seconds() * 1000.0))
        latencies.append(delta_ms)

    return {
        "p50_ms": _percentile(latencies, 0.50),
        "p95_ms": _percentile(latencies, 0.95),
        "p99_ms": _percentile(latencies, 0.99),
    }


def get_retained_analytics_events(app, *, retention_days: int | None = None) -> list[dict[str, Any]]:
    if retention_days is None:
        retention_days = int(app.config.get("ANALYTICS_RETENTION_DAYS", 90))

    store_path = _analytics_store_path(app)
    if not store_path.exists():
        return get_analytics_event_buffer(app).get_all()

    cutoff = _retention_cutoff(retention_days)
    retained: list[dict[str, Any]] = []
    with _persist_lock:
        lines = store_path.read_text(encoding="utf-8").splitlines()

    for line in lines:
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict):
            continue
        if _event_within_retention(item, cutoff):
            retained.append(item)
    return retained


def prune_analytics_event_store(app, *, retention_days: int | None = None) -> int:
    if retention_days is None:
        retention_days = int(app.config.get("ANALYTICS_RETENTION_DAYS", 90))

    store_path = _analytics_store_path(app)
    if not store_path.exists():
        return 0

    cutoff = _retention_cutoff(retention_days)
    with _persist_lock:
        lines = store_path.read_text(encoding="utf-8").splitlines()

    retained_lines: list[str] = []
    pruned = 0
    for line in lines:
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            pruned += 1
            continue
        if not isinstance(item, dict):
            pruned += 1
            continue
        if _event_within_retention(item, cutoff):
            retained_lines.append(json.dumps(item, ensure_ascii=True))
        else:
            pruned += 1

    with _persist_lock:
        if retained_lines:
            store_path.write_text("\n".join(retained_lines) + "\n", encoding="utf-8")
        else:
            store_path.write_text("", encoding="utf-8")

    return pruned


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


def get_analytics_summary(app, *, window_days: int = 7) -> dict[str, Any]:
    safe_window_days = max(1, int(window_days))
    retention_days = int(app.config.get("ANALYTICS_RETENTION_DAYS", 90))
    retained_events = get_retained_analytics_events(app, retention_days=retention_days)

    return {
        "window_days": safe_window_days,
        "retention_days": max(0, retention_days),
        "generated_at": _utc_timestamp(),
        "volume_trend": _build_trend_series(retained_events, stage="inbound_receive", window_days=safe_window_days),
        "escalation_trend": _build_trend_series(retained_events, stage="escalation_flag", window_days=safe_window_days),
        "delivery_breakdown": _build_delivery_breakdown(retained_events),
        "latency_summary": _build_latency_summary(retained_events),
    }

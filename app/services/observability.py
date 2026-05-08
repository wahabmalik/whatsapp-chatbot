from __future__ import annotations

import logging
import re
import uuid
from contextvars import ContextVar
from typing import Any


CORRELATION_ID_HEADER = "X-Request-ID"
MAX_CORRELATION_ID_LENGTH = 128

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)

_KEY_VALUE_PATTERN = re.compile(
    r"(?i)(?P<key>access[_-]?token|app[_-]?secret|verify[_-]?token|openai[_-]?api[_-]?key|authorization)\s*[:=]\s*(?P<value>[^\s,;]+)"
)
_AUTH_BEARER_PATTERN = re.compile(
    r"(?i)(authorization\s*[:=]\s*bearer\s+[^\s,;]+)"
)
_BEARER_PATTERN = re.compile(r"(?i)bearer\s+[a-z0-9\-._~+/]+=*")
_OPENAI_KEY_PATTERN = re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9_-]{7,}\b")
_PHONE_PATTERN = re.compile(r"(?<!\w)(\+?\d{1,4})\d+(\d{4})(?!\d)")


def sanitize_text(value: str) -> str:
    sanitized = value
    sanitized = _AUTH_BEARER_PATTERN.sub("authorization=[REDACTED]", sanitized)
    sanitized = _KEY_VALUE_PATTERN.sub(lambda m: f"{m.group('key')}=[REDACTED]", sanitized)
    sanitized = _BEARER_PATTERN.sub("Bearer [REDACTED]", sanitized)
    sanitized = _OPENAI_KEY_PATTERN.sub("sk-[REDACTED]", sanitized)
    sanitized = _PHONE_PATTERN.sub(lambda m: f"{m.group(1)}...{m.group(2)}", sanitized)
    return sanitized


def _sanitize_arg(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, dict):
        return {key: _sanitize_arg(item) for key, item in value.items()}
    if isinstance(value, set):
        return {_sanitize_arg(item) for item in value}
    if isinstance(value, frozenset):
        return frozenset(_sanitize_arg(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_sanitize_arg(item) for item in value)
    if isinstance(value, list):
        return [_sanitize_arg(item) for item in value]
    return value


class SafeObservabilityFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = get_correlation_id() or "n/a"

        if isinstance(record.msg, str):
            record.msg = sanitize_text(record.msg)

        if record.args:
            if isinstance(record.args, tuple):
                record.args = tuple(_sanitize_arg(item) for item in record.args)
            elif isinstance(record.args, dict):
                record.args = {key: _sanitize_arg(item) for key, item in record.args.items()}
            else:
                record.args = _sanitize_arg(record.args)

        return True


def get_correlation_id() -> str | None:
    return _correlation_id.get()


def set_correlation_id(value: str | None) -> str:
    candidate = (value or "").strip()
    if candidate:
        candidate = re.sub(r"[^A-Za-z0-9._:-]", "", candidate)
        candidate = candidate[:MAX_CORRELATION_ID_LENGTH]
    if not candidate:
        candidate = str(uuid.uuid4())
    _correlation_id.set(candidate)
    return candidate


def ensure_correlation_id(value: str | None = None) -> str:
    if value and value.strip():
        return set_correlation_id(value)

    existing = get_correlation_id()
    if existing:
        return existing
    return set_correlation_id(None)


def clear_correlation_id() -> None:
    _correlation_id.set(None)
from __future__ import annotations

from collections import deque
from copy import deepcopy
from threading import Lock
from typing import Any


class MessageLogBuffer:
    def __init__(self, max_size: int = 100) -> None:
        self._max_size = max(1, int(max_size))
        self._entries: deque[dict[str, Any]] = deque(maxlen=self._max_size)
        self._lock = Lock()

    @property
    def max_size(self) -> int:
        return self._max_size

    def add_message(self, message: dict[str, Any]) -> None:
        with self._lock:
            self._entries.append(dict(message))

    def get_all(self) -> list[dict[str, Any]]:
        with self._lock:
            # Return newest first for dashboards and log views.
            return [deepcopy(item) for item in reversed(self._entries)]

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


def get_message_log_buffer(app, max_size: int = 100) -> MessageLogBuffer:
    key = "message_log_buffer"
    buffer = app.extensions.get(key)
    if buffer is None:
        buffer = MessageLogBuffer(max_size=max_size)
        app.extensions[key] = buffer
    return buffer

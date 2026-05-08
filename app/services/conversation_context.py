"""
app/services/conversation_context.py

Per-user rolling conversation context window (FR9).

Stores at most MAX_MESSAGES messages per user and automatically
resets on inactivity timeout or explicit boundary reset.
"""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from threading import Lock
from time import monotonic
from typing import Any

MAX_MESSAGES: int = 5
DEFAULT_TIMEOUT_SECONDS: float = 1800.0  # 30 minutes


class ConversationContextStore:
    """Thread-safe, in-memory per-user conversation context store."""

    def __init__(self, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self._timeout = max(1.0, float(timeout_seconds))
        # user_id -> {"messages": deque, "last_activity": monotonic timestamp}
        self._store: dict[str, dict[str, Any]] = {}
        self._lock = Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def append_message(self, user_id: str, message: dict[str, Any]) -> None:
        """Append a message for *user_id*, auto-resetting on timeout or new user."""
        with self._lock:
            now = monotonic()
            entry = self._store.get(user_id)
            if entry is None or (now - entry["last_activity"]) > self._timeout:
                # Expired or brand-new: start a fresh window.
                entry = {
                    "messages": deque(maxlen=MAX_MESSAGES),
                    "last_activity": now,
                }
                self._store[user_id] = entry
            entry["messages"].append(dict(message))
            entry["last_activity"] = now

    def get_context(self, user_id: str) -> list[dict[str, Any]]:
        """Return a shallow copy of the context list for *user_id*.

        Returns an empty list if the user is unknown or the window has expired.
        """
        with self._lock:
            entry = self._store.get(user_id)
            if entry is None:
                return []
            if (monotonic() - entry["last_activity"]) > self._timeout:
                del self._store[user_id]
                return []
            return [deepcopy(m) for m in entry["messages"]]

    def reset_context(self, user_id: str) -> None:
        """Explicitly clear the context for *user_id* (conversation boundary)."""
        with self._lock:
            self._store.pop(user_id, None)

    def clear(self) -> None:
        """Clear all stored contexts (e.g. on app teardown or test cleanup)."""
        with self._lock:
            self._store.clear()


# ------------------------------------------------------------------
# App-extension accessor (mirrors MessageLogBuffer pattern)
# ------------------------------------------------------------------

def get_conversation_context_store(
    app,
    timeout_seconds: float | None = None,
) -> ConversationContextStore:
    """Return the app-scoped ConversationContextStore, creating it on first call."""
    key = "conversation_context_store"
    store = app.extensions.get(key)
    if store is None:
        if timeout_seconds is None:
            timeout_seconds = float(
                app.config.get(
                    "CONVERSATION_CONTEXT_TIMEOUT_SECONDS",
                    DEFAULT_TIMEOUT_SECONDS,
                )
            )
        store = ConversationContextStore(timeout_seconds=timeout_seconds)
        app.extensions[key] = store
    return store

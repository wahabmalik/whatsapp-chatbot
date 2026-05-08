import logging
import sqlite3
import time
from threading import Lock
from typing import Callable, Optional


class ExpiringKeyStore:
    def __init__(
        self,
        window_seconds: int,
        now_fn: Optional[Callable[[], float]] = None,
    ) -> None:
        self.window_seconds = max(1, int(window_seconds))
        self._now_fn = now_fn or time.time
        self._items: dict[str, float] = {}
        self._lock = Lock()

    def seen_recently(self, key: str) -> bool:
        now = self._now_fn()
        with self._lock:
            self._purge_stale(now)
            if key in self._items:
                return True
            self._items[key] = now
            return False

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def close(self) -> None:
        # In-memory store has no external resources.
        return None

    def _purge_stale(self, now: float) -> None:
        stale = [
            key
            for key, seen_at in self._items.items()
            if now - seen_at > self.window_seconds
        ]
        for key in stale:
            del self._items[key]


class SQLiteExpiringKeyStore:
    def __init__(
        self,
        db_path: str,
        namespace: str,
        window_seconds: int,
        now_fn: Optional[Callable[[], float]] = None,
    ) -> None:
        self.db_path = db_path
        self.namespace = namespace
        self.window_seconds = max(1, int(window_seconds))
        self._now_fn = now_fn or time.time
        self._lock = Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._initialize()
        self._closed = False

    def _initialize(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS expiring_keys (
                    namespace TEXT NOT NULL,
                    key TEXT NOT NULL,
                    seen_at REAL NOT NULL,
                    PRIMARY KEY (namespace, key)
                )
                """
            )

    def seen_recently(self, key: str) -> bool:
        now = self._now_fn()
        cutoff = now - self.window_seconds

        with self._lock:
            with self._conn:
                self._conn.execute(
                    "DELETE FROM expiring_keys WHERE namespace = ? AND seen_at < ?",
                    (self.namespace, cutoff),
                )

                row = self._conn.execute(
                    "SELECT seen_at FROM expiring_keys WHERE namespace = ? AND key = ?",
                    (self.namespace, key),
                ).fetchone()
                if row is not None:
                    return True

                self._conn.execute(
                    "INSERT OR REPLACE INTO expiring_keys(namespace, key, seen_at) VALUES (?, ?, ?)",
                    (self.namespace, key, now),
                )
                return False

    def clear(self) -> None:
        with self._lock:
            with self._conn:
                self._conn.execute(
                    "DELETE FROM expiring_keys WHERE namespace = ?",
                    (self.namespace,),
                )

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._conn.close()
            self._closed = True

    def __del__(self):  # pragma: no cover - destructor safety
        try:
            self.close()
        except Exception:
            pass


def create_expiring_store(
    app,
    extension_key: str,
    namespace: str,
    window_seconds: int,
):
    existing = app.extensions.get(extension_key)
    if existing is not None:
        return existing

    backend = str(app.config.get("STATE_STORE_BACKEND", "memory")).strip().lower()
    if backend == "sqlite":
        db_path = str(app.config.get("STATE_STORE_SQLITE_PATH", "data/runtime_state.db"))
        try:
            store = SQLiteExpiringKeyStore(
                db_path=db_path,
                namespace=namespace,
                window_seconds=window_seconds,
            )
        except sqlite3.Error as exc:
            fallback_enabled = bool(
                app.config.get("STATE_STORE_FALLBACK_TO_MEMORY", True)
            )
            if not fallback_enabled:
                raise

            logging.warning(
                "STATE_STORE sqlite init failed for namespace=%s path=%s; "
                "falling back to in-memory store. "
                "Check that the path is writable and the parent directory exists. Error: %s",
                namespace,
                db_path,
                exc,
            )
            store = ExpiringKeyStore(window_seconds=window_seconds)
    else:
        store = ExpiringKeyStore(window_seconds=window_seconds)

    app.extensions[extension_key] = store
    return store
from __future__ import annotations

import collections
import time
from threading import Lock


BASE_COUNTER_KEYS = (
    "http.requests_total",
    "http.responses_total",
    "http.responses_4xx_total",
    "http.responses_5xx_total",
    "webhook.requests_total",
    "webhook.duplicates_total",
    "webhook.internal_errors_total",
    "webhook.processed_messages_total",
    "webhook.blocked_config_invalid_total",
    "webhook.status_updates_total",
    "webhook.invalid_events_total",
    "webhook.json_decode_errors_total",
    "whatsapp.send_attempt",
    "whatsapp.send_success",
    "whatsapp.send_error",
    "whatsapp.fallback_sent",
    "whatsapp.fallback_failed",
    "ai.reply_attempt",
    "ai.reply_success",
    "ai.reply_timeout",
    "ai.reply_auth_error",
    "ai.reply_rate_limited",
    "ai.reply_provider_error",
)
BASE_DURATION_KEYS = (
    "http.request_duration_seconds",
    "webhook.handle_message_seconds",
    "whatsapp.send_duration",
    "whatsapp.send_attempt_duration",
    "ai.reply_duration",
)

# Width of the sliding error window in seconds (5 minutes).
ERROR_WINDOW_SECONDS: float = 300.0


class MetricsCollector:
    def __init__(self) -> None:
        self._lock = Lock()
        self._counters: dict[str, int] = {}
        self._duration_totals: dict[str, float] = {}
        self._duration_counts: dict[str, int] = {}
        # Inflight gauge — tracks currently active (unfinished) requests.
        self._inflight: int = 0
        # Sliding-window error tracking — wall-clock timestamps of 4xx/5xx responses.
        self._error_timestamps: collections.deque = collections.deque()
        # Per-endpoint counters — keyed by Flask endpoint name.
        self._endpoint_counters: dict[str, dict[str, int]] = {}

    def increment(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + amount

    def observe_duration(self, name: str, seconds: float) -> None:
        with self._lock:
            self._duration_totals[name] = self._duration_totals.get(name, 0.0) + seconds
            self._duration_counts[name] = self._duration_counts.get(name, 0) + 1

    def inc_inflight(self) -> None:
        """Increment the in-flight request gauge (call at request start)."""
        with self._lock:
            self._inflight += 1

    def dec_inflight(self) -> None:
        """Decrement the in-flight request gauge (call at request teardown)."""
        with self._lock:
            self._inflight = max(0, self._inflight - 1)

    def record_error(self, ts: float | None = None) -> None:
        """Record a 4xx/5xx response timestamp for the sliding-window error rate."""
        now = ts if ts is not None else time.time()
        with self._lock:
            self._error_timestamps.append(now)

    def record_endpoint_request(self, endpoint: str, status_code: int) -> None:
        """Increment per-endpoint request and error counters."""
        with self._lock:
            ep = self._endpoint_counters.setdefault(
                endpoint, {"requests_total": 0, "errors_total": 0}
            )
            ep["requests_total"] += 1
            if status_code >= 400:
                ep["errors_total"] += 1

    def snapshot(self) -> dict:
        with self._lock:
            counters = dict(self._counters)
            for key in BASE_COUNTER_KEYS:
                counters.setdefault(key, 0)

            totals = dict(self._duration_totals)
            counts = dict(self._duration_counts)
            for key in BASE_DURATION_KEYS:
                totals.setdefault(key, 0.0)
                counts.setdefault(key, 0)

            average_durations = {
                key: (totals[key] / counts[key])
                for key in totals
                if counts.get(key, 0) > 0
            }

            inflight = self._inflight

            # Prune expired entries from the sliding error window.
            cutoff = time.time() - ERROR_WINDOW_SECONDS
            while self._error_timestamps and self._error_timestamps[0] < cutoff:
                self._error_timestamps.popleft()
            errors_in_window = len(self._error_timestamps)

            endpoint_counters = {
                ep: dict(v) for ep, v in self._endpoint_counters.items()
            }

            return {
                "counters": counters,
                "durations": {
                    "totals": totals,
                    "counts": counts,
                    "averages": average_durations,
                },
                "inflight": inflight,
                "errors_last_300s": errors_in_window,
                "endpoints": endpoint_counters,
            }


def get_metrics_collector(app):
    key = "metrics_collector"
    collector = app.extensions.get(key)
    if collector is None:
        collector = MetricsCollector()
        app.extensions[key] = collector
    return collector


class Timer:
    def __init__(self) -> None:
        self._start = time.monotonic()

    def elapsed(self) -> float:
        return time.monotonic() - self._start
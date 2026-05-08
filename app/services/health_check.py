from __future__ import annotations

from datetime import datetime, timezone

from app.services.observability import get_correlation_id


def set_last_error(app, error_message: str | None) -> None:
    app.extensions["last_runtime_error"] = (error_message or "").strip() or None


def get_setup_status(app) -> dict[str, object]:
    """Return setup and configuration validation status."""
    from app.config import get_required_config_readiness
    
    validation_errors = app.extensions.get("config_validation_errors", [])
    config_readiness = get_required_config_readiness(app)
    
    required_keys = [item["key"] for item in config_readiness]
    missing_keys = [item["key"] for item in config_readiness if not item["ready"]]
    
    is_setup_complete = len(missing_keys) == 0 and len(validation_errors) == 0
    
    return {
        "setup_complete": is_setup_complete,
        "validation_errors": validation_errors,
        "required_keys": required_keys,
        "missing_keys": missing_keys,
        "config_readiness": config_readiness,
    }


def get_bot_health(app) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    started_at = app.extensions.get("app_started_at")
    last_error = app.extensions.get("last_runtime_error")
    last_request_at = app.extensions.get("last_request_at")

    uptime_seconds = 0
    if isinstance(started_at, datetime):
        uptime_seconds = max(0, int((now - started_at).total_seconds()))

    request_age_seconds = None
    if isinstance(last_request_at, datetime):
        request_age_seconds = max(0, int((now - last_request_at).total_seconds()))

    from app.services.metrics import get_metrics_collector

    counters = get_metrics_collector(app).snapshot().get("counters", {})
    health_metrics = {
        "requests_total": counters.get("http.requests_total", 0),
        "responses_4xx_total": counters.get("http.responses_4xx_total", 0),
        "responses_5xx_total": counters.get("http.responses_5xx_total", 0),
        "webhook_requests_total": counters.get("webhook.requests_total", 0),
        "webhook_internal_errors_total": counters.get("webhook.internal_errors_total", 0),
    }
    
    # Include setup status in health check
    setup_status = get_setup_status(app)

    return {
        "status": "running" if last_error is None else "degraded",
        "uptime_seconds": uptime_seconds,
        "last_error": last_error,
        "request_id": get_correlation_id() or "n/a",
        "last_request_age_seconds": request_age_seconds,
        "metrics": health_metrics,
        "setup": setup_status,
    }

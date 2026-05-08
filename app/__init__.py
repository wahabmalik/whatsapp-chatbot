from flask import Flask
from flask_session import Session
from cachelib.file import FileSystemCache
from datetime import datetime, timezone
import time
from app.config import (
    configure_logging,
    get_required_config_readiness,
    load_configurations,
    refresh_config_validation_errors,
)
from .views import webhook_blueprint
from .views_auth import auth_blueprint
from .views_dashboard import dashboard_blueprint
from .onboarding import onboarding_blueprint
import logging
from flask import g, request

from app.services.observability import (
    CORRELATION_ID_HEADER,
    clear_correlation_id,
    ensure_correlation_id,
    get_correlation_id,
)
from app.services.metrics import get_metrics_collector
from app.saas_db import SaaSDatabase


def create_app():
    app = Flask(__name__)
    app.extensions["app_started_at"] = datetime.now(timezone.utc)
    app.extensions["last_runtime_error"] = None

    # Load configurations and logging settings
    load_configurations(app)
    configure_logging()
    app.config["SESSION_TYPE"] = "cachelib"
    app.config["SESSION_CACHELIB"] = FileSystemCache(
        app.config["_SESSION_DIR"],
        threshold=500,
        mode=0o600,
    )
    Session(app)

    validation_errors = refresh_config_validation_errors(app)
    for item in get_required_config_readiness(app):
        logging.info("CONFIG_READINESS key=%s ready=%s", item["key"], item["ready"])
    if validation_errors:
        logging.warning(
            "Configuration validation issues detected; setup flow remains available: %s",
            "; ".join(validation_errors),
        )

    # Verify the WhatsApp channel lazy import resolves at startup, not at first request.
    from app.services.channel_interface import _probe_whatsapp_send_fn
    _probe_whatsapp_send_fn()

    # SaaS v1 database — initialise only when DATABASE_URL is configured.
    saas_db = SaaSDatabase()
    saas_db.init_app(app)
    if saas_db.is_ready:
        if not saas_db.verify_connectivity():
            raise RuntimeError(
                "SAAS_DB_STARTUP_FAIL Database configured but unreachable. "
                "Set a reachable DATABASE_URL before starting the application."
            )
        try:
            saas_db.create_tables()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "SAAS_DB_STARTUP_FAIL Database schema bootstrap failed. "
                "Set a reachable DATABASE_URL before starting the application."
            ) from exc

    # SMTP password-reset dispatch — registered only when SMTP_HOST is configured.
    _smtp_host = app.config.get("SMTP_HOST")
    if _smtp_host:
        from app.utils.email import build_smtp_dispatch
        _from = app.config.get("SMTP_FROM_ADDRESS") or app.config.get("SMTP_USERNAME") or "noreply@localhost"
        _ttl = int(app.config.get("PASSWORD_RESET_TOKEN_TTL_MINUTES", 30))
        app.config["AUTH_PASSWORD_RESET_DISPATCH"] = build_smtp_dispatch(
            smtp_host=_smtp_host,
            smtp_port=int(app.config.get("SMTP_PORT", 587)),
            smtp_username=app.config.get("SMTP_USERNAME"),
            smtp_password=app.config.get("SMTP_PASSWORD"),
            from_address=_from,
            use_tls=bool(app.config.get("SMTP_USE_TLS", True)),
            ttl_minutes=_ttl,
        )
        logging.info("SMTP_DISPATCH_REGISTERED host=%s port=%s", _smtp_host, app.config.get("SMTP_PORT"))
    else:
        logging.warning(
            "SMTP_HOST not configured — password reset emails will not be sent in production. "
            "Set SMTP_HOST (and related SMTP_* env vars) to enable."
        )

    # Import and register blueprints, if any
    app.register_blueprint(webhook_blueprint)
    app.register_blueprint(auth_blueprint)
    app.register_blueprint(dashboard_blueprint)
    app.register_blueprint(onboarding_blueprint)

    @app.before_request
    def _bind_correlation_id():
        ensure_correlation_id(request.headers.get(CORRELATION_ID_HEADER))
        g._request_started_at = time.monotonic()
        m = get_metrics_collector(app)
        m.increment("http.requests_total")
        m.inc_inflight()

    @app.after_request
    def _attach_correlation_header(response):
        metrics = get_metrics_collector(app)
        response.headers[CORRELATION_ID_HEADER] = get_correlation_id() or ensure_correlation_id(None)
        metrics.increment("http.responses_total")
        is_error = response.status_code >= 400
        if response.status_code >= 500:
            metrics.increment("http.responses_5xx_total")
        elif is_error:
            metrics.increment("http.responses_4xx_total")
        if is_error:
            metrics.record_error()

        endpoint = request.endpoint or "unknown"
        metrics.record_endpoint_request(endpoint, response.status_code)

        started_at = getattr(g, "_request_started_at", None)
        if isinstance(started_at, float):
            metrics.observe_duration("http.request_duration_seconds", max(0.0, time.monotonic() - started_at))

        app.extensions["last_request_at"] = datetime.now(timezone.utc)
        return response

    @app.teardown_request
    def _clear_correlation_id(_exception):
        get_metrics_collector(app).dec_inflight()
        clear_correlation_id()

    @app.teardown_appcontext
    def _cleanup_extension_resources(_exception):
        for extension in list(app.extensions.values()):
            close_method = getattr(extension, "close", None)
            if callable(close_method):
                try:
                    close_method()
                except Exception as exc:  # noqa: BLE001
                    logging.warning(
                        "Extension close() raised during teardown: %s",
                        exc,
                    )

    return app

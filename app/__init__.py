from flask import Flask
from flask_session import Session
from cachelib.file import FileSystemCache
from datetime import datetime, timezone
import os
import sys
import time
from app.config import (
    configure_logging,
    get_required_config_readiness,
    load_configurations,
    refresh_config_validation_errors,
)
from .views import webhook_blueprint
from .views_auth import auth_blueprint
from .views_dashboard import dashboard_api, dashboard_blueprint
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
from app.cli_db import db_cli
from app.utils.email import build_smtp_dispatch


def create_app(config_name=None):
    app = Flask(__name__)
    app.extensions["app_started_at"] = datetime.now(timezone.utc)
    app.extensions["last_runtime_error"] = None

    running_under_pytest = bool(os.environ.get("PYTEST_CURRENT_TEST") or "pytest" in sys.modules)
    explicit_db_env = bool(os.environ.get("DATABASE_URL") or os.environ.get("SAAS_DATABASE_URL"))

    # Load configurations and logging settings
    load_configurations(app)
    configure_logging()
    smtp_host = str(app.config.get("SMTP_HOST") or "").strip()
    if smtp_host:
        app.config["AUTH_PASSWORD_RESET_DISPATCH"] = build_smtp_dispatch(
            smtp_host=smtp_host,
            smtp_port=int(app.config.get("SMTP_PORT", 587)),
            smtp_username=app.config.get("SMTP_USERNAME"),
            smtp_password=app.config.get("SMTP_PASSWORD"),
            from_address=(
                app.config.get("SMTP_FROM_ADDRESS")
                or app.config.get("SMTP_USERNAME")
                or "no-reply@example.invalid"
            ),
            use_tls=bool(app.config.get("SMTP_USE_TLS", True)),
            ttl_minutes=int(app.config.get("PASSWORD_RESET_TOKEN_TTL_MINUTES", 30)),
        )
    else:
        logging.warning(
            "AUTH_PASSWORD_RESET_DISPATCH_NOT_CONFIGURED SMTP_HOST is missing; forgot-password emails are disabled"
        )
    app.config["SESSION_TYPE"] = "cachelib"
    app.config["SESSION_CACHELIB"] = FileSystemCache(
        app.config["_SESSION_DIR"],
        threshold=500,
        mode=0o600,
    )
    Session(app)

    refresh_config_validation_errors(app)

    # Ensure database initialization is fully bypassed in testing
    if config_name == "testing":
        app.config["SAAS_DB_MOCK"] = True
        logging.info("Mocking database connectivity for testing environment.")

    # Keep tests deterministic: when DATABASE_URL is not explicitly provided by the
    # test process, avoid loading machine-local DB defaults from .env.
    if running_under_pytest and not explicit_db_env:
        app.config["SAAS_DB_MOCK"] = True

    # Skip SaaS database initialization if mock is enabled
    if app.config.get("SAAS_DB_MOCK"):
        logging.info("Skipping SaaS database initialization due to mock configuration.")
    else:
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

    # Initialize OAuth2 service
    from app.services.oauth_service import oauth_service
    oauth_service.init_app(app)

    app.register_blueprint(webhook_blueprint)
    app.register_blueprint(auth_blueprint)
    app.register_blueprint(dashboard_blueprint)
    app.register_blueprint(dashboard_api)
    app.register_blueprint(onboarding_blueprint)

    app.cli.add_command(db_cli)

    @app.before_request
    def _before_request_metrics_and_correlation():
        g._request_started_at = time.perf_counter()
        metrics = get_metrics_collector(app)
        metrics.inc_inflight()
        metrics.increment("http.requests_total")
        ensure_correlation_id(request.headers.get(CORRELATION_ID_HEADER))

    @app.after_request
    def _after_request_metrics_and_correlation(response):
        metrics = get_metrics_collector(app)

        correlation_id = get_correlation_id() or ensure_correlation_id(None)
        response.headers[CORRELATION_ID_HEADER] = correlation_id

        metrics.increment("http.responses_total")
        if 400 <= response.status_code < 500:
            metrics.increment("http.responses_4xx_total")
            metrics.record_error()
        elif response.status_code >= 500:
            metrics.increment("http.responses_5xx_total")
            metrics.record_error()

        metrics.record_endpoint_request(request.endpoint or "unknown", response.status_code)

        started_at = getattr(g, "_request_started_at", None)
        if started_at is not None:
            metrics.observe_duration(
                "http.request_duration_seconds",
                max(0.0, time.perf_counter() - started_at),
            )

        return response

    @app.teardown_request
    def _teardown_request_context(_exc):
        get_metrics_collector(app).dec_inflight()
        clear_correlation_id()

    @app.teardown_appcontext
    def _teardown_appcontext(_exc):
        # Close each extension independently so one failure does not block others.
        for extension_name, extension in list(app.extensions.items()):
            close_fn = getattr(extension, "close", None)
            if not callable(close_fn):
                continue
            try:
                close_fn()
            except Exception as exc:  # noqa: BLE001
                logging.warning(
                    "Extension '%s' close() failed during teardown: %s",
                    extension_name,
                    exc,
                )

    return app

from __future__ import annotations

import secrets
import sys
import os
from dotenv import load_dotenv
import logging
import re
from pathlib import Path

from app.services.observability import SafeObservabilityFilter


PROVIDER_META = "meta"
PROVIDER_EVOLUTION = "evolution"

COMMON_REQUIRED_CONFIG_KEYS = (
    "OPENAI_API_KEY",
)

PROVIDER_REQUIRED_CONFIG_KEYS = {
    PROVIDER_META: (
        "ACCESS_TOKEN",
        "APP_SECRET",
        "VERSION",
        "PHONE_NUMBER_ID",
        "VERIFY_TOKEN",
    ),
    PROVIDER_EVOLUTION: (
        "EVOLUTION_API_URL",
        "EVOLUTION_API_KEY",
        "EVOLUTION_INSTANCE_NAME",
    ),
}


def is_config_value_set(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def normalize_provider(value: str | None, env: dict[str, str] | None = None) -> str:
    provider = str(value or "").strip().lower()
    if provider in PROVIDER_REQUIRED_CONFIG_KEYS:
        return provider

    source = env if env is not None else os.environ
    if any(is_config_value_set(source.get(key)) for key in PROVIDER_REQUIRED_CONFIG_KEYS[PROVIDER_EVOLUTION]):
        return PROVIDER_EVOLUTION
    return PROVIDER_META


def get_required_config_keys(provider: str) -> tuple[str, ...]:
    return COMMON_REQUIRED_CONFIG_KEYS + PROVIDER_REQUIRED_CONFIG_KEYS[provider]


def _as_int(name: str, default: int, minimum: int = 0) -> int:
    value = os.getenv(name, str(default)).strip()
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return parsed


def _as_float(name: str, default: float, minimum: float = 0.0) -> float:
    value = os.getenv(name, str(default)).strip()
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if parsed < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return parsed


def _as_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value")


def _as_csv_list(name: str, default: str) -> list[str]:
    raw = os.getenv(name, default)
    return [token.strip().lower() for token in raw.split(",") if token.strip()]


def validate_config(app) -> list[str]:
    errors: list[str] = []

    raw_provider = str(os.getenv("WHATSAPP_PROVIDER") or "").strip().lower()
    if raw_provider and raw_provider not in PROVIDER_REQUIRED_CONFIG_KEYS:
        errors.append(
            f"WHATSAPP_PROVIDER '{raw_provider}' is not recognized. "
            f"Must be one of: {', '.join(sorted(PROVIDER_REQUIRED_CONFIG_KEYS))}"
        )

    provider = normalize_provider(app.config.get("WHATSAPP_PROVIDER"))

    for key in get_required_config_keys(provider):
        if not is_config_value_set(app.config.get(key)):
            errors.append(f"Missing required configuration: {key}")

    if provider == PROVIDER_META:
        version = str(app.config.get("VERSION", "")).strip()
        if version and not re.match(r"^v\d+\.\d+$", version):
            errors.append("VERSION must match format v<major>.<minor>")

    numeric_keys: list[str] = []
    if provider == PROVIDER_META:
        numeric_keys.append("PHONE_NUMBER_ID")

    for numeric_key in numeric_keys:
        value = str(app.config.get(numeric_key, "")).strip()
        if value and not value.isdigit():
            errors.append(f"{numeric_key} must contain digits only")

    if provider == PROVIDER_EVOLUTION:
        api_url = str(app.config.get("EVOLUTION_API_URL", "")).strip()
        if api_url and not re.match(r"^https?://", api_url):
            errors.append("EVOLUTION_API_URL must start with http:// or https://")

    backend = str(app.config.get("STATE_STORE_BACKEND", "memory")).strip().lower()
    if backend not in {"memory", "sqlite"}:
        errors.append("STATE_STORE_BACKEND must be one of: memory, sqlite")

    from app.services.channel_interface import SUPPORTED_CHANNELS
    outbound_channel = str(app.config.get("OUTBOUND_CHANNEL", "whatsapp")).strip().lower()
    if outbound_channel not in SUPPORTED_CHANNELS:
        errors.append(
            f"OUTBOUND_CHANNEL '{outbound_channel}' is not supported. "
            f"Must be one of: {', '.join(sorted(SUPPORTED_CHANNELS))}"
        )

    return errors


def refresh_config_validation_errors(app) -> list[str]:
    """Recompute config validation errors and cache them on app extensions."""
    errors = validate_config(app)
    app.extensions["config_validation_errors"] = errors
    return errors


def load_configurations(app):
    load_dotenv()
    provider = normalize_provider(os.getenv("WHATSAPP_PROVIDER"), os.environ)
    app.config["WHATSAPP_PROVIDER"] = provider
    _secret_key = os.getenv("FLASK_SECRET_KEY") or os.getenv("SECRET_KEY")
    if not _secret_key:
        _secret_key = secrets.token_hex(32)
        logging.warning(
            "FLASK_SECRET_KEY is not set — using a random secret key. "
            "All user sessions will be invalidated on every restart. "
            "Set FLASK_SECRET_KEY in your .env file for production."
        )
    app.config["SECRET_KEY"] = _secret_key
    app.config["ACCESS_TOKEN"] = os.getenv("ACCESS_TOKEN")
    app.config["YOUR_PHONE_NUMBER"] = os.getenv("YOUR_PHONE_NUMBER")
    app.config["APP_ID"] = os.getenv("APP_ID")
    app.config["APP_SECRET"] = os.getenv("APP_SECRET")
    app.config["EVOLUTION_API_URL"] = os.getenv("EVOLUTION_API_URL")
    app.config["EVOLUTION_API_KEY"] = os.getenv("EVOLUTION_API_KEY")
    app.config["EVOLUTION_INSTANCE_NAME"] = os.getenv("EVOLUTION_INSTANCE_NAME")
    app.config["EVOLUTION_WEBHOOK_SECRET"] = os.getenv("EVOLUTION_WEBHOOK_SECRET")
    app.config["EVOLUTION_WEBHOOK_SECRET_HEADER"] = os.getenv(
        "EVOLUTION_WEBHOOK_SECRET_HEADER", "apikey"
    )
    app.config["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY")
    app.config["OPENAI_ASSISTANT_ID"] = os.getenv("OPENAI_ASSISTANT_ID")
    app.config["USE_OPENAI_SERVICE"] = _as_bool("USE_OPENAI_SERVICE", default=True)
    app.config["GOOGLE_AI_API_KEY"] = os.getenv("GOOGLE_AI_API_KEY")
    app.config["RECIPIENT_WAID"] = os.getenv("RECIPIENT_WAID")
    app.config["VERSION"] = os.getenv("VERSION")
    app.config["PHONE_NUMBER_ID"] = os.getenv("PHONE_NUMBER_ID")
    app.config["VERIFY_TOKEN"] = os.getenv("VERIFY_TOKEN")
    app.config["FAQ_STORE_PATH"] = os.getenv("FAQ_STORE_PATH", "data/user_faqs.json")
    app.config["OPENAI_RUN_TIMEOUT_SECONDS"] = _as_float(
        "OPENAI_RUN_TIMEOUT_SECONDS", default=30.0, minimum=1.0
    )
    app.config["OPENAI_POLL_INTERVAL_SECONDS"] = _as_float(
        "OPENAI_POLL_INTERVAL_SECONDS", default=0.5, minimum=0.1
    )
    app.config["OPENAI_MAX_RETRIES"] = _as_int(
        "OPENAI_MAX_RETRIES", default=2, minimum=0
    )
    app.config["OPENAI_RETRY_BACKOFF_SECONDS"] = _as_float(
        "OPENAI_RETRY_BACKOFF_SECONDS", default=0.5, minimum=0.0
    )
    app.config["WHATSAPP_SEND_TIMEOUT_SECONDS"] = _as_float(
        "WHATSAPP_SEND_TIMEOUT_SECONDS", default=10.0, minimum=0.1
    )
    app.config["WHATSAPP_FALLBACK_MAX_RETRIES"] = _as_int(
        "WHATSAPP_FALLBACK_MAX_RETRIES", default=2, minimum=1
    )
    app.config["WHATSAPP_DEFER_RETRIES"] = _as_bool(
        "WHATSAPP_DEFER_RETRIES", default=True
    )
    app.config["WHATSAPP_BACKGROUND_DELIVERY_WORKERS"] = _as_int(
        "WHATSAPP_BACKGROUND_DELIVERY_WORKERS", default=2, minimum=1
    )
    app.config["IDEMPOTENCY_WINDOW_SECONDS"] = _as_int(
        "IDEMPOTENCY_WINDOW_SECONDS", default=300, minimum=1
    )
    app.config["SIGNATURE_MAX_SKEW_SECONDS"] = _as_int(
        "SIGNATURE_MAX_SKEW_SECONDS", default=300, minimum=1
    )
    app.config["SIGNATURE_REPLAY_WINDOW_SECONDS"] = _as_int(
        "SIGNATURE_REPLAY_WINDOW_SECONDS", default=300, minimum=1
    )
    app.config["OUTBOUND_CHANNEL"] = os.getenv("OUTBOUND_CHANNEL", "whatsapp").strip().lower()
    app.config["STATE_STORE_BACKEND"] = os.getenv("STATE_STORE_BACKEND", "memory")
    sqlite_path = os.getenv("STATE_STORE_SQLITE_PATH", "data/runtime_state.db")
    app.config["STATE_STORE_SQLITE_PATH"] = sqlite_path
    app.config["STATE_STORE_FALLBACK_TO_MEMORY"] = _as_bool(
        "STATE_STORE_FALLBACK_TO_MEMORY", default=True
    )
    app.config["ESCALATION_CONFIDENCE_THRESHOLD"] = _as_float(
        "ESCALATION_CONFIDENCE_THRESHOLD", default=0.35, minimum=0.0
    )
    app.config["ESCALATION_KEYWORDS"] = _as_csv_list(
        "ESCALATION_KEYWORDS", default="human,agent,escalate,supervisor"
    )
    app.config["ESCALATION_QUEUE_PATH"] = os.getenv(
        "ESCALATION_QUEUE_PATH", "data/operator_review_queue.jsonl"
    )
    app.config["CONVERSATION_CONTEXT_TIMEOUT_SECONDS"] = _as_int(
        "CONVERSATION_CONTEXT_TIMEOUT_SECONDS", default=1800, minimum=1
    )
    # SaaS v1 database — optional; SaaS features unavailable when not set.
    app.config["DATABASE_URL"] = os.getenv("DATABASE_URL")
    session_dir = os.getenv("SESSION_FILE_DIR", "data/flask_session")
    app.config["_SESSION_DIR"] = session_dir
    app.config["SESSION_PERMANENT"] = _as_bool("SESSION_PERMANENT", default=False)
    app.config["SESSION_COOKIE_HTTPONLY"] = _as_bool("SESSION_COOKIE_HTTPONLY", default=True)
    app.config["SESSION_COOKIE_SAMESITE"] = os.getenv("SESSION_COOKIE_SAMESITE", "Lax")
    app.config["SESSION_COOKIE_SECURE"] = _as_bool("SESSION_COOKIE_SECURE", default=False)
    app.config["PASSWORD_RESET_TOKEN_TTL_MINUTES"] = _as_int(
        "PASSWORD_RESET_TOKEN_TTL_MINUTES", default=30, minimum=1
    )
    # SMTP email dispatch — all optional; feature is disabled when SMTP_HOST is absent.
    app.config["SMTP_HOST"] = os.getenv("SMTP_HOST")
    app.config["SMTP_PORT"] = _as_int("SMTP_PORT", default=587, minimum=1)
    app.config["SMTP_USERNAME"] = os.getenv("SMTP_USERNAME")
    app.config["SMTP_PASSWORD"] = os.getenv("SMTP_PASSWORD")
    app.config["SMTP_FROM_ADDRESS"] = os.getenv("SMTP_FROM_ADDRESS")
    app.config["SMTP_USE_TLS"] = _as_bool("SMTP_USE_TLS", default=True)
    app.config["APP_BASE_URL"] = os.getenv("APP_BASE_URL", "").rstrip("/")
    # Paddle billing — all optional; billing endpoints return 503 when not set.
    app.config["PADDLE_API_KEY"] = os.getenv("PADDLE_API_KEY")
    app.config["PADDLE_CLIENT_TOKEN"] = os.getenv("PADDLE_CLIENT_TOKEN")
    app.config["PADDLE_WEBHOOK_SECRET"] = os.getenv("PADDLE_WEBHOOK_SECRET")
    app.config["PADDLE_STARTER_PRICE_ID"] = os.getenv("PADDLE_STARTER_PRICE_ID")
    app.config["PADDLE_PRO_PRICE_ID"] = os.getenv("PADDLE_PRO_PRICE_ID")
    app.config["PADDLE_BUSINESS_PRICE_ID"] = os.getenv("PADDLE_BUSINESS_PRICE_ID")
    Path(sqlite_path).parent.mkdir(parents=True, exist_ok=True)
    Path(app.config["ESCALATION_QUEUE_PATH"]).parent.mkdir(parents=True, exist_ok=True)
    Path(session_dir).mkdir(parents=True, exist_ok=True)


def get_required_config_readiness(app) -> list[dict[str, object]]:
    provider = normalize_provider(app.config.get("WHATSAPP_PROVIDER"))
    return [
        {"key": key, "ready": is_config_value_set(app.config.get(key))}
        for key in get_required_config_keys(provider)
    ]


def configure_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - [corr=%(correlation_id)s] %(message)s",
        stream=sys.stdout,
        force=True,
    )

    safe_filter = SafeObservabilityFilter()
    root_logger = logging.getLogger()
    if not any(isinstance(existing, SafeObservabilityFilter) for existing in root_logger.filters):
        root_logger.addFilter(safe_filter)

    # Ensure every configured handler can format records with correlation_id.
    for handler in root_logger.handlers:
        if not any(isinstance(existing, SafeObservabilityFilter) for existing in handler.filters):
            handler.addFilter(safe_filter)

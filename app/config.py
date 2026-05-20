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


def _looks_like_placeholder(value: object) -> bool:
    if not isinstance(value, str):
        return False
    trimmed = value.strip()
    if not trimmed:
        return False

    lowered = trimmed.lower()
    placeholder_fragments = (
        "<your",
        "<from ",
        "<generate",
        "change-me",
        "your-",
        "yourdomain.com",
        "...",
    )
    if any(fragment in lowered for fragment in placeholder_fragments):
        return True

    # Common token templates that are intentionally incomplete.
    if trimmed in {"sk-...", "pri_...", "http://<your-evolution-host>:3333", "https://<your-railway-domain>"}:
        return True

    return False


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


def _running_under_pytest() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST") or "pytest" in sys.modules)


def _default_session_cookie_secure(app_base_url: str) -> bool:
    return str(app_base_url or "").strip().lower().startswith("https://")


def _read_persisted_secret_key(path: Path) -> str | None:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def _resolve_secret_key() -> str:
    configured = os.getenv("FLASK_SECRET_KEY") or os.getenv("SECRET_KEY")
    if configured:
        return configured

    if _running_under_pytest():
        return secrets.token_hex(32)

    secret_path_raw = (os.getenv("RUNTIME_SECRET_KEY_PATH") or "").strip() or "data/runtime_secret_key.txt"
    secret_path = Path(secret_path_raw)
    try:
        secret_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logging.warning(
            "RUNTIME_SECRET_KEY_PERSISTENCE_DIR_CREATE_FAILED path=%s reason=%s",
            secret_path.parent,
            exc,
        )
        return secrets.token_hex(32)

    existing = _read_persisted_secret_key(secret_path)
    if existing:
        return existing

    generated = secrets.token_hex(32)
    try:
        with secret_path.open("x", encoding="utf-8") as handle:
            handle.write(f"{generated}\n")
    except FileExistsError:
        existing_after_race = _read_persisted_secret_key(secret_path)
        if existing_after_race:
            return existing_after_race
    except OSError:
        logging.warning(
            "RUNTIME_SECRET_KEY_PERSISTENCE_WRITE_FAILED path=%s",
            secret_path,
        )
        return generated

    return generated


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

    onboarding_instance_mode = str(app.config.get("ONBOARDING_INSTANCE_MODE", "auto")).strip().lower()
    if onboarding_instance_mode not in {"auto", "shared", "tenant"}:
        errors.append("ONBOARDING_INSTANCE_MODE must be one of: auto, shared, tenant")

    placeholder_sensitive_keys = (
        "SECRET_KEY",
        "OPENAI_API_KEY",
        "EVOLUTION_API_URL",
        "EVOLUTION_API_KEY",
        "EVOLUTION_INSTANCE_NAME",
        "APP_BASE_URL",
        "PADDLE_API_KEY",
        "PADDLE_CLIENT_TOKEN",
        "PADDLE_WEBHOOK_SECRET",
        "PADDLE_STARTER_PRICE_ID",
        "PADDLE_PRO_PRICE_ID",
        "PADDLE_BUSINESS_PRICE_ID",
        "INSTAGRAM_OUTBOUND_URL",
        "INSTAGRAM_ACCESS_TOKEN",
        "MESSENGER_OUTBOUND_URL",
        "MESSENGER_PAGE_ACCESS_TOKEN",
        "TIKTOK_OUTBOUND_URL",
        "TIKTOK_ACCESS_TOKEN",
    )
    for key in placeholder_sensitive_keys:
        value = app.config.get(key)
        if is_config_value_set(value) and _looks_like_placeholder(value):
            errors.append(f"Configuration value for {key} appears to be a placeholder")

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

    channel_url_keys = {
        "instagram": "INSTAGRAM_OUTBOUND_URL",
        "messenger": "MESSENGER_OUTBOUND_URL",
        "tiktok": "TIKTOK_OUTBOUND_URL",
    }
    channel_url_key = channel_url_keys.get(outbound_channel)
    if channel_url_key:
        channel_url = str(app.config.get(channel_url_key, "")).strip()
        if channel_url and not re.match(r"^https?://", channel_url):
            errors.append(f"{channel_url_key} must start with http:// or https://")

    crm_export_enabled = bool(app.config.get("CRM_EXPORT_ENABLED", False))
    crm_export_url = str(app.config.get("CRM_EXPORT_WEBHOOK_URL", "")).strip()
    if crm_export_enabled and crm_export_url and not re.match(r"^https?://", crm_export_url):
        errors.append("CRM_EXPORT_WEBHOOK_URL must start with http:// or https://")
    if crm_export_enabled and not crm_export_url:
        errors.append("CRM_EXPORT_ENABLED requires CRM_EXPORT_WEBHOOK_URL to be configured")

    if bool(app.config.get("INDIA_D2C_STARTER_PACK_ENABLED", False)):
        cost_country = str(app.config.get("INDIA_MESSAGE_COST_COUNTRY", "IN") or "IN").strip().upper()
        if cost_country != "IN":
            errors.append(
                f"INDIA_MESSAGE_COST_COUNTRY must be 'IN' when INDIA_D2C_STARTER_PACK_ENABLED is true "
                f"(got '{cost_country}'). Cost estimation is constrained to India-only pricing."
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
    _secret_key = _resolve_secret_key()
    if not _secret_key:
        _secret_key = secrets.token_hex(32)
        logging.warning(
            "FLASK_SECRET_KEY is not set — using a random secret key. "
            "All user sessions will be invalidated on every restart. "
            "Set FLASK_SECRET_KEY in your .env file for production."
        )
    elif not (os.getenv("FLASK_SECRET_KEY") or os.getenv("SECRET_KEY")) and not _running_under_pytest():
        logging.warning(
            "FLASK_SECRET_KEY is not set — using a persisted runtime key from RUNTIME_SECRET_KEY_PATH. "
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
    app.config["ONBOARDING_INSTANCE_MODE"] = os.getenv("ONBOARDING_INSTANCE_MODE", "auto")
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
    # Telegram adapter credentials (Story 9.2). Required only when OUTBOUND_CHANNEL=telegram.
    # Absent credentials are accepted here; the adapter enters disabled state at runtime.
    app.config["TELEGRAM_BOT_TOKEN"] = os.getenv("TELEGRAM_BOT_TOKEN")
    app.config["TELEGRAM_DEFAULT_CHAT_ID"] = os.getenv("TELEGRAM_DEFAULT_CHAT_ID")
    app.config["TELEGRAM_SEND_TIMEOUT_SECONDS"] = _as_float(
        "TELEGRAM_SEND_TIMEOUT_SECONDS", default=10.0, minimum=0.1
    )
    app.config["INSTAGRAM_OUTBOUND_URL"] = os.getenv("INSTAGRAM_OUTBOUND_URL")
    app.config["INSTAGRAM_ACCESS_TOKEN"] = os.getenv("INSTAGRAM_ACCESS_TOKEN")
    app.config["INSTAGRAM_DEFAULT_RECIPIENT_ID"] = os.getenv("INSTAGRAM_DEFAULT_RECIPIENT_ID")
    app.config["INSTAGRAM_SEND_TIMEOUT_SECONDS"] = _as_float(
        "INSTAGRAM_SEND_TIMEOUT_SECONDS", default=10.0, minimum=0.1
    )
    app.config["INSTAGRAM_CONNECT_URL"] = os.getenv("INSTAGRAM_CONNECT_URL")
    app.config["MESSENGER_OUTBOUND_URL"] = os.getenv("MESSENGER_OUTBOUND_URL")
    app.config["MESSENGER_PAGE_ACCESS_TOKEN"] = os.getenv("MESSENGER_PAGE_ACCESS_TOKEN")
    app.config["MESSENGER_DEFAULT_RECIPIENT_ID"] = os.getenv("MESSENGER_DEFAULT_RECIPIENT_ID")
    app.config["MESSENGER_SEND_TIMEOUT_SECONDS"] = _as_float(
        "MESSENGER_SEND_TIMEOUT_SECONDS", default=10.0, minimum=0.1
    )
    app.config["MESSENGER_CONNECT_URL"] = os.getenv("MESSENGER_CONNECT_URL")
    app.config["TIKTOK_OUTBOUND_URL"] = os.getenv("TIKTOK_OUTBOUND_URL")
    app.config["TIKTOK_ACCESS_TOKEN"] = os.getenv("TIKTOK_ACCESS_TOKEN")
    app.config["TIKTOK_DEFAULT_RECIPIENT_ID"] = os.getenv("TIKTOK_DEFAULT_RECIPIENT_ID")
    app.config["TIKTOK_SEND_TIMEOUT_SECONDS"] = _as_float(
        "TIKTOK_SEND_TIMEOUT_SECONDS", default=10.0, minimum=0.1
    )
    app.config["TIKTOK_CONNECT_URL"] = os.getenv("TIKTOK_CONNECT_URL")
    app.config["CRM_EXPORT_ENABLED"] = _as_bool("CRM_EXPORT_ENABLED", default=False)
    app.config["CRM_EXPORT_WEBHOOK_URL"] = os.getenv("CRM_EXPORT_WEBHOOK_URL")
    app.config["CRM_EXPORT_API_KEY"] = os.getenv("CRM_EXPORT_API_KEY")
    app.config["CRM_EXPORT_TIMEOUT_SECONDS"] = _as_float(
        "CRM_EXPORT_TIMEOUT_SECONDS", default=5.0, minimum=0.1
    )
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
    app.config["ANALYTICS_RETENTION_DAYS"] = _as_int(
        "ANALYTICS_RETENTION_DAYS", default=90, minimum=1
    )
    app.config["INDIA_D2C_STARTER_PACK_ENABLED"] = _as_bool(
        "INDIA_D2C_STARTER_PACK_ENABLED", default=False
    )
    app.config["INDIA_D2C_STARTER_PACK_COHORT_PERCENT"] = _as_int(
        "INDIA_D2C_STARTER_PACK_COHORT_PERCENT", default=0, minimum=0
    )
    app.config["INDIA_D2C_STARTER_PACK_COHORT_TENANTS"] = _as_csv_list(
        "INDIA_D2C_STARTER_PACK_COHORT_TENANTS", default=""
    )
    app.config["INDIA_MESSAGE_COST_COUNTRY"] = os.getenv(
        "INDIA_MESSAGE_COST_COUNTRY", "IN"
    ).strip().upper()
    app.config["INDIA_MESSAGE_COST_MARKETING_PAISA"] = _as_int(
        "INDIA_MESSAGE_COST_MARKETING_PAISA", default=75, minimum=1
    )
    app.config["INDIA_MESSAGE_COST_UTILITY_PAISA"] = _as_int(
        "INDIA_MESSAGE_COST_UTILITY_PAISA", default=20, minimum=1
    )
    app.config["INDIA_MESSAGE_COST_AUTHENTICATION_PAISA"] = _as_int(
        "INDIA_MESSAGE_COST_AUTHENTICATION_PAISA", default=15, minimum=1
    )
    app.config["INDIA_MESSAGE_COST_WARNING_THRESHOLD_PAISA"] = _as_int(
        "INDIA_MESSAGE_COST_WARNING_THRESHOLD_PAISA", default=100, minimum=0
    )
    app.config["USAGE_ALERT_THRESHOLD_PCTS"] = os.getenv(
        "USAGE_ALERT_THRESHOLD_PCTS", "80"
    )
    app.config["RECONNECTION_DETECTION_WINDOW_SECONDS"] = _as_int(
        "RECONNECTION_DETECTION_WINDOW_SECONDS", default=60, minimum=1
    )
    app.config["RECONNECTION_MAX_RETRIES"] = _as_int(
        "RECONNECTION_MAX_RETRIES", default=3, minimum=1
    )
    app.config["STARTER_PACK_TELEMETRY_PATH"] = os.getenv(
        "STARTER_PACK_TELEMETRY_PATH", "data/starter_pack_telemetry.jsonl"
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
    app_base_url = os.getenv("APP_BASE_URL", "").rstrip("/")
    app.config["APP_BASE_URL"] = app_base_url
    secure_default = _default_session_cookie_secure(app_base_url)
    app.config["SESSION_COOKIE_SECURE"] = _as_bool("SESSION_COOKIE_SECURE", default=secure_default)
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
    app.config["GOOGLE_OAUTH_CLIENT_ID"] = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
    app.config["GOOGLE_OAUTH_CLIENT_SECRET"] = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
    app.config["FACEBOOK_OAUTH_APP_ID"] = os.getenv("FACEBOOK_OAUTH_APP_ID")
    app.config["FACEBOOK_OAUTH_APP_SECRET"] = os.getenv("FACEBOOK_OAUTH_APP_SECRET")
    app.config["LINKEDIN_OAUTH_CLIENT_ID"] = os.getenv("LINKEDIN_OAUTH_CLIENT_ID")
    app.config["LINKEDIN_OAUTH_CLIENT_SECRET"] = os.getenv("LINKEDIN_OAUTH_CLIENT_SECRET")
    # Paddle billing — all optional; billing endpoints return 503 when not set.
    app.config["PADDLE_API_KEY"] = os.getenv("PADDLE_API_KEY")
    app.config["PADDLE_CLIENT_TOKEN"] = os.getenv("PADDLE_CLIENT_TOKEN")
    app.config["PADDLE_WEBHOOK_SECRET"] = os.getenv("PADDLE_WEBHOOK_SECRET")
    app.config["PADDLE_STARTER_PRICE_ID"] = os.getenv("PADDLE_STARTER_PRICE_ID")
    app.config["PADDLE_PRO_PRICE_ID"] = os.getenv("PADDLE_PRO_PRICE_ID")
    app.config["PADDLE_BUSINESS_PRICE_ID"] = os.getenv("PADDLE_BUSINESS_PRICE_ID")
    app.config["BYPASS_BILLING_FOR_TESTS"] = _as_bool("BYPASS_BILLING_FOR_TESTS", default=False)
    Path(sqlite_path).parent.mkdir(parents=True, exist_ok=True)
    Path(app.config["ESCALATION_QUEUE_PATH"]).parent.mkdir(parents=True, exist_ok=True)
    Path(app.config["STARTER_PACK_TELEMETRY_PATH"]).parent.mkdir(parents=True, exist_ok=True)
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

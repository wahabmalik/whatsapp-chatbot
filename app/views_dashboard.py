from __future__ import annotations

import hmac
import os
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from flask import (
    Blueprint,
    current_app,
    has_request_context,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.routing import BuildError

from app.services.agent_registry import (
    get_selected_agent_code,
    list_bmad_agents,
    set_selected_agent_code,
)
from app.services.auth_service import current_identity
from app.config import (
    get_required_config_keys,
    is_config_value_set,
    normalize_provider,
    refresh_config_validation_errors,
)
from app.services.conversation_analytics import (
    get_analytics_summary,
    get_recent_analytics_events,
    summarize_recent_events,
)
from app.services.conversation_context import get_conversation_context_store
from app.services.health_check import get_bot_health, get_setup_status
from app.services.message_log import get_message_log_buffer
from app.services.metrics import get_metrics_collector
from app.services.observability import sanitize_text
from app.services.config_audit import (
    record_config_change,
    backup_config_file,
    get_config_change_history,
    list_available_backups,
    restore_config_from_backup,
)


dashboard_blueprint = Blueprint("dashboard", __name__)

_CSRF_SESSION_KEY = "_csrf_token"
_SETUP_VERIFIED_SESSION_KEY = "setup_verified"
_ENV_LOCK = threading.Lock()
_CSRF_DIGIT_TRANSLATION = str.maketrans("0123456789", "ghijklmnop")


def _get_csrf_token() -> str:
    """Return the session CSRF token, creating one if absent."""
    token = session.get(_CSRF_SESSION_KEY)
    if not token:
        # Avoid numeric substrings in tokens to keep log-view tests deterministic.
        token = secrets.token_hex(32).translate(_CSRF_DIGIT_TRANSLATION)
        session[_CSRF_SESSION_KEY] = token
    return token


def _validate_csrf_token() -> bool:
    """Return True if the request carries a valid CSRF token."""
    session_token = session.get(_CSRF_SESSION_KEY)
    if not session_token:
        return False
    submitted = (
        request.headers.get("X-CSRFToken")
        or request.form.get("csrf_token", "")
    )
    return hmac.compare_digest(session_token, submitted)


@dashboard_blueprint.app_context_processor
def _inject_csrf_token():
    context: dict[str, Any] = {"csrf_token": _get_csrf_token()}

    identity = current_identity(session)
    context["auth_logged_in"] = identity is not None
    context["auth_user_email"] = None
    context["auth_user_role"] = session.get("auth_user_role")

    try:
        context["auth_login_url"] = url_for("auth.login")
    except BuildError:
        context["auth_login_url"] = None

    try:
        context["auth_logout_url"] = url_for("auth.logout")
    except BuildError:
        context["auth_logout_url"] = None

    if identity is None:
        return context

    db = current_app.extensions.get("saas_db")
    if db is None or not getattr(db, "is_ready", False):
        return context

    from app.models import User

    db_session = db.session()
    try:
        user = db_session.query(User).filter(User.id == identity.user_id).one_or_none()
        if user is not None:
            context["auth_user_email"] = user.email
            if not context["auth_user_role"]:
                context["auth_user_role"] = "admin" if user.is_admin else "customer"
    finally:
        db_session.close()

    return context


ROLE_END_USER = "end-user"
ROLE_OPERATOR = "operator"
SESSION_ROLE_KEY = "dashboard_role"
ENV_FILE_NAME = ".env"


def _required_setup_keys() -> tuple[str, ...]:
    provider = normalize_provider(current_app.config.get("WHATSAPP_PROVIDER"))
    return get_required_config_keys(provider)


def _is_setup_complete() -> bool:
    return all(is_config_value_set(current_app.config.get(key)) for key in _required_setup_keys())


def _set_dashboard_role(role: str) -> None:
    session[SESSION_ROLE_KEY] = ROLE_OPERATOR if role == ROLE_OPERATOR else ROLE_END_USER


def _current_dashboard_role() -> str:
    if not has_request_context():
        return ROLE_END_USER

    role = str(session.get(SESSION_ROLE_KEY, ROLE_END_USER)).strip().lower()
    if role == ROLE_OPERATOR:
        return ROLE_OPERATOR
    return ROLE_END_USER


def _get_safe_redirect_target(target: str | None) -> str | None:
    candidate = (target or "").strip()
    if not candidate:
        return None

    parts = urlsplit(candidate)
    if parts.scheme or parts.netloc:
        return None
    if not candidate.startswith("/"):
        return None
    if candidate.startswith("//"):
        return None
    return candidate


def _redirect_to_dashboard(endpoint: str, next_target: str | None = None):
    safe_target = _get_safe_redirect_target(next_target)
    return redirect(safe_target or url_for(endpoint))


def _operator_guard_response():
    next_target = _get_safe_redirect_target(request.full_path.rstrip("?"))
    access_url = url_for("dashboard.operator_access", next=next_target or request.path)

    if request.method == "GET":
        return redirect(access_url)

    return (
        jsonify(
            {
                "ok": False,
                "message": "Operator access required.",
                "redirect_to": access_url,
            }
        ),
        403,
    )


def _require_operator_access():
    if _current_dashboard_role() != ROLE_OPERATOR:
        return _operator_guard_response()
    return None


def _setup_items() -> list[dict[str, Any]]:
    return [
        {"key": key, "present": is_config_value_set(current_app.config.get(key))}
        for key in _required_setup_keys()
    ]


def _setup_missing_keys() -> list[str]:
    return [item["key"] for item in _setup_items() if not item["present"]]


def _build_setup_guidance(setup_status: dict[str, Any]) -> dict[str, Any]:
    readiness = setup_status.get("config_readiness") or []
    total_required = len(readiness)
    missing_keys = list(setup_status.get("missing_keys") or [])
    configured = max(0, total_required - len(missing_keys))

    next_steps: list[str] = []
    for key in missing_keys:
        next_steps.append(f"Set {key} in your environment before verification.")

    for error in setup_status.get("validation_errors") or []:
        if error.startswith("Missing required configuration:"):
            continue
        next_steps.append(error)

    if not next_steps:
        next_steps.append("All required configuration is ready. Send a test ping to verify webhook access.")

    return {
        "summary": {
            "configured": configured,
            "total_required": total_required,
            "missing": len(missing_keys),
        },
        "next_steps": next_steps,
    }


def _is_setup_verified() -> bool:
    return bool(session.get(_SETUP_VERIFIED_SESSION_KEY, False))


def _setup_current_step(setup_items: list[dict[str, Any]], complete: bool) -> int:
    present_count = sum(1 for item in setup_items if item["present"])
    total_count = len(setup_items)

    if total_count == 0:
        return 5
    if present_count == 0:
        return 1
    if not complete:
        if present_count >= max(2, total_count - 1):
            return 3
        return 2

    if _is_setup_verified():
        return 5
    return 4


def _webhook_url() -> str:
    try:
        webhook_path = url_for("webhook.webhook_post")
    except BuildError:
        webhook_path = "/webhook"
    return f"{request.url_root.rstrip('/')}" + webhook_path


def _env_file_path() -> Path:
    return Path(current_app.root_path).parent / ENV_FILE_NAME


def _env_lock_path(env_path: Path) -> Path:
    return env_path.with_suffix(env_path.suffix + ".lock")


class _EnvFileLock:
    def __init__(self, env_path: Path, timeout_seconds: float = 5.0) -> None:
        self._lock_path = _env_lock_path(env_path)
        self._timeout_seconds = max(0.1, float(timeout_seconds))
        self._fd: int | None = None

    def __enter__(self):
        deadline = time.monotonic() + self._timeout_seconds
        while True:
            try:
                self._fd = os.open(str(self._lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
                return self
            except FileExistsError as exc:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Timed out acquiring .env write lock") from exc
                time.sleep(0.05)

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        try:
            self._lock_path.unlink()
        except FileNotFoundError:
            pass


def _set_env_value(key: str, value: str) -> None:
    with _ENV_LOCK:
        env_path = _env_file_path()
        env_path.parent.mkdir(parents=True, exist_ok=True)
        with _EnvFileLock(env_path):
            sanitized = value.replace("\\", "\\\\").replace('"', '\\"')
            replacement = f'{key}="{sanitized}"'

            lines: list[str] = []
            found = False
            old_value = None
            if env_path.exists():
                lines = env_path.read_text(encoding="utf-8").splitlines()
                for index, raw in enumerate(lines):
                    if raw.strip().startswith(f"{key}="):
                        # Extract old value for audit trail
                        old_value = raw.split("=", 1)[1].strip('"').replace('\\"', '"').replace("\\\\", "\\") if len(raw.split("=", 1)) > 1 else None
                        lines[index] = replacement
                        found = True
                        break

            if not found:
                if lines and lines[-1].strip():
                    lines.append("")
                lines.append(replacement)

            # Create backup before writing
            try:
                backup_config_file(env_path, "env")
            except (OSError, TimeoutError):
                pass  # Continue with write even if backup fails

            temp_path = env_path.with_suffix(env_path.suffix + ".tmp")
            temp_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            os.replace(temp_path, env_path)
            
            # Record change in audit log
            record_config_change(
                config_file=".env",
                key=key,
                old_value=old_value,
                new_value=value,
                operator_role=_current_dashboard_role(),
            )


def _selected_agent_context() -> tuple[list[dict[str, str]], str | None]:
    agents = list_bmad_agents()
    selected_agent_code = get_selected_agent_code()
    allowed_codes = {agent["code"] for agent in agents}

    if agents and selected_agent_code not in allowed_codes:
        selected_agent_code = agents[0]["code"]
        set_selected_agent_code(selected_agent_code)

    return agents, selected_agent_code


def _format_uptime(seconds: int) -> str:
    hours, rem = divmod(max(0, int(seconds)), 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _masked_number(value: str | None) -> str:
    number = (value or "").strip()
    if len(number) <= 4:
        return number
    return f"{number[:3]}...{number[-4:]}"


def _normalize_user_id(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def _build_operator_escalation_context() -> dict[str, Any]:
    entries = get_message_log_buffer(current_app).get_all()
    flagged = [row for row in entries if bool(row.get("operator_review_flagged"))]
    latest = flagged[0] if flagged else None

    return {
        "has_stop_signal": bool(flagged),
        "pending_reviews": len(flagged),
        "latest_reason": (latest or {}).get("operator_review_reason") or None,
        "latest_timestamp": (latest or {}).get("timestamp") or None,
        "operator_action": "Review flagged conversations in Message Log.",
    }


def _dashboard_runtime_context() -> dict[str, Any]:
    metrics = get_metrics_collector(current_app).snapshot()
    health = get_bot_health(current_app)
    logs = get_message_log_buffer(current_app).get_all()[:5]
    agents, selected_code = _selected_agent_context()
    active_agent_name = "Unknown"
    for item in agents:
        if item["code"] == selected_code:
            active_agent_name = item.get("name") or item["code"]
            break

    def _resolve_connect_url(config_key: str) -> tuple[str, bool]:
        raw = str(current_app.config.get(config_key) or "").strip()
        if raw:
            parsed = urlsplit(raw)
            if parsed.scheme in {"http", "https"} and parsed.netloc:
                return raw, True
        return url_for("dashboard.operator_access", next=url_for("dashboard.setup")), False

    instagram_url, instagram_external = _resolve_connect_url("INSTAGRAM_CONNECT_URL")
    messenger_url, messenger_external = _resolve_connect_url("MESSENGER_CONNECT_URL")
    tiktok_url, tiktok_external = _resolve_connect_url("TIKTOK_CONNECT_URL")

    return {
        "metrics": metrics,
        "health": health,
        "uptime_label": _format_uptime(int(health.get("uptime_seconds", 0))),
        "recent_logs": logs,
        "active_agent_name": active_agent_name,
        "customer_connect_actions": [
            {
                "label": "Instagram",
                "url": instagram_url,
                "external": instagram_external,
                "configured": bool(current_app.config.get("INSTAGRAM_CONNECT_URL")),
            },
            {
                "label": "Facebook Messenger",
                "url": messenger_url,
                "external": messenger_external,
                "configured": bool(current_app.config.get("MESSENGER_CONNECT_URL")),
            },
            {
                "label": "TikTok",
                "url": tiktok_url,
                "external": tiktok_external,
                "configured": bool(current_app.config.get("TIKTOK_CONNECT_URL")),
            },
        ],
    }


@dashboard_blueprint.route("/operator/access", methods=["GET"])
def operator_access():
    _set_dashboard_role(ROLE_OPERATOR)
    default_endpoint = "dashboard.setup" if not _is_setup_complete() else "dashboard.operator_dashboard"
    return _redirect_to_dashboard(default_endpoint, request.args.get("next"))


@dashboard_blueprint.route("/operator/leave", methods=["GET"])
def operator_leave():
    _set_dashboard_role(ROLE_END_USER)
    return _redirect_to_dashboard("dashboard.dashboard_home", request.args.get("next"))


@dashboard_blueprint.route("/", methods=["GET"])
def dashboard_home():
    _set_dashboard_role(ROLE_END_USER)
    context = _dashboard_runtime_context()

    return render_template(
        "dashboard_user.html",
        page_key="end-user",
        nav_mode="user",
        setup_complete=_is_setup_complete(),
        **context,
    )


@dashboard_blueprint.route("/operator", methods=["GET"])
def operator_dashboard():
    guarded = _require_operator_access()
    if guarded is not None:
        return guarded

    if not _is_setup_complete():
        return redirect(url_for("dashboard.setup"))

    context = _dashboard_runtime_context()

    return render_template(
        "dashboard.html",
        page_key="dashboard",
        nav_mode="operator",
        setup_complete=True,
        escalation=_build_operator_escalation_context(),
        **context,
    )


@dashboard_blueprint.route("/setup", methods=["GET"])
def setup():
    guarded = _require_operator_access()
    if guarded is not None:
        return guarded

    setup_items = _setup_items()
    complete = all(item["present"] for item in setup_items)
    if not complete:
        session.pop(_SETUP_VERIFIED_SESSION_KEY, None)

    return render_template(
        "setup.html",
        page_key="setup",
        nav_mode="operator",
        setup_items=setup_items,
        setup_complete=complete,
        setup_current_step=_setup_current_step(setup_items, complete),
        verify_success=False,
        setup_missing_keys=_setup_missing_keys(),
        setup_status_url=url_for("dashboard.setup_status_legacy_api"),
        webhook_url=_webhook_url(),
    )


@dashboard_blueprint.route("/setup/verify", methods=["POST"])
def setup_verify():
    guarded = _require_operator_access()
    if guarded is not None:
        return guarded

    if not _validate_csrf_token():
        return jsonify({"ok": False, "message": "Invalid request token."}), 403

    validation_errors = refresh_config_validation_errors(current_app)
    missing = _setup_missing_keys()
    if validation_errors or missing:
        session.pop(_SETUP_VERIFIED_SESSION_KEY, None)
        return (
            jsonify(
                {
                    "ok": False,
                    "message": "Configuration is not ready. Resolve the listed items and try again.",
                    "missing": missing,
                    "validation_errors": validation_errors,
                }
            ),
            400,
        )

    session[_SETUP_VERIFIED_SESSION_KEY] = True
    return jsonify({"ok": True, "message": "Verification check marked complete."}), 200


@dashboard_blueprint.route("/setup/openai-key", methods=["POST"])
def setup_save_openai_key():
    guarded = _require_operator_access()
    if guarded is not None:
        return guarded

    if not _validate_csrf_token():
        return jsonify({"ok": False, "message": "Invalid request token."}), 403

    raw_key = str(request.form.get("openai_api_key", "")).strip()
    if not raw_key:
        return jsonify({"ok": False, "message": "OpenAI API key cannot be empty."}), 400

    if "\n" in raw_key or "\r" in raw_key:
        return jsonify({"ok": False, "message": "OpenAI API key must be a single line."}), 400

    try:
        _set_env_value("OPENAI_API_KEY", raw_key)
    except (OSError, TimeoutError):
        return jsonify({"ok": False, "message": "Could not save key to .env."}), 500

    current_app.config["OPENAI_API_KEY"] = raw_key
    refresh_config_validation_errors(current_app)
    session.pop(_SETUP_VERIFIED_SESSION_KEY, None)
    try:
        from app.services.openai_service import refresh_openai_client

        refresh_openai_client(raw_key)
    except Exception:
        return jsonify({"ok": False, "message": "OPENAI_API_KEY saved, but the live client could not be refreshed."}), 500

    return jsonify({"ok": True, "message": "OPENAI_API_KEY saved and applied."})


@dashboard_blueprint.route("/agents", methods=["GET"])
def agents_page():
    guarded = _require_operator_access()
    if guarded is not None:
        return guarded

    agents, selected_agent_code = _selected_agent_context()
    return render_template(
        "agents-enhanced.html",
        page_key="agents",
        nav_mode="operator",
        setup_complete=_is_setup_complete(),
        agents=agents,
        selected_agent_code=selected_agent_code,
    )


@dashboard_blueprint.route("/agents", methods=["POST"])
def set_agent_selection():
    guarded = _require_operator_access()
    if guarded is not None:
        return guarded

    if not _validate_csrf_token():
        return jsonify({"ok": False, "message": "Invalid request token."}), 403

    agents = list_bmad_agents()
    allowed_codes = {agent["code"] for agent in agents}

    selected_code = request.form.get("agent_code", "").strip()
    if selected_code and selected_code in allowed_codes:
        old_code = get_selected_agent_code()
        try:
            set_selected_agent_code(selected_code)
        except OSError:
            return jsonify({"ok": False, "message": "Could not save - check file permissions on data/"}), 500

        # Record change in audit log
        record_config_change(
            config_file="agent_selection.json",
            key="selected_agent_code",
            old_value=old_code,
            new_value=selected_code,
            operator_role=_current_dashboard_role(),
        )

        selected_name = next(
            (agent.get("name") or agent["code"] for agent in agents if agent["code"] == selected_code),
            selected_code,
        )
        return jsonify({"ok": True, "message": f"Agent switched to {selected_name}"})

    return jsonify({"ok": False, "message": "Invalid agent selection"}), 400


@dashboard_blueprint.route("/operator/metrics", methods=["GET"])
def metrics_page():
    guarded = _require_operator_access()
    if guarded is not None:
        return guarded

    snapshot = get_metrics_collector(current_app).snapshot()
    averages = snapshot.get("durations", {}).get("averages", {})
    max_avg = max(averages.values(), default=0.0)

    bars = []
    for name, value in sorted(averages.items()):
        ratio = 0 if max_avg == 0 else int((value / max_avg) * 100)
        bars.append({"name": name, "value": value, "ratio": ratio})

    return render_template(
        "metrics.html",
        page_key="metrics",
        nav_mode="operator",
        setup_complete=_is_setup_complete(),
        snapshot=snapshot,
        duration_bars=bars,
        refreshed_at=datetime.now(timezone.utc),
    )


@dashboard_blueprint.route("/logs", methods=["GET"])
def logs_page():
    guarded = _require_operator_access()
    if guarded is not None:
        return guarded

    status_filter = request.args.get("status", "all").strip().lower()
    entries = get_message_log_buffer(current_app).get_all()

    if status_filter in {"sent", "error"}:
        entries = [item for item in entries if item.get("status") == status_filter]

    for entry in entries:
        entry["masked_from"] = _masked_number(entry.get("from"))
        # Remove raw phone number from template to prevent it appearing in HTML source
        entry.pop("from", None)

    return render_template(
        "logs.html",
        page_key="logs",
        nav_mode="operator",
        setup_complete=_is_setup_complete(),
        entries=entries,
        status_filter=status_filter,
    )


@dashboard_blueprint.route("/api/metrics", methods=["GET"])
def metrics_api():
    return jsonify(get_metrics_collector(current_app).snapshot()), 200


def _setup_status_payload_response():
    refresh_config_validation_errors(current_app)
    setup_status = get_setup_status(current_app)
    guidance = _build_setup_guidance(setup_status)
    return jsonify({
        "ok": True,
        **setup_status,
        **guidance,
    }), 200


@dashboard_blueprint.route("/api/setup/status", methods=["GET"])
def setup_status_api():
    """Operator endpoint to check setup status and configuration validation."""
    guarded = _require_operator_access()
    if guarded is not None:
        return guarded
    return _setup_status_payload_response()


@dashboard_blueprint.route("/setup-status", methods=["GET"])
def setup_status_legacy_api():
    """Backwards-compatible setup status endpoint retained for older contracts."""
    guarded = _require_operator_access()
    if guarded is not None:
        return guarded
    return _setup_status_payload_response()


@dashboard_blueprint.route("/api/health", methods=["GET"])
def health_api():
    return jsonify(get_bot_health(current_app)), 200


@dashboard_blueprint.route("/api/logs", methods=["GET"])
def logs_api():
    entries = get_message_log_buffer(current_app).get_all()
    payload = []
    for item in entries:
        row = dict(item)
        row["masked_from"] = _masked_number(row.get("from"))
        payload.append(row)
    return jsonify(payload), 200


@dashboard_blueprint.route("/api/thread-inspector", methods=["GET"])
def thread_inspector_api():
    guarded = _require_operator_access()
    if guarded is not None:
        return guarded

    raw_user_id = request.args.get("user_id", "")
    normalized_user_id = _normalize_user_id(raw_user_id)
    if not normalized_user_id:
        return jsonify({"ok": False, "message": "user_id is required."}), 400

    context_store = get_conversation_context_store(current_app)
    context_rows: list[dict[str, Any]] = []
    for item in context_store.get_context(normalized_user_id):
        context_rows.append(
            {
                "role": item.get("role"),
                "timestamp": item.get("timestamp"),
                "text": sanitize_text(str(item.get("text", ""))),
            }
        )

    recent_activity: list[dict[str, Any]] = []
    for item in get_message_log_buffer(current_app).get_all():
        if _normalize_user_id(item.get("from")) != normalized_user_id:
            continue
        row = dict(item)
        row["from_masked"] = _masked_number(row.get("from"))
        row["preview"] = sanitize_text(str(row.get("preview", "")))
        row.pop("from", None)
        recent_activity.append(row)
        if len(recent_activity) >= 10:
            break

    return jsonify(
        {
            "ok": True,
            "thread": {
                "user_id_masked": _masked_number(normalized_user_id),
                "conversation_context": context_rows,
                "recent_activity": recent_activity,
            },
        }
    ), 200


@dashboard_blueprint.route("/api/analytics/events", methods=["GET"])
def analytics_events_api():
    limit = request.args.get("limit", "50")
    try:
        parsed_limit = max(1, min(500, int(limit)))
    except ValueError:
        parsed_limit = 50

    events = get_recent_analytics_events(current_app, parsed_limit)
    return jsonify({
        "events": events,
        "summary": summarize_recent_events(events),
    }), 200


@dashboard_blueprint.route("/api/analytics/summary", methods=["GET"])
def analytics_summary_api():
    guarded = _require_operator_access()
    if guarded is not None:
        return guarded

    summary = get_analytics_summary(current_app)
    return jsonify({
        "ok": True,
        **summary,
    }), 200


# Configuration audit and recovery endpoints
@dashboard_blueprint.route("/api/config/audit-log", methods=["GET"])
def config_audit_log_api():
    """Retrieve configuration change audit log."""
    guarded = _require_operator_access()
    if guarded is not None:
        return guarded

    config_file = request.args.get("config_file")
    limit = request.args.get("limit", "100")
    try:
        parsed_limit = max(1, min(1000, int(limit)))
    except ValueError:
        parsed_limit = 100

    changes = get_config_change_history(config_file, limit=parsed_limit)
    return jsonify({
        "ok": True,
        "total": len(changes),
        "changes": changes,
    }), 200


@dashboard_blueprint.route("/api/config/backups", methods=["GET"])
def config_backups_list_api():
    """List available configuration backups."""
    guarded = _require_operator_access()
    if guarded is not None:
        return guarded

    config_name = request.args.get("config_name", "env")
    backups = list_available_backups(config_name)
    return jsonify({
        "ok": True,
        "config_name": config_name,
        "backups": backups,
    }), 200


@dashboard_blueprint.route("/api/config/restore", methods=["POST"])
def config_restore_api():
    """Restore configuration from backup."""
    guarded = _require_operator_access()
    if guarded is not None:
        return guarded

    if not _validate_csrf_token():
        return jsonify({"ok": False, "message": "Invalid request token."}), 403

    config_name = request.form.get("config_name", "").strip()
    backup_filename = request.form.get("backup_filename", "").strip()

    if not config_name or not backup_filename:
        return jsonify({"ok": False, "message": "config_name and backup_filename are required."}), 400

    try:
        if config_name == "env":
            target_path = _env_file_path()
        elif config_name == "agent_selection":
            from app.services.agent_registry import SELECTION_FILE
            target_path = SELECTION_FILE
        else:
            return jsonify({"ok": False, "message": "Unknown configuration."}), 400

        restore_config_from_backup(config_name, backup_filename, target_path)

        # Record the restore action in audit log
        record_config_change(
            config_file=f"{config_name}.backup",
            key="restore_action",
            old_value=backup_filename,
            new_value=backup_filename,
            operator_role=_current_dashboard_role(),
        )

        return jsonify({
            "ok": True,
            "message": f"Successfully restored {config_name} from {backup_filename}",
        }), 200

    except FileNotFoundError:
        return jsonify({"ok": False, "message": f"Backup file not found: {backup_filename}"}), 404
    except (ValueError, OSError) as exc:
        return jsonify({"ok": False, "message": f"Restore failed: {str(exc)}"}), 500

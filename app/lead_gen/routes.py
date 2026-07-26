"""Operator routes for Scout-powered lead generation."""

from __future__ import annotations

import hmac

from flask import (
    Blueprint,
    Response,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from app.services.auth_service import current_identity
from app.services.lead_gen import (
    LeadGenValidationError,
    UnsupportedPlatformError,
    export_leads_csv,
    list_leads,
    list_platforms,
    scrape_and_store,
)
from app.views_dashboard import ROLE_OPERATOR, SESSION_ROLE_KEY

lead_gen_blueprint = Blueprint("lead_gen", __name__)
_CSRF_SESSION_KEY = "_csrf_token"


def _require_operator_page():
    if current_identity(session) is None:
        return redirect(url_for("auth.login"))
    if session.get(SESSION_ROLE_KEY) != ROLE_OPERATOR:
        return redirect(url_for("dashboard.dashboard_home"))
    return None


def _require_operator_api():
    if current_identity(session) is None:
        return jsonify({"ok": False, "message": "Authentication required."}), 401
    if session.get(SESSION_ROLE_KEY) != ROLE_OPERATOR:
        return jsonify({"ok": False, "message": "Operator access required."}), 403
    return None


def _validate_csrf_token() -> bool:
    token = session.get(_CSRF_SESSION_KEY)
    if not token:
        return False
    submitted = request.headers.get("X-CSRFToken") or request.form.get("csrf_token", "")
    return hmac.compare_digest(str(token), str(submitted))


def _db_or_503():
    db = current_app.extensions.get("saas_db")
    if db is None or not getattr(db, "is_ready", False):
        return None, (jsonify({"ok": False, "message": "SaaS database is not configured."}), 503)
    return db, None


def _request_json_or_form() -> dict:
    if request.is_json:
        return request.get_json(silent=True) or {}
    return request.form.to_dict(flat=True)


def _as_bool(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


@lead_gen_blueprint.get("/leads")
def leads_page():
    guarded = _require_operator_page()
    if guarded is not None:
        return guarded

    return render_template(
        "leads.html",
        page_key="leads",
        nav_mode="operator",
        platforms=list_platforms(),
        max_usernames=10,
    )


@lead_gen_blueprint.get("/api/leads/platforms")
def leads_platforms_api():
    guarded = _require_operator_api()
    if guarded is not None:
        return guarded
    return jsonify({"ok": True, "platforms": list_platforms()})


@lead_gen_blueprint.get("/api/leads")
def leads_list_api():
    guarded = _require_operator_api()
    if guarded is not None:
        return guarded

    identity = current_identity(session)
    db, error = _db_or_503()
    if error is not None:
        return error

    platform = str(request.args.get("platform") or "").strip() or None
    has_email_raw = request.args.get("has_email")
    has_email = None
    if has_email_raw is not None and str(has_email_raw).strip() != "":
        has_email = _as_bool(has_email_raw)

    try:
        page = int(request.args.get("page", "1"))
        per_page = int(request.args.get("per_page", "25"))
    except ValueError:
        return jsonify({"ok": False, "message": "page and per_page must be integers."}), 400

    try:
        payload = list_leads(
            db,
            identity.tenant_id,
            platform=platform,
            has_email=has_email,
            page=page,
            per_page=per_page,
        )
    except LeadGenValidationError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400

    return jsonify({"ok": True, **payload})


@lead_gen_blueprint.post("/api/leads/scrape")
def leads_scrape_api():
    guarded = _require_operator_api()
    if guarded is not None:
        return guarded
    if not _validate_csrf_token():
        return jsonify({"ok": False, "message": "CSRF validation failed."}), 400

    identity = current_identity(session)
    db, error = _db_or_503()
    if error is not None:
        return error

    body = _request_json_or_form()
    platform = str(body.get("platform") or "").strip()
    usernames = body.get("usernames")
    if isinstance(usernames, str):
        username_input = usernames
    elif isinstance(usernames, list):
        username_input = usernames
    else:
        username_input = str(body.get("usernames_text") or "")

    enrich = _as_bool(body.get("enrich"), default=True)

    try:
        result = scrape_and_store(
            db,
            identity.tenant_id,
            platform,
            username_input,
            enrich=enrich,
            app=current_app,
        )
    except UnsupportedPlatformError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400
    except LeadGenValidationError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        current_app.logger.exception("LEAD_GEN_SCRAPE_API_FAILED")
        return jsonify({"ok": False, "message": f"Scrape failed: {exc}"}), 500

    return jsonify({"ok": True, **result})


@lead_gen_blueprint.get("/api/leads/export.csv")
def leads_export_csv():
    guarded = _require_operator_api()
    if guarded is not None:
        return guarded

    identity = current_identity(session)
    db, error = _db_or_503()
    if error is not None:
        return error

    platform = str(request.args.get("platform") or "").strip() or None
    has_email_raw = request.args.get("has_email")
    has_email = None
    if has_email_raw is not None and str(has_email_raw).strip() != "":
        has_email = _as_bool(has_email_raw)

    csv_text = export_leads_csv(
        db,
        identity.tenant_id,
        platform=platform,
        has_email=has_email,
    )
    filename = "leads_export.csv"
    if platform:
        filename = f"leads_{platform}_export.csv"

    return Response(
        csv_text,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

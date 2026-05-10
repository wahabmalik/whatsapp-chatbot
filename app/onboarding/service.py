"""Onboarding service for tenant QR code and connection state management.

This module handles:
- Entitlement validation against billing service
- Evolution API integration for instance creation and QR code fetching
- Connection state synchronization with resilient polling
- Preparation of connection data for inbound routing (Story 3.2)
"""

from __future__ import annotations

import base64
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests

from app.models import ConnectionState

logger = logging.getLogger(__name__)


class OnboardingError(Exception):
    """Base onboarding error."""


class NoActiveSubscriptionError(OnboardingError):
    """Raised when tenant is not entitled for onboarding."""


class EvolutionUnavailableError(OnboardingError):
    """Raised when Evolution API is unavailable or response is malformed."""


class EvolutionResponseValidationError(EvolutionUnavailableError):
    """Raised when Evolution API response fails validation."""


class EvolutionAlreadyConnected(OnboardingError):
    """Raised when instance is already connected and no QR is required."""

    def __init__(self, phone: str | None = None) -> None:
        super().__init__("Evolution instance is already connected")
        self.phone = phone


@dataclass(frozen=True)
class QrCodeResult:
    """QR code result for onboarding UI consumption."""

    qr_image: str
    expires_in_seconds: int
    instance_name: str
    already_connected: bool = False
    phone: str | None = None


@dataclass(frozen=True)
class ConnectionSnapshot:
    """Current connection state snapshot from Evolution API."""

    status: str  # one of: 'disconnected', 'connecting', 'connected'
    phone: str | None = None


def _utcnow() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


def _normalize_status(raw: str | None) -> str:
    """Normalize Evolution status to canonical values.

    Canonical statuses: 'disconnected', 'connecting', 'connected'
    """
    value = str(raw or "").strip().lower()
    if value in {"open", "connected", "online", "ready"}:
        return "connected"
    if value in {"connecting", "qr", "qrcode", "pending", "in_progress"}:
        return "connecting"
    if value in {"close", "closed", "disconnected", "offline"}:
        return "disconnected"
    return "connecting"


def _phone_from_payload(payload: Any) -> str | None:
    """Extract phone number from Evolution API payload."""
    if isinstance(payload, dict):
        for key in ("phone", "phoneNumber", "number", "wuid", "wid"):
            value = payload.get(key)
            if value:
                return str(value)
        for nested_key in ("instance", "connection", "state"):
            nested = payload.get(nested_key)
            found = _phone_from_payload(nested)
            if found:
                return found
    return None


def _status_from_payload(payload: Any) -> str | None:
    """Extract connection status string from Evolution payload."""
    if isinstance(payload, dict):
        for key in ("connectionStatus", "status", "state", "instanceState"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value

        for nested_key in ("instance", "connection", "data", "result"):
            nested = payload.get(nested_key)
            found = _status_from_payload(nested)
            if found:
                return found

    if isinstance(payload, list):
        for item in payload:
            found = _status_from_payload(item)
            if found:
                return found

    return None


def _extract_qr_image(payload: Any) -> str | None:
    """Extract QR image (base64 or data URI) from Evolution API payload."""
    if isinstance(payload, dict):
        direct = payload.get("qr_image") or payload.get("base64") or payload.get("qrcode") or payload.get("qr")
        if isinstance(direct, str) and direct.strip():
            return direct.strip()
        for nested_key in ("qrcode", "qr", "base64", "data", "instance"):
            nested = payload.get(nested_key)
            nested_value = _extract_qr_image(nested)
            if nested_value:
                return nested_value
    elif isinstance(payload, str) and payload.strip():
        return payload.strip()
    return None


def _ensure_data_uri(candidate: str) -> str:
    """Convert base64 string to data URI if needed."""
    qr = candidate.strip()
    if qr.startswith("data:image"):
        return qr

    compact = re.sub(r"\s+", "", qr)
    try:
        base64.b64decode(compact, validate=True)
        return f"data:image/png;base64,{compact}"
    except Exception:  # noqa: BLE001
        logger.warning("Failed to validate base64 in QR candidate; returning as-is")
        return qr


def _extract_expires_seconds(payload: Any, default_seconds: int = 60) -> int:
    """Extract TTL/expiration seconds from Evolution API payload."""
    keys = (
        "expires_in_seconds",
        "expiresIn",
        "expires",
        "countdown",
        "ttl",
    )
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if value is None:
                continue
            try:
                parsed = int(value)
                if parsed > 0:
                    return parsed
            except Exception:  # noqa: BLE001
                continue
        for nested_key in ("qrcode", "qr", "data", "instance"):
            nested = payload.get(nested_key)
            nested_value = _extract_expires_seconds(nested, default_seconds=default_seconds)
            if nested_value != default_seconds:
                return nested_value
    return default_seconds


def _validate_response_json(response: requests.Response, context: str) -> dict:
    """Validate and parse JSON response from Evolution API.

    Raises:
        EvolutionResponseValidationError: If response is malformed or invalid.
    """
    if not response.content:
        return {}

    try:
        return response.json()
    except ValueError as exc:
        msg = f"Evolution {context}: invalid JSON response"
        logger.error(msg, extra={"status_code": response.status_code, "content": response.text[:200]})
        raise EvolutionResponseValidationError(msg) from exc


def _headers(api_key: str) -> dict[str, str]:
    """Build headers for Evolution API requests."""
    return {"apikey": api_key, "Content-Type": "application/json"}


def _api_base(app) -> str:
    """Get Evolution API base URL from config."""
    base = str(app.config.get("EVOLUTION_API_URL", "")).strip().rstrip("/")
    if not base:
        raise EvolutionUnavailableError("EVOLUTION_API_URL is not configured")
    return base


def _api_key(app) -> str:
    """Get Evolution API key from config."""
    key = str(app.config.get("EVOLUTION_API_KEY", "")).strip()
    if not key:
        raise EvolutionUnavailableError("EVOLUTION_API_KEY is not configured")
    return key


def _instance_name_for_tenant(tenant_id: str) -> str:
    """Generate Evolution instance name scoped to tenant."""
    compact = re.sub(r"[^a-zA-Z0-9]", "", tenant_id or "")
    if not compact:
        compact = "tenant"
    return f"tenant-{compact[:24]}"


def _configured_instance_name(app) -> str | None:
    """Return configured shared Evolution instance name when provided."""
    value = str(app.config.get("EVOLUTION_INSTANCE_NAME", "")).strip()
    return value or None


def _instance_mode(app) -> str:
    """Resolve onboarding instance strategy: auto, shared, or tenant."""
    raw = str(app.config.get("ONBOARDING_INSTANCE_MODE", "auto")).strip().lower()
    if raw in {"auto", "shared", "tenant"}:
        return raw
    return "auto"


def _resolve_instance_name(app, fallback_tenant_instance: str) -> tuple[str, bool]:
    """Pick instance name and whether shared-instance behavior should be enabled."""
    configured = _configured_instance_name(app)
    mode = _instance_mode(app)

    if mode == "shared":
        if configured:
            return configured, True
        return fallback_tenant_instance, False

    if mode == "tenant":
        return fallback_tenant_instance, False

    # auto: prefer configured shared instance when present, else tenant instance.
    if configured:
        return configured, True
    return fallback_tenant_instance, False


def _ensure_connection_state(db, tenant_id: str) -> ConnectionState:
    """Ensure ConnectionState row exists and is properly initialized."""
    sess = db.session()
    try:
        row = sess.query(ConnectionState).filter(ConnectionState.tenant_id == tenant_id).one_or_none()
        if row is None:
            row = ConnectionState(
                tenant_id=tenant_id,
                status="disconnected",
                evolution_instance=_instance_name_for_tenant(tenant_id),
            )
            sess.add(row)
            sess.commit()
            sess.refresh(row)
            return row

        changed = False
        if not row.evolution_instance:
            row.evolution_instance = _instance_name_for_tenant(tenant_id)
            changed = True
        if not row.status:
            row.status = "disconnected"
            changed = True

        if changed:
            sess.commit()
            sess.refresh(row)
        return row
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()


def _create_instance_if_missing(app, instance_name: str, *, allow_forbidden_passthrough: bool = False) -> None:
    """Create instance on Evolution API if it doesn't exist (409 = already exists)."""
    base = _api_base(app)
    key = _api_key(app)
    payload = {
        "instanceName": instance_name,
        "qrcode": True,
        "integration": "WHATSAPP-BAILEYS",
    }
    try:
        response = requests.post(
            f"{base}/instance/create",
            json=payload,
            headers=_headers(key),
            timeout=10,
        )
    except requests.Timeout as exc:
        raise EvolutionUnavailableError(f"Evolution instance create timeout") from exc
    except requests.RequestException as exc:
        raise EvolutionUnavailableError(f"Evolution instance create network error") from exc

    if response.status_code in {200, 201, 202, 409}:
        return
    if response.status_code == 403 and allow_forbidden_passthrough:
        # Some deployments lock API keys to pre-provisioned instances and forbid create.
        # In that mode, continue and let connect/status endpoints decide availability.
        logger.info(
            "Evolution instance create forbidden; continuing with pre-provisioned instance",
            extra={"instance_name": instance_name},
        )
        return
    msg = f"Evolution instance create failed: {response.status_code}"
    logger.error(msg, extra={"response_text": response.text[:200]})
    raise EvolutionUnavailableError(msg)


def _fetch_qr_from_evolution(app, instance_name: str) -> tuple[str, int]:
    """Fetch QR code and TTL from Evolution connect endpoint."""
    base = _api_base(app)
    key = _api_key(app)
    try:
        response = requests.get(
            f"{base}/instance/connect/{instance_name}",
            headers=_headers(key),
            timeout=10,
        )
    except requests.Timeout as exc:
        raise EvolutionUnavailableError(f"Evolution QR fetch timeout") from exc
    except requests.RequestException as exc:
        raise EvolutionUnavailableError(f"Evolution QR fetch network error") from exc

    if response.status_code >= 500:
        msg = f"Evolution connect server error: {response.status_code}"
        logger.error(msg, extra={"response_text": response.text[:200]})
        raise EvolutionUnavailableError(msg)
    if response.status_code >= 400:
        msg = f"Evolution connect client error: {response.status_code}"
        logger.error(msg, extra={"response_text": response.text[:200]})
        raise EvolutionUnavailableError(msg)

    payload = _validate_response_json(response, "QR connect")
    qr = _extract_qr_image(payload)
    if not qr:
        status = _normalize_status(_status_from_payload(payload))
        if status == "connected":
            raise EvolutionAlreadyConnected(phone=_phone_from_payload(payload))
        msg = "Evolution QR payload missing qr image"
        logger.error(msg, extra={"payload_keys": list(payload.keys()) if isinstance(payload, dict) else "not-dict"})
        raise EvolutionResponseValidationError(msg)
    return _ensure_data_uri(qr), _extract_expires_seconds(payload)


def _is_entitled(db, tenant_id: str) -> bool:
    """Check if tenant has active subscription or trial."""
    from app.services.billing_service import can_activate_bot

    return bool(can_activate_bot(db, tenant_id))


def get_or_create_qr_code(db, app, tenant_id: str) -> QrCodeResult:
    """Get or create QR code for tenant onboarding.

    Raises:
        NoActiveSubscriptionError: If tenant not entitled.
        EvolutionUnavailableError: If Evolution API is unavailable or fails.
    """
    if not _is_entitled(db, tenant_id):
        logger.warning("Onboarding QR requested for non-entitled tenant", extra={"tenant_id": tenant_id})
        raise NoActiveSubscriptionError("No active subscription")

    connection = _ensure_connection_state(db, tenant_id)
    fallback_tenant_instance = connection.evolution_instance or _instance_name_for_tenant(tenant_id)
    instance_name, shared_mode = _resolve_instance_name(app, fallback_tenant_instance)

    retries = max(1, int(app.config.get("ONBOARDING_QR_MAX_RETRIES", 3)))
    backoff = float(app.config.get("ONBOARDING_QR_BACKOFF_SECONDS", 0.25))

    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            _create_instance_if_missing(
                app,
                instance_name,
                allow_forbidden_passthrough=shared_mode,
            )
            try:
                qr_image, expires_in_seconds = _fetch_qr_from_evolution(app, instance_name)
                already_connected = False
                connected_phone = None
            except EvolutionAlreadyConnected as exc:
                qr_image, expires_in_seconds = "", 0
                already_connected = True
                connected_phone = exc.phone

            sess = db.session()
            try:
                row = sess.query(ConnectionState).filter(ConnectionState.tenant_id == tenant_id).one()
                row.status = "connected" if already_connected else "connecting"
                row.evolution_instance = instance_name
                if connected_phone:
                    row.phone_number = connected_phone
                if already_connected and row.connected_at is None:
                    row.connected_at = _utcnow()
                sess.commit()
            except Exception:
                sess.rollback()
                raise
            finally:
                sess.close()

            logger.info("QR code generated successfully", extra={"tenant_id": tenant_id})
            return QrCodeResult(
                qr_image=qr_image,
                expires_in_seconds=expires_in_seconds,
                instance_name=instance_name,
                already_connected=already_connected,
                phone=connected_phone,
            )
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < retries - 1:
                wait_time = backoff * (2**attempt)
                logger.debug(f"QR fetch attempt {attempt + 1} failed, retrying in {wait_time}s", extra={"error": str(exc)})
                time.sleep(wait_time)
                continue

    msg = str(last_error or "Evolution unavailable")
    logger.error("QR code generation failed after retries", extra={"tenant_id": tenant_id, "error": msg})
    raise EvolutionUnavailableError(msg)


def _fetch_state_via_connection_endpoint(app, instance_name: str) -> ConnectionSnapshot | None:
    """Fetch connection state via connectionState endpoint."""
    base = _api_base(app)
    key = _api_key(app)
    try:
        response = requests.get(
            f"{base}/instance/connectionState/{instance_name}",
            headers=_headers(key),
            timeout=8,
        )
    except requests.Timeout:
        logger.debug("connectionState endpoint timeout")
        return None
    except requests.RequestException:
        logger.debug("connectionState endpoint network error")
        return None

    if response.status_code == 404:
        logger.debug(f"Instance not found on connectionState endpoint: {instance_name}")
        return None
    if response.status_code >= 400:
        logger.warning(f"connectionState endpoint error: {response.status_code}")
        return None

    payload = _validate_response_json(response, "connectionState")
    status = _normalize_status(_status_from_payload(payload))
    phone = _phone_from_payload(payload)
    return ConnectionSnapshot(status=status, phone=phone)


def _fetch_state_via_instances_list(app, instance_name: str) -> ConnectionSnapshot | None:
    """Fetch connection state via fetchInstances endpoint (fallback)."""
    base = _api_base(app)
    key = _api_key(app)
    try:
        response = requests.get(
            f"{base}/instance/fetchInstances",
            headers=_headers(key),
            timeout=8,
        )
    except requests.Timeout:
        logger.debug("fetchInstances endpoint timeout")
        return None
    except requests.RequestException:
        logger.debug("fetchInstances endpoint network error")
        return None

    if response.status_code >= 400:
        logger.warning(f"fetchInstances endpoint error: {response.status_code}")
        return None

    payload = _validate_response_json(response, "fetchInstances")
    rows = payload if isinstance(payload, list) else payload.get("instances") if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        logger.warning("fetchInstances response is not a list or dict with 'instances' key")
        return None

    for row in rows:
        if not isinstance(row, dict):
            continue
        row_name = str(row.get("name") or row.get("instanceName") or "").strip()
        if row_name != instance_name:
            continue
        status = _normalize_status(row.get("connectionStatus") or row.get("status") or row.get("state"))
        return ConnectionSnapshot(status=status, phone=_phone_from_payload(row))
    return None


def sync_connection_status(db, app, tenant_id: str) -> ConnectionSnapshot:
    """Sync connection status from Evolution API to database.

    Story 3.2 will use this to handle webhook-driven transitions.
    """
    connection = _ensure_connection_state(db, tenant_id)
    fallback_tenant_instance = connection.evolution_instance or _instance_name_for_tenant(tenant_id)
    instance_name, _ = _resolve_instance_name(app, fallback_tenant_instance)

    snapshot = _fetch_state_via_connection_endpoint(app, instance_name)
    if snapshot is None:
        snapshot = _fetch_state_via_instances_list(app, instance_name)

    if snapshot is None:
        snapshot = ConnectionSnapshot(status=connection.status or "disconnected", phone=connection.phone_number)

    sess = db.session()
    try:
        row = sess.query(ConnectionState).filter(ConnectionState.tenant_id == tenant_id).one()
        row.status = snapshot.status
        row.evolution_instance = instance_name
        if snapshot.phone:
            row.phone_number = snapshot.phone
        if snapshot.status == "connected" and row.connected_at is None:
            row.connected_at = _utcnow()
        if snapshot.status != "connected":
            row.connected_at = None
        sess.commit()
        logger.debug(f"Connection status synced: {snapshot.status}", extra={"tenant_id": tenant_id})
    except Exception:
        sess.rollback()
        logger.error("Failed to sync connection status", extra={"tenant_id": tenant_id})
        raise
    finally:
        sess.close()

    return snapshot


# Story 3.2 Integration Point: Webhook-driven connection updates
# ================================================================
# Story 3.2 will introduce webhook handlers that call the methods below
# to transition connection state when Evolution sends webhook events.


def mark_connected(db, tenant_id: str, phone_number: str | None = None) -> ConnectionSnapshot:
    """Mark tenant as connected (for Story 3.2 webhook handler).

    Called when Evolution webhook indicates device is connected.
    """
    sess = db.session()
    try:
        row = sess.query(ConnectionState).filter(ConnectionState.tenant_id == tenant_id).one_or_none()
        if row is None:
            row = ConnectionState(
                tenant_id=tenant_id,
                status="connected",
                phone_number=phone_number,
                connected_at=_utcnow(),
                evolution_instance=_instance_name_for_tenant(tenant_id),
            )
            sess.add(row)
        else:
            row.status = "connected"
            row.connected_at = _utcnow()
            if phone_number:
                row.phone_number = phone_number
        sess.commit()
        logger.info("Tenant marked as connected", extra={"tenant_id": tenant_id, "phone": phone_number})
        return ConnectionSnapshot(status="connected", phone=row.phone_number)
    except Exception:
        sess.rollback()
        logger.error("Failed to mark tenant as connected", extra={"tenant_id": tenant_id})
        raise
    finally:
        sess.close()


def mark_disconnected(db, tenant_id: str) -> ConnectionSnapshot:
    """Mark tenant as disconnected (for Story 3.2 webhook handler).

    Called when Evolution webhook indicates device is disconnected.
    """
    sess = db.session()
    try:
        row = sess.query(ConnectionState).filter(ConnectionState.tenant_id == tenant_id).one_or_none()
        if row is None:
            row = ConnectionState(
                tenant_id=tenant_id,
                status="disconnected",
                connected_at=None,
                evolution_instance=_instance_name_for_tenant(tenant_id),
            )
            sess.add(row)
        else:
            row.status = "disconnected"
            row.connected_at = None
        sess.commit()
        logger.info("Tenant marked as disconnected", extra={"tenant_id": tenant_id})
        return ConnectionSnapshot(status="disconnected", phone=row.phone_number)
    except Exception:
        sess.rollback()
        logger.error("Failed to mark tenant as disconnected", extra={"tenant_id": tenant_id})
        raise
    finally:
        sess.close()


def get_connection_state(db, tenant_id: str) -> ConnectionSnapshot | None:
    """Get current connection state (for Story 3.2 routing logic).

    Returns None if no connection state exists.
    """
    sess = db.session()
    try:
        row = sess.query(ConnectionState).filter(ConnectionState.tenant_id == tenant_id).one_or_none()
        if row is None:
            return None
        return ConnectionSnapshot(status=row.status, phone=row.phone_number)
    finally:
        sess.close()


def sse_event(payload: dict[str, Any]) -> str:
    """Format payload as Server-Sent Event (SSE) data line."""
    return f"data: {json.dumps(payload)}\n\n"

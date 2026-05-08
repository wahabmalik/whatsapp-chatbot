"""Onboarding module for SaaS tenant WhatsApp connection flow.

Provides:
- Blueprint: onboarding_blueprint (routes for page, QR, and SSE status)
- Service: Functions for QR generation, status sync, and Story 3.2 webhook handlers
"""

from .routes import onboarding_blueprint
from .service import (
    ConnectionSnapshot,
    EvolutionResponseValidationError,
    EvolutionUnavailableError,
    NoActiveSubscriptionError,
    OnboardingError,
    QrCodeResult,
    get_connection_state,
    get_or_create_qr_code,
    mark_connected,
    mark_disconnected,
    sync_connection_status,
)

__all__ = [
    "onboarding_blueprint",
    "ConnectionSnapshot",
    "EvolutionResponseValidationError",
    "EvolutionUnavailableError",
    "NoActiveSubscriptionError",
    "OnboardingError",
    "QrCodeResult",
    "get_connection_state",
    "get_or_create_qr_code",
    "mark_connected",
    "mark_disconnected",
    "sync_connection_status",
]

"""DEPRECATED: Onboarding service has moved to app.onboarding module.

This file is kept for backward compatibility and re-exports from the new location.
New code should import directly from app.onboarding.

Migration path:
  from app.services.onboarding_service import ...
becomes:
  from app.onboarding import ...
"""

# Re-export all public members for backward compatibility
from app.onboarding.service import (  # noqa: F401
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
    sse_event,
    sync_connection_status,
)

__all__ = [
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
    "sse_event",
    "sync_connection_status",
]


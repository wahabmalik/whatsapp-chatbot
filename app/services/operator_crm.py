"""Closar operator CRM helpers — demo sheet data plus real channel/status probes."""

from __future__ import annotations

from typing import Any, Mapping

from app.services.channel_interface import SUPPORTED_CHANNELS


LEAD_STAGES = ("Discover", "Chat", "Follow-up", "Proposal")
SALE_TYPES = ("Closed sale", "Build what they want")

# Adapters that can be activated via OUTBOUND_CHANNEL today.
PRODUCT_CHANNELS: tuple[dict[str, str], ...] = (
    {"id": "whatsapp", "label": "WhatsApp", "category": "Messaging"},
    {"id": "telegram", "label": "Telegram", "category": "Messaging"},
    {"id": "instagram", "label": "Instagram", "category": "Social"},
    {"id": "messenger", "label": "Messenger", "category": "Social"},
    {"id": "tiktok", "label": "TikTok", "category": "Social"},
)

# Shown in the UI as Coming soon — not active adapters.
COMING_SOON_CHANNELS: tuple[dict[str, str], ...] = (
    {"id": "discord", "label": "Discord", "category": "Workplace"},
    {"id": "slack", "label": "Slack", "category": "Workplace"},
    {"id": "teams", "label": "Microsoft Teams", "category": "Workplace"},
    {"id": "sms", "label": "SMS", "category": "Messaging"},
    {"id": "line", "label": "Line", "category": "Messaging"},
    {"id": "viber", "label": "Viber", "category": "Messaging"},
    {"id": "email", "label": "Email", "category": "Inbox"},
)

# Back-compat alias used by older imports/tests.
CHANNELS = PRODUCT_CHANNELS + COMING_SOON_CHANNELS

_CHANNEL_LABELS = {row["id"]: row["label"] for row in CHANNELS}

_STATUS_LABELS = {
    "active_outbound": "Active outbound",
    "connected": "Configured",
    "not_connected": "Not configured",
    "coming_soon": "Coming soon",
}


def demo_leads() -> list[dict[str, Any]]:
    """Sample pipeline rows for UI preview until live CRM persistence ships."""
    return [
        {
            "updated": "2026-07-25 14:02",
            "name": "Aisha Rahman",
            "contact": "+971 50 112 8890",
            "need": "Shopify store + WhatsApp checkout",
            "channel": "WhatsApp",
            "stage": "Follow-up",
            "messages": 18,
            "last_message": "Can you send a package for 50 SKUs?",
        },
        {
            "updated": "2026-07-25 13:41",
            "name": "Marcus Chen",
            "contact": "@marcusops",
            "need": "Lead bot for Telegram community",
            "channel": "Telegram",
            "stage": "Proposal",
            "messages": 27,
            "last_message": "Proposal looks good — awaiting finance.",
        },
        {
            "updated": "2026-07-25 12:18",
            "name": "Nora Vidal",
            "contact": "nora@atelier.co",
            "need": "Instagram DM qualifier for brand drops",
            "channel": "Instagram",
            "stage": "Chat",
            "messages": 9,
            "last_message": "We get ~200 DMs on drop days.",
        },
        {
            "updated": "2026-07-25 11:05",
            "name": "James Okonkwo",
            "contact": "j.okonkwo@northline.io",
            "need": "Teams intake for enterprise RFPs",
            "channel": "Microsoft Teams",
            "stage": "Discover",
            "messages": 4,
            "last_message": "Who owns procurement on your side?",
        },
        {
            "updated": "2026-07-24 19:22",
            "name": "Sofia Mendes",
            "contact": "+351 91 440 2211",
            "need": "SMS follow-up for abandoned carts",
            "channel": "SMS",
            "stage": "Follow-up",
            "messages": 14,
            "last_message": "Remind me tomorrow after 10am.",
        },
    ]


def demo_sales() -> list[dict[str, Any]]:
    """Sample closed-book rows for UI preview until live CRM persistence ships."""
    return [
        {
            "closed_at": "2026-07-24 16:40",
            "client": "BrightCart UAE",
            "contact": "ops@brightcart.ae",
            "what_they_want": "WhatsApp sales bot + CRM export",
            "channel": "WhatsApp",
            "sale_type": "Closed sale",
            "messages": 42,
            "last_message": "Contract signed — kickoff Monday.",
        },
        {
            "closed_at": "2026-07-23 11:12",
            "client": "Studio Lumen",
            "contact": "@lumen.studio",
            "what_they_want": "Custom TikTok lead qualifier for creators",
            "channel": "TikTok",
            "sale_type": "Build what they want",
            "messages": 31,
            "last_message": "Please scope a creator-facing flow.",
        },
        {
            "closed_at": "2026-07-22 09:55",
            "client": "Harbor Logistics",
            "contact": "amina@harborlog.com",
            "what_they_want": "Slack bot that qualifies inbound freight leads",
            "channel": "Slack",
            "sale_type": "Closed sale",
            "messages": 36,
            "last_message": "Invoice paid. Send onboarding pack.",
        },
    ]


def _config_present(config: Mapping[str, Any], *keys: str) -> bool:
    return all(str(config.get(key) or "").strip() for key in keys)


def channel_is_configured(channel_id: str, config: Mapping[str, Any]) -> bool:
    """Return True when env/config indicates the adapter can send."""
    channel_id = (channel_id or "").strip().lower()
    if channel_id == "whatsapp":
        return _config_present(config, "ACCESS_TOKEN", "PHONE_NUMBER_ID")
    if channel_id == "telegram":
        return _config_present(config, "TELEGRAM_BOT_TOKEN")
    if channel_id == "instagram":
        return _config_present(config, "INSTAGRAM_OUTBOUND_URL", "INSTAGRAM_ACCESS_TOKEN")
    if channel_id == "messenger":
        return _config_present(
            config, "MESSENGER_OUTBOUND_URL", "MESSENGER_PAGE_ACCESS_TOKEN"
        )
    if channel_id == "tiktok":
        return _config_present(config, "TIKTOK_OUTBOUND_URL", "TIKTOK_ACCESS_TOKEN")
    return False


def resolve_channel_action(
    channel_id: str,
    *,
    status: str,
    config: Mapping[str, Any],
    setup_url: str,
    onboarding_url: str,
) -> dict[str, str | bool]:
    """Map channel row status to an honest CTA."""
    channel_id = (channel_id or "").strip().lower()
    if status == "coming_soon":
        return {
            "label": "Coming soon",
            "url": "",
            "enabled": False,
            "external": False,
        }

    if channel_id == "whatsapp":
        return {
            "label": "Configure" if status != "not_connected" else "Connect",
            "url": onboarding_url if status == "not_connected" else setup_url,
            "enabled": True,
            "external": False,
        }

    connect_key = {
        "instagram": "INSTAGRAM_CONNECT_URL",
        "messenger": "MESSENGER_CONNECT_URL",
        "tiktok": "TIKTOK_CONNECT_URL",
    }.get(channel_id)
    if connect_key:
        raw = str(config.get(connect_key) or "").strip()
        if raw.startswith(("http://", "https://")):
            return {
                "label": "Configure" if status != "not_connected" else "Connect",
                "url": raw,
                "enabled": True,
                "external": True,
            }

    return {
        "label": "Configure" if status != "not_connected" else "Configure env",
        "url": setup_url,
        "enabled": True,
        "external": False,
    }


def build_channel_status(
    config: Mapping[str, Any],
    *,
    setup_url: str = "/setup",
    onboarding_url: str = "/onboarding",
) -> list[dict[str, Any]]:
    """Build channel rows from real config + coming-soon placeholders."""
    active_outbound = str(config.get("OUTBOUND_CHANNEL") or "whatsapp").strip().lower()
    if active_outbound not in SUPPORTED_CHANNELS:
        active_outbound = "whatsapp"

    rows: list[dict[str, Any]] = []
    for channel in PRODUCT_CHANNELS:
        configured = channel_is_configured(channel["id"], config)
        if channel["id"] == active_outbound and configured:
            status = "active_outbound"
        elif configured:
            status = "connected"
        else:
            status = "not_connected"
        action = resolve_channel_action(
            channel["id"],
            status=status,
            config=config,
            setup_url=setup_url,
            onboarding_url=onboarding_url,
        )
        rows.append(
            {
                **channel,
                "status": status,
                "status_label": _STATUS_LABELS[status],
                "supported": True,
                "action_label": action["label"],
                "action_url": action["url"],
                "action_enabled": action["enabled"],
                "action_external": action["external"],
            }
        )

    for channel in COMING_SOON_CHANNELS:
        rows.append(
            {
                **channel,
                "status": "coming_soon",
                "status_label": _STATUS_LABELS["coming_soon"],
                "supported": False,
                "action_label": "Coming soon",
                "action_url": "",
                "action_enabled": False,
                "action_external": False,
            }
        )
    return rows


def demo_channel_status(*, active_outbound: str = "whatsapp") -> list[dict[str, Any]]:
    """Legacy helper kept for tests; prefer build_channel_status()."""
    config = {"OUTBOUND_CHANNEL": active_outbound}
    # Pretend nothing is configured so callers see honest defaults.
    return build_channel_status(config)


def overview_stats(
    leads: list[dict[str, Any]] | None = None,
    sales: list[dict[str, Any]] | None = None,
    *,
    bot_online: bool | None = None,
    active_channel: str | None = None,
    lead_generation_enabled: bool = True,
    crm_export_enabled: bool = False,
    service_offering: str | None = None,
    is_demo: bool = True,
) -> dict[str, Any]:
    leads = leads if leads is not None else demo_leads()
    sales = sales if sales is not None else demo_sales()
    follow_ups = sum(1 for row in leads if row.get("stage") == "Follow-up")
    closed_sales = sum(1 for row in sales if row.get("sale_type") == "Closed sale")
    build_requests = sum(1 for row in sales if row.get("sale_type") == "Build what they want")
    channel_label = active_channel or "WhatsApp"
    if channel_label in _CHANNEL_LABELS:
        channel_label = _CHANNEL_LABELS[channel_label]
    elif isinstance(channel_label, str) and channel_label.islower():
        channel_label = channel_label.replace("_", " ").title()

    return {
        "bot_online": True if bot_online is None else bool(bot_online),
        "active_channel": channel_label,
        "new_leads_today": len(leads),
        "follow_ups_due": follow_ups,
        "closed_sales": closed_sales,
        "build_requests": build_requests,
        "lead_generation_enabled": bool(lead_generation_enabled),
        "service_offering": service_offering
        or (
            "Custom software, AI chatbots, WhatsApp commerce flows, "
            "and lead qualification systems for growing brands."
        ),
        "crm_export_enabled": bool(crm_export_enabled),
        "is_demo": bool(is_demo),
    }


def build_operator_crm_context(app) -> dict[str, Any]:
    """Assemble CRM template context from app config + live health."""
    from app.services.crm_export import crm_export_enabled
    from app.services.health_check import get_bot_health

    config = app.config
    health = get_bot_health(app)
    bot_online = str(health.get("status") or "") == "running"
    active_id = str(config.get("OUTBOUND_CHANNEL") or "whatsapp").strip().lower()
    leads = demo_leads()
    sales = demo_sales()
    crm = overview_stats(
        leads,
        sales,
        bot_online=bot_online,
        active_channel=active_id,
        lead_generation_enabled=True,
        crm_export_enabled=crm_export_enabled(app),
        is_demo=True,
    )
    return {
        "crm": crm,
        "leads": leads,
        "sales": sales,
        "channels": [],  # filled by caller with URLs
        "is_demo": True,
    }

"""Built-in free CRM demo data and helpers for the Closar operator dashboard."""

from __future__ import annotations

from typing import Any


LEAD_STAGES = ("Discover", "Chat", "Follow-up", "Proposal")
SALE_TYPES = ("Closed sale", "Build what they want")

CHANNELS = (
    {"id": "whatsapp", "label": "WhatsApp", "category": "Messaging"},
    {"id": "telegram", "label": "Telegram", "category": "Messaging"},
    {"id": "instagram", "label": "Instagram", "category": "Social"},
    {"id": "messenger", "label": "Messenger", "category": "Social"},
    {"id": "tiktok", "label": "TikTok", "category": "Social"},
    {"id": "discord", "label": "Discord", "category": "Workplace"},
    {"id": "slack", "label": "Slack", "category": "Workplace"},
    {"id": "teams", "label": "Microsoft Teams", "category": "Workplace"},
    {"id": "sms", "label": "SMS", "category": "Messaging"},
    {"id": "line", "label": "Line", "category": "Messaging"},
    {"id": "viber", "label": "Viber", "category": "Messaging"},
    {"id": "email", "label": "Email", "category": "Inbox"},
)


def demo_leads() -> list[dict[str, Any]]:
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


def demo_channel_status(*, active_outbound: str = "whatsapp") -> list[dict[str, Any]]:
    connected = {"whatsapp", "telegram", "instagram", "email"}
    rows: list[dict[str, Any]] = []
    for channel in CHANNELS:
        status = "connected" if channel["id"] in connected else "not_connected"
        if channel["id"] == active_outbound:
            status = "active_outbound"
        rows.append(
            {
                **channel,
                "status": status,
                "status_label": {
                    "active_outbound": "Active outbound",
                    "connected": "Connected",
                    "not_connected": "Not connected",
                }[status],
            }
        )
    return rows


def overview_stats(
    leads: list[dict[str, Any]] | None = None,
    sales: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    leads = leads if leads is not None else demo_leads()
    sales = sales if sales is not None else demo_sales()
    follow_ups = sum(1 for row in leads if row.get("stage") == "Follow-up")
    closed_sales = sum(1 for row in sales if row.get("sale_type") == "Closed sale")
    build_requests = sum(1 for row in sales if row.get("sale_type") == "Build what they want")
    return {
        "bot_online": True,
        "active_channel": "WhatsApp",
        "new_leads_today": len(leads),
        "follow_ups_due": follow_ups,
        "closed_sales": closed_sales,
        "build_requests": build_requests,
        "lead_generation_enabled": True,
        "service_offering": (
            "Custom software, AI chatbots, WhatsApp commerce flows, "
            "and lead qualification systems for growing brands."
        ),
        "crm_export_enabled": False,
    }

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, relationship

from .base import new_uuid, utcnow


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# tenants
# ---------------------------------------------------------------------------
class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(String(36), primary_key=True, default=new_uuid)
    name = Column(String(255), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    disabled_reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    users = relationship("User", back_populates="tenant")
    subscription = relationship("Subscription", back_populates="tenant", uselist=False)
    usage_events = relationship("UsageEvent", back_populates="tenant")
    usage_counter = relationship("UsageCounter", back_populates="tenant", uselist=False)
    connection_state = relationship("ConnectionState", back_populates="tenant", uselist=False)
    bot_config = relationship("BotConfig", back_populates="tenant", uselist=False)
    billing_events = relationship("BillingEvent", back_populates="tenant")
    audit_entries = relationship("AuditLog", back_populates="tenant")
    starter_template_drafts = relationship("StarterTemplateDraft", back_populates="tenant")
    consent_ledger_entries = relationship("ConsentLedger", back_populates="tenant")
    notifications = relationship("TenantNotification", back_populates="tenant")
    conversation_summaries = relationship("ConversationSummary", back_populates="tenant")


# ---------------------------------------------------------------------------
# users
# ---------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=new_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False, index=True)
    email = Column(String(255), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    reset_token = Column(String(255), nullable=True)
    reset_token_expires = Column(DateTime(timezone=True), nullable=True)
    is_admin = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    tenant = relationship("Tenant", back_populates="users")


# ---------------------------------------------------------------------------
# bot_configs
# ---------------------------------------------------------------------------
class BotConfig(Base):
    __tablename__ = "bot_configs"

    tenant_id = Column(String(36), ForeignKey("tenants.id"), primary_key=True)
    business_name = Column(String(100), nullable=False, default="")
    ai_persona_prompt = Column(Text, nullable=False, default="")
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    tenant = relationship("Tenant", back_populates="bot_config")


# ---------------------------------------------------------------------------
# subscriptions
# ---------------------------------------------------------------------------
class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(String(36), primary_key=True, default=new_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False, index=True)
    stripe_customer_id = Column(String(255), nullable=False)
    stripe_subscription_id = Column(String(255), nullable=False, unique=True)
    plan_key = Column(String(50), nullable=False)
    status = Column(String(50), nullable=False, default="active")
    conversation_limit = Column(Integer, nullable=False, default=0)
    current_period_start = Column(DateTime(timezone=True), nullable=False)
    current_period_end = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    tenant = relationship("Tenant", back_populates="subscription")


# ---------------------------------------------------------------------------
# billing_events
# ---------------------------------------------------------------------------
class BillingEvent(Base):
    __tablename__ = "billing_events"

    id = Column(String(36), primary_key=True, default=new_uuid)
    stripe_event_id = Column(String(255), nullable=False, unique=True, index=True)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=True, index=True)
    event_type = Column(String(100), nullable=False)
    payload = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    tenant = relationship("Tenant", back_populates="billing_events")


# ---------------------------------------------------------------------------
# usage_counters
# ---------------------------------------------------------------------------
class UsageCounter(Base):
    __tablename__ = "usage_counters"

    tenant_id = Column(String(36), ForeignKey("tenants.id"), primary_key=True)
    period_start = Column(DateTime(timezone=True), nullable=False)
    conversations_used = Column(Integer, nullable=False, default=0)
    is_blocked = Column(Boolean, nullable=False, default=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    tenant = relationship("Tenant", back_populates="usage_counter")


# ---------------------------------------------------------------------------
# usage_events
# ---------------------------------------------------------------------------
class UsageEvent(Base):
    __tablename__ = "usage_events"

    id = Column(String(36), primary_key=True, default=new_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False, index=True)
    idempotency_key = Column(String(255), nullable=False, unique=True)
    billing_period_start = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    tenant = relationship("Tenant", back_populates="usage_events")

    __table_args__ = (Index("idx_usage_events_tenant_period", "tenant_id", "billing_period_start"),)


# ---------------------------------------------------------------------------
# connection_states
# ---------------------------------------------------------------------------
class ConnectionState(Base):
    __tablename__ = "connection_states"

    tenant_id = Column(String(36), ForeignKey("tenants.id"), primary_key=True)
    status = Column(String(50), nullable=False, default="disconnected")
    phone_number = Column(String(50), nullable=True)
    evolution_instance = Column(String(255), nullable=True)
    connected_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    tenant = relationship("Tenant", back_populates="connection_state")


# ---------------------------------------------------------------------------
# audit_log
# ---------------------------------------------------------------------------
class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(String(36), primary_key=True, default=new_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False, index=True)
    actor_id = Column(String(255), nullable=True)
    actor_type = Column(String(50), nullable=False)
    action = Column(String(100), nullable=False)
    payload = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    tenant = relationship("Tenant", back_populates="audit_entries")


# ---------------------------------------------------------------------------
# starter_template_drafts
# ---------------------------------------------------------------------------
class StarterTemplateDraft(Base):
    __tablename__ = "starter_template_drafts"

    id = Column(String(36), primary_key=True, default=new_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False, index=True)
    workflow_slug = Column(String(80), nullable=False)
    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=False)
    category_label = Column(String(80), nullable=False)
    draft_status = Column(String(50), nullable=False, default="draft")
    provider_state = Column(String(50), nullable=False, default="draft")
    consent_state = Column(String(50), nullable=False, default="required")
    sendability_state = Column(String(50), nullable=False, default="blocked")
    last_submission_outcome = Column(String(50), nullable=True)
    last_submission_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    tenant = relationship("Tenant", back_populates="starter_template_drafts")

    __table_args__ = (
        UniqueConstraint("tenant_id", "workflow_slug", name="uq_starter_template_drafts_tenant_slug"),
    )


# ---------------------------------------------------------------------------
# consent_ledger  (Story 12.6 — Compliance and Sendability Control Surface)
# ---------------------------------------------------------------------------
class ConsentLedger(Base):
    """Tenant-scoped consent record per contact.

    status values: granted | required | revoked
    source: free-text label such as "operator_manual", "inbound_opt_in", etc.
    """

    __tablename__ = "consent_ledger"

    id = Column(String(36), primary_key=True, default=new_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False, index=True)
    contact_id = Column(String(255), nullable=False)
    status = Column(String(50), nullable=False, default="required")
    source = Column(String(100), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    tenant = relationship("Tenant", back_populates="consent_ledger_entries")

    __table_args__ = (
        UniqueConstraint("tenant_id", "contact_id", name="uq_consent_ledger_tenant_contact"),
        Index("idx_consent_ledger_tenant_status", "tenant_id", "status"),
    )


# ---------------------------------------------------------------------------
# tenant_notifications  (Story 12.1 — Notification Center)
# ---------------------------------------------------------------------------
class TenantNotification(Base):
    __tablename__ = "tenant_notifications"

    id = Column(String(36), primary_key=True, default=new_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False, index=True)
    category = Column(String(50), nullable=False)
    alert_type = Column(String(100), nullable=False)
    severity = Column(String(20), nullable=False, default="info")
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    notification_key = Column(String(255), nullable=False)
    details_json = Column(Text, nullable=True)
    dismissed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    tenant = relationship("Tenant", back_populates="notifications")

    __table_args__ = (
        UniqueConstraint("tenant_id", "notification_key", name="uq_tenant_notifications_tenant_key"),
        Index("idx_tenant_notifications_active", "tenant_id", "dismissed_at", "created_at"),
    )


# ---------------------------------------------------------------------------
# conversation_summary
# ---------------------------------------------------------------------------
class ConversationSummary(Base):
    __tablename__ = "conversation_summaries"

    id = Column(String(36), primary_key=True, default=new_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False)
    conversation_key = Column(String(120), nullable=False)
    wa_id = Column(String(36), nullable=False)
    message_count = Column(Integer, nullable=False, default=0)
    escalation_flag = Column(Boolean, nullable=False, default=False)
    latest_timestamp = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    tenant = relationship("Tenant", back_populates="conversation_summaries")
    messages = relationship("ConversationMessage", back_populates="conversation_summary")

    __table_args__ = (
        UniqueConstraint("tenant_id", "conversation_key", name="uq_conversation_summary_tenant_key"),
        Index("ix_conversation_summary_tenant_wa_id_latest", "tenant_id", "wa_id", "latest_timestamp"),
        Index("ix_conversation_summary_tenant_created_at", "tenant_id", "created_at"),
        Index("ix_conversation_summary_tenant_conversation_key", "tenant_id", "conversation_key"),
    )


# ---------------------------------------------------------------------------
# conversation_message
# ---------------------------------------------------------------------------
class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id = Column(String(36), primary_key=True, default=new_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False, index=True)
    conversation_summary_id = Column(String(36), ForeignKey("conversation_summaries.id"), nullable=False)
    conversation_key = Column(String(120), nullable=False)
    wa_id = Column(String(36), nullable=False)
    sender = Column(String(255), nullable=False)
    text_body = Column(Text, nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    delivery_status = Column(String(50), nullable=False)
    correlation_id = Column(String(128), nullable=True)

    conversation_summary = relationship("ConversationSummary", back_populates="messages")

    __table_args__ = (
        Index("ix_conversation_message_summary_id", "conversation_summary_id"),
        Index("ix_conversation_message_tenant_conversation", "tenant_id", "conversation_key"),
        Index("ix_conversation_message_tenant_timestamp", "tenant_id", "timestamp"),
    )


# ---------------------------------------------------------------------------
# oauth_providers
# ---------------------------------------------------------------------------
class OAuthProvider(Base):
    __tablename__ = "oauth_providers"

    id = Column(String(36), primary_key=True, default=new_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    provider = Column(String(50), nullable=False)  # 'google', 'facebook', 'linkedin'
    provider_user_id = Column(String(255), nullable=False)
    email = Column(String(255), nullable=True)
    name = Column(String(255), nullable=True)
    picture_url = Column(String(500), nullable=True)
    access_token = Column(Text, nullable=True)
    refresh_token = Column(Text, nullable=True)
    token_expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    user = relationship("User", backref="oauth_providers")

    __table_args__ = (
        UniqueConstraint("provider", "provider_user_id", name="uq_oauth_provider_user"),
    )

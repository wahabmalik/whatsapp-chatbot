from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text
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

"""Initial SaaS schema bootstrap using canonical architecture table names.

Revision ID: 001_initial_saas_schema
Revises:
Create Date: 2026-05-04
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "001_initial_saas_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("disabled_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("reset_token", sa.String(length=255), nullable=True),
        sa.Column("reset_token_expires", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("stripe_customer_id", sa.String(length=255), nullable=False),
        sa.Column("stripe_subscription_id", sa.String(length=255), nullable=False),
        sa.Column("plan_key", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("conversation_limit", sa.Integer(), nullable=False),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", name="uq_subscriptions_tenant_id"),
        sa.UniqueConstraint("stripe_subscription_id", name="uq_subscriptions_stripe_subscription_id"),
    )
    op.create_index("ix_subscriptions_tenant_id", "subscriptions", ["tenant_id"])

    op.create_table(
        "usage_events",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("billing_period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("idempotency_key", name="uq_usage_events_idempotency_key"),
    )
    op.create_index("ix_usage_events_tenant_id", "usage_events", ["tenant_id"])
    op.create_index(
        "idx_usage_events_tenant_period",
        "usage_events",
        ["tenant_id", "billing_period_start"],
    )

    op.create_table(
        "usage_counters",
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id"), primary_key=True, nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("conversations_used", sa.Integer(), nullable=False),
        sa.Column("is_blocked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "connection_states",
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id"), primary_key=True, nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("phone_number", sa.String(length=50), nullable=True),
        sa.Column("evolution_instance", sa.String(length=255), nullable=True),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "bot_configs",
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id"), primary_key=True, nullable=False),
        sa.Column("business_name", sa.String(length=100), nullable=False),
        sa.Column("ai_persona_prompt", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("actor_id", sa.String(length=255), nullable=True),
        sa.Column("actor_type", sa.String(length=50), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("payload", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_log_tenant_id", "audit_log", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_log_tenant_id", table_name="audit_log")
    op.drop_table("audit_log")

    op.drop_table("bot_configs")
    op.drop_table("connection_states")
    op.drop_table("usage_counters")

    op.drop_index("idx_usage_events_tenant_period", table_name="usage_events")
    op.drop_index("ix_usage_events_tenant_id", table_name="usage_events")
    op.drop_table("usage_events")

    op.drop_index("ix_subscriptions_tenant_id", table_name="subscriptions")
    op.drop_table("subscriptions")

    op.drop_index("ix_users_tenant_id", table_name="users")
    op.drop_table("users")

    op.drop_table("tenants")

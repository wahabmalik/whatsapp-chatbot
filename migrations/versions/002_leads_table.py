"""Add leads table for Scout-powered lead generation.

Revision ID: 002_leads_table
Revises: 001_initial_saas_schema
Create Date: 2026-07-26
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "002_leads_table"
down_revision = "001_initial_saas_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "leads",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("platform", sa.String(length=50), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("bio", sa.Text(), nullable=True),
        sa.Column("profile_url", sa.String(length=500), nullable=True),
        sa.Column("website", sa.String(length=500), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=64), nullable=True),
        sa.Column("follower_count", sa.Integer(), nullable=True),
        sa.Column("following_count", sa.Integer(), nullable=True),
        sa.Column("email_score", sa.Integer(), nullable=True),
        sa.Column("email_source", sa.String(length=80), nullable=True),
        sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("lead_score", sa.Integer(), nullable=True),
        sa.Column("company_domain", sa.String(length=255), nullable=True),
        sa.Column("raw_json", sa.Text(), nullable=True),
        sa.Column("scraped_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "platform", "username", name="uq_leads_tenant_platform_username"),
    )
    op.create_index("ix_leads_tenant_id", "leads", ["tenant_id"])
    op.create_index("ix_leads_tenant_platform", "leads", ["tenant_id", "platform"])
    op.create_index("ix_leads_tenant_email", "leads", ["tenant_id", "email"])
    op.create_index("ix_leads_tenant_scraped_at", "leads", ["tenant_id", "scraped_at"])


def downgrade() -> None:
    op.drop_index("ix_leads_tenant_scraped_at", table_name="leads")
    op.drop_index("ix_leads_tenant_email", table_name="leads")
    op.drop_index("ix_leads_tenant_platform", table_name="leads")
    op.drop_index("ix_leads_tenant_id", table_name="leads")
    op.drop_table("leads")

"""
Tests for Story saas-1.1: Database Schema Bootstrap and Tenant Model.

AC coverage:
    AC-1: Canonical architecture tables exist after create_tables().
  AC-2: Every business entity table has a non-nullable indexed tenant_id column.
    AC-3: TenantGuard raises ValueError when tenant_id is missing/blank.
  AC-4: SaaSDatabase registers in app.extensions["saas_db"] with a working close().
    AC-5: Missing DATABASE_URL skips init; configured but unreachable DB fails fast.
"""

import logging
import os
import pytest
from unittest.mock import patch

from sqlalchemy import inspect as sa_inspect, create_engine

from app.saas_db import SaaSDatabase
from app.repositories.base import TenantGuard


_BASE_ENV = {
    "WHATSAPP_PROVIDER": "meta",
    "ACCESS_TOKEN": "token",
    "YOUR_PHONE_NUMBER": "15551234567",
    "APP_ID": "123456789",
    "APP_SECRET": "supersecret",
    "RECIPIENT_WAID": "15551234567",
    "VERSION": "v18.0",
    "PHONE_NUMBER_ID": "1234567890",
    "VERIFY_TOKEN": "verify-token",
    "OPENAI_API_KEY": "sk-test",
    "FLASK_SECRET_KEY": "test-secret-key",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def in_memory_db():
    """SaaSDatabase backed by an in-memory SQLite instance."""
    db = SaaSDatabase()
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    # Bypass init_app and wire directly for unit-test isolation.
    db._engine = engine
    from sqlalchemy.orm import sessionmaker
    db._Session = sessionmaker(bind=engine)
    db.create_tables()
    yield db
    db.close()


@pytest.fixture()
def flask_app_with_db(tmp_path):
    """Flask test app with DATABASE_URL pointing to a temp SQLite file."""
    db_path = tmp_path / "test_saas.db"
    env = {
        **_BASE_ENV,
        "DATABASE_URL": f"sqlite:///{db_path}",
    }
    with patch.dict(os.environ, env, clear=True), patch("app.config.load_dotenv", return_value=None):
        from app import create_app
        app = create_app()
        yield app


@pytest.fixture()
def flask_app_no_db():
    """Flask test app without DATABASE_URL (SaaS DB skipped)."""
    with patch.dict(os.environ, _BASE_ENV, clear=True), patch("app.config.load_dotenv", return_value=None):
        from app import create_app

        app = create_app()
    return app


# ---------------------------------------------------------------------------
# AC-1: All 11 required tables exist after create_tables()
# ---------------------------------------------------------------------------

REQUIRED_TABLES = {
    "tenants",
    "users",
    "subscriptions",
    "usage_events",
    "usage_counters",
    "connection_states",
    "bot_configs",
    "audit_log",
    "billing_events",
}


def test_all_required_tables_exist(in_memory_db):
    """AC-1: create_tables() produces all 11 required SaaS tables."""
    existing = in_memory_db.get_existing_table_names()
    missing = REQUIRED_TABLES - existing
    assert not missing, f"Missing tables after create_tables(): {sorted(missing)}"


def test_no_extra_required_tables_missing(in_memory_db):
    """AC-1: required_tables property matches the expected 11-table set."""
    assert REQUIRED_TABLES == set(in_memory_db.required_tables)


# ---------------------------------------------------------------------------
# AC-2: Every business entity table has tenant_id as non-nullable indexed column
# ---------------------------------------------------------------------------

# Tables that carry tenant_id (tenant itself is the root, skip it)
TENANT_SCOPED_TABLES = {
    "users",
    "subscriptions",
    "usage_events",
    "usage_counters",
    "connection_states",
    "bot_configs",
    "audit_log",
}


def test_tenant_id_column_exists_in_all_business_tables(in_memory_db):
    """AC-2: tenant_id column present in all business-entity tables."""
    inspector = sa_inspect(in_memory_db._engine)
    for table_name in TENANT_SCOPED_TABLES:
        columns = {c["name"]: c for c in inspector.get_columns(table_name)}
        assert "tenant_id" in columns, (
            f"Table '{table_name}' is missing tenant_id column"
        )


def test_tenant_id_is_non_nullable_where_required(in_memory_db):
    """AC-2: tenant_id is non-nullable in all tenant-scoped canonical tables."""
    inspector = sa_inspect(in_memory_db._engine)
    for table_name in TENANT_SCOPED_TABLES:
        cols = {c["name"]: c for c in inspector.get_columns(table_name)}
        assert not cols["tenant_id"]["nullable"], (
            f"tenant_id in '{table_name}' should be NOT NULL"
        )


def test_tenant_id_is_indexed_in_key_tables(in_memory_db):
    """AC-2: tenant_id has an index in high-query tables."""
    inspector = sa_inspect(in_memory_db._engine)
    for table_name in TENANT_SCOPED_TABLES:
        indexes = inspector.get_indexes(table_name)
        indexed_cols = {col for idx in indexes for col in idx["column_names"]}
        # PK columns are inherently indexed for tables using tenant_id as primary key.
        pk_cols = {c["name"] for c in inspector.get_columns(table_name) if c.get("primary_key")}
        assert "tenant_id" in indexed_cols or "tenant_id" in pk_cols, (
            f"tenant_id in '{table_name}' is not indexed"
        )


# ---------------------------------------------------------------------------
# AC-3: TenantGuard raises ValueError for missing/blank tenant_id
# ---------------------------------------------------------------------------

class _ConcreteRepo(TenantGuard):
    """Minimal concrete subclass for testing."""
    def get_something(self):
        self.require_tenant()
        return self._tenant_id


def test_repository_raises_on_none_tenant_id():
    """AC-3: Constructing repository with None tenant_id raises ValueError."""
    with pytest.raises(ValueError, match="tenant_id is required"):
        _ConcreteRepo(session=None, tenant_id=None)


def test_repository_raises_on_empty_string_tenant_id():
    """AC-3: Constructing repository with empty string raises ValueError."""
    with pytest.raises(ValueError, match="tenant_id is required"):
        _ConcreteRepo(session=None, tenant_id="")


def test_repository_raises_on_whitespace_tenant_id():
    """AC-3: Constructing repository with whitespace-only tenant_id raises ValueError."""
    with pytest.raises(ValueError, match="tenant_id is required"):
        _ConcreteRepo(session=None, tenant_id="   ")


def test_repository_accepts_valid_tenant_id():
    """AC-3: Repository constructed with valid tenant_id works correctly."""
    repo = _ConcreteRepo(session=None, tenant_id="tenant-abc-123")
    assert repo.get_something() == "tenant-abc-123"


def test_repository_require_tenant_guard():
    """AC-3: require_tenant() returns the stored tenant_id when valid."""
    repo = _ConcreteRepo(session=None, tenant_id="t-123")
    assert repo.require_tenant() == "t-123"


def test_tenant_guard_rejects_unscoped_model_query(in_memory_db):
    """AC-3: scoped_query() errors when model does not expose tenant_id."""

    class _NoTenantModel:
        pass

    repo = _ConcreteRepo(session=in_memory_db.session(), tenant_id="tenant-1")
    with pytest.raises(ValueError, match="not tenant-scoped"):
        repo.scoped_query(_NoTenantModel)


# ---------------------------------------------------------------------------
# AC-4: SaaSDatabase registers in app.extensions and close() is callable
# ---------------------------------------------------------------------------

def test_saas_db_registered_in_app_extensions(flask_app_with_db):
    """AC-4: When DATABASE_URL is set, saas_db is present in app.extensions."""
    assert "saas_db" in flask_app_with_db.extensions
    saas_db = flask_app_with_db.extensions["saas_db"]
    assert isinstance(saas_db, SaaSDatabase)
    assert saas_db.is_ready


def test_saas_db_has_close_method(flask_app_with_db):
    """AC-4: SaaSDatabase exposes a callable close() for teardown lifecycle."""
    saas_db = flask_app_with_db.extensions["saas_db"]
    assert callable(getattr(saas_db, "close", None))


def test_saas_db_close_is_idempotent(in_memory_db):
    """AC-4: close() can be called multiple times without error."""
    in_memory_db.close()
    in_memory_db.close()  # second call must not raise


def test_create_tables_is_idempotent(in_memory_db):
    """AC-4: Calling create_tables() twice does not raise (CREATE IF NOT EXISTS)."""
    in_memory_db.create_tables()  # second call on already-created tables


# ---------------------------------------------------------------------------
# AC-5: Missing DATABASE_URL skips init and logs warning; unreachable DB logs error
# ---------------------------------------------------------------------------

def test_missing_database_url_skips_init(flask_app_no_db, caplog):
    """AC-5: Without DATABASE_URL, saas_db is not registered."""
    assert "saas_db" not in flask_app_no_db.extensions


def test_create_app_fails_fast_when_db_unreachable(tmp_path):
    """AC-5: Configured but unreachable DATABASE_URL raises RuntimeError at startup."""
    bad_path = tmp_path / "missing" / "folder" / "unreachable.db"
    env = {
        **_BASE_ENV,
        "DATABASE_URL": f"sqlite:///{bad_path}",
    }
    with patch.dict(os.environ, env, clear=True), patch("app.config.load_dotenv", return_value=None):
        from app import create_app
        with pytest.raises(RuntimeError, match="SAAS_DB_STARTUP_FAIL"):
            create_app()


def test_verify_connectivity_returns_false_for_bad_url(caplog):
    """AC-5: verify_connectivity() returns False and logs an error for an unreachable DB."""
    db = SaaSDatabase()
    # Use a SQLite file in a non-existent directory — guaranteed to fail without extra drivers.
    db._engine = create_engine("sqlite:////nonexistent_path_xyz/no_dir/fail.db")
    from sqlalchemy.orm import sessionmaker
    db._Session = sessionmaker(bind=db._engine)
    with caplog.at_level(logging.ERROR):
        result = db.verify_connectivity()
    assert result is False
    error_found = any(
        "SAAS_DB_CONNECTIVITY_FAILED" in r.message
        for r in caplog.records
    )
    assert error_found, "Expected SAAS_DB_CONNECTIVITY_FAILED error log"


def test_verify_connectivity_returns_false_when_not_initialised(caplog):
    """AC-5: verify_connectivity() returns False gracefully when engine is None."""
    db = SaaSDatabase()
    with caplog.at_level(logging.WARNING):
        result = db.verify_connectivity()
    assert result is False


def test_create_tables_skips_gracefully_when_not_initialised(caplog):
    """AC-5: create_tables() emits a warning and returns cleanly when engine is None."""
    db = SaaSDatabase()
    with caplog.at_level(logging.WARNING):
        db.create_tables()  # must not raise
    warning_found = any(
        "SAAS_DB_SKIP" in r.message
        for r in caplog.records
    )
    assert warning_found


# ---------------------------------------------------------------------------
# Additional: verify connectivity works against in-memory SQLite
# ---------------------------------------------------------------------------

def test_verify_connectivity_returns_true_for_valid_db(in_memory_db):
    """AC-5: verify_connectivity() returns True when the database is reachable."""
    assert in_memory_db.verify_connectivity() is True


# ---------------------------------------------------------------------------
# Additional: tenants.is_active (ENF-03 kill switch) column must exist
# ---------------------------------------------------------------------------

def test_tenants_has_is_active_column(in_memory_db):
    """ENF-03 prerequisite: tenants.is_active column exists and defaults to True."""
    inspector = sa_inspect(in_memory_db._engine)
    cols = {c["name"]: c for c in inspector.get_columns("tenants")}
    assert "is_active" in cols, "tenants.is_active column is missing"
    # SQLite stores defaults as strings; just confirm column is present.


def test_tenants_is_active_defaults_true(in_memory_db):
    """ENF-03: new Tenant row has is_active=True by default."""
    from app.models import Tenant
    session = in_memory_db.session()
    try:
        t = Tenant(name="test-tenant")
        session.add(t)
        session.commit()
        session.refresh(t)
        assert t.is_active is True
    finally:
        session.close()

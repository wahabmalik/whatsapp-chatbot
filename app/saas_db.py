from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

if TYPE_CHECKING:
    from flask import Flask

logger = logging.getLogger(__name__)

_REQUIRED_TABLES = (
    "tenants",
    "users",
    "subscriptions",
    "usage_events",
    "usage_counters",
    "connection_states",
    "bot_configs",
    "audit_log",
    "billing_events",
    "starter_template_drafts",
    "tenant_notifications",
    "conversation_summaries",
    "conversation_messages",
)


class SaaSDatabase:
    """Flask extension that owns the SQLAlchemy engine for the SaaS v1 database.

    Lifecycle:
      - init_app(app)    — called from the app factory; creates engine + session factory.
      - create_tables()  — idempotent CREATE TABLE IF NOT EXISTS for all SaaS models.
      - verify_connectivity() — lightweight SELECT 1 to confirm DB is reachable.
      - close()          — called by Flask's teardown_appcontext; disposes the engine.

    Usage::

        saas_db = SaaSDatabase()
        saas_db.init_app(app)

        with saas_db.session() as s:
            s.add(...)
            s.commit()
    """

    def __init__(self) -> None:
        self._engine = None
        self._Session = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def init_app(self, app: "Flask") -> None:
        db_url = app.config.get("DATABASE_URL") or app.config.get("SAAS_DATABASE_URL")
        if not db_url:
            logger.warning(
                "SAAS_DB_SKIP DATABASE_URL is not set; "
                "SaaS database extension will not be initialised. "
                "SaaS features (auth, billing, usage) will be unavailable."
            )
            return

        connect_args = {}
        is_sqlite = db_url.startswith("sqlite")
        if is_sqlite:
            # SQLite requires check_same_thread=False when used across threads.
            connect_args["check_same_thread"] = False

        engine_kwargs: dict = dict(
            connect_args=connect_args,
            # pool_pre_ping: test each connection before use so stale/dropped
            # connections (e.g. managed Postgres provider kills idle conns) are
            # detected and replaced transparently rather than raising a 500.
            pool_pre_ping=True,
        )
        if not is_sqlite:
            # Recycle connections every 25 minutes. Managed Postgres providers
            # (Neon, Render, Railway) typically close idle connections after
            # 5-30 minutes; recycling before that prevents connection errors.
            engine_kwargs["pool_recycle"] = 1500
            # Cap the connection pool to avoid exhausting the database's
            # max_connections limit under concurrent load.
            engine_kwargs["pool_size"] = 5
            engine_kwargs["max_overflow"] = 10

        self._engine = create_engine(db_url, **engine_kwargs)
        self._Session = sessionmaker(bind=self._engine)
        app.extensions["saas_db"] = self
        logger.info("SAAS_DB_INIT engine created database_url_prefix=%s", db_url.split(":")[0])

    def create_tables(self) -> None:
        """Idempotent: creates all SaaS tables if they do not already exist."""
        if self._engine is None:
            logger.warning("SAAS_DB_SKIP create_tables() called but engine is not initialised.")
            return
        from app.models import Base  # local import to avoid circular dependency at module load

        Base.metadata.create_all(self._engine)
        logger.info("SAAS_DB_TABLES_CREATED tables_count=%d", len(Base.metadata.tables))

    def verify_connectivity(self) -> bool:
        """Returns True if the database is reachable; False otherwise.

        A failed connectivity check logs a clear error but does NOT raise so
        that callers can decide whether to hard-fail or emit a warning.
        """
        if self._engine is None:
            logger.warning("SAAS_DB_SKIP verify_connectivity() called but engine is not initialised.")
            return False
        try:
            with self._engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("SAAS_DB_CONNECTIVITY_OK")
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "SAAS_DB_CONNECTIVITY_FAILED error=%s "
                "Fix: ensure DATABASE_URL is correct and the database server is running.",
                exc,
            )
            return False

    def session(self):
        """Return a new SQLAlchemy Session.  Caller is responsible for lifecycle."""
        if self._Session is None:
            raise RuntimeError(
                "SaaSDatabase is not initialised. "
                "Ensure DATABASE_URL is set and init_app() was called."
            )
        return self._Session()

    def close(self) -> None:
        """Dispose the connection pool — called by Flask teardown_appcontext."""
        if self._engine is not None:
            self._engine.dispose()
            logger.debug("SAAS_DB_CLOSED engine disposed")

    # ------------------------------------------------------------------
    # Introspection helpers (used by tests)
    # ------------------------------------------------------------------

    @property
    def is_ready(self) -> bool:
        return self._engine is not None

    def get_existing_table_names(self) -> set[str]:
        """Return the set of table names that currently exist in the database."""
        if self._engine is None:
            return set()
        from sqlalchemy import inspect as sa_inspect

        inspector = sa_inspect(self._engine)
        return set(inspector.get_table_names())

    @property
    def required_tables(self) -> tuple[str, ...]:
        return _REQUIRED_TABLES

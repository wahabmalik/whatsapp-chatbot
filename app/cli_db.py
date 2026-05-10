from __future__ import annotations

from pathlib import Path

import click
from flask import current_app
from flask.cli import with_appcontext
from sqlalchemy import create_engine, inspect


def _load_alembic_modules() -> tuple[object, object]:
    try:
        from alembic import command  # type: ignore
        from alembic.config import Config  # type: ignore
    except ImportError as exc:  # pragma: no cover - depends on runtime env
        raise click.ClickException(
            "Alembic is not installed. Install dependencies with: pip install -r requirements.txt"
        ) from exc
    return command, Config


def _build_alembic_config() -> object:
    _, Config = _load_alembic_modules()
    repo_root = Path(current_app.root_path).parent
    cfg = Config(str(repo_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(repo_root / "migrations"))

    db_url = current_app.config.get("DATABASE_URL")
    if isinstance(db_url, str) and db_url.strip():
        cfg.set_main_option("sqlalchemy.url", db_url)

    return cfg


def _schema_exists_without_alembic_version(db_url: str) -> bool:
    required_tables = {
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
    engine = create_engine(db_url, pool_pre_ping=True)
    try:
        existing_tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    return required_tables.issubset(existing_tables) and "alembic_version" not in existing_tables


@click.group("db")
def db_cli() -> None:
    """Database migration commands backed by Alembic."""


@db_cli.command("upgrade")
@click.argument("revision", default="head")
@with_appcontext
def db_upgrade(revision: str) -> None:
    """Apply migrations up to REVISION (default: head)."""
    command, _ = _load_alembic_modules()
    cfg = _build_alembic_config()
    db_url = current_app.config.get("DATABASE_URL")

    if (
        revision == "head"
        and isinstance(db_url, str)
        and db_url.strip()
        and _schema_exists_without_alembic_version(db_url)
    ):
        click.echo("Detected existing schema without alembic metadata; stamping head revision.")
        command.stamp(cfg, "head")
        click.echo("Database is now aligned to head migration revision.")
        return

    command.upgrade(cfg, revision)


@db_cli.command("downgrade")
@click.argument("revision")
@with_appcontext
def db_downgrade(revision: str) -> None:
    """Revert migrations down to REVISION."""
    command, _ = _load_alembic_modules()
    command.downgrade(_build_alembic_config(), revision)


@db_cli.command("current")
@with_appcontext
def db_current() -> None:
    """Show current migration revision."""
    command, _ = _load_alembic_modules()
    command.current(_build_alembic_config())

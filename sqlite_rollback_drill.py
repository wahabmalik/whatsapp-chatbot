"""Root entrypoint wrapper for start/sqlite_rollback_drill.py."""

from start.sqlite_rollback_drill import main


if __name__ == "__main__":
    raise SystemExit(main())
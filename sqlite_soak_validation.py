"""Root entrypoint wrapper for start/sqlite_soak_validation.py."""

from start.sqlite_soak_validation import main


if __name__ == "__main__":
    raise SystemExit(main())

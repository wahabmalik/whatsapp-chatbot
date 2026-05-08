# Story 7.11 — SECRET_KEY Hardcoded Fallback Absence Test

**Epic**: 7 (Retrospective carry-forward)
**Status**: done
**Completed**: 2026-05-02

## Summary

Added `SecretKeyFallbackAbsenceTests` to `tests/test_story_5_1_csrf_and_config_write_safety.py` asserting that when neither `FLASK_SECRET_KEY` nor `SECRET_KEY` env vars are set, the app starts with a non-empty, non-static `SECRET_KEY` generated via `secrets.token_hex(32)`. Implements the Epic 1 carry-forward action: *"SECRET_KEY had hardcoded fallback — verify current load_configurations uses secrets.token_hex(32) as non-static fallback."*

## Changes

- **`tests/test_story_5_1_csrf_and_config_write_safety.py`** — Added `SecretKeyFallbackAbsenceTests` class with 4 tests:
  - `test_secret_key_is_set_when_env_vars_absent` — key must be non-empty
  - `test_secret_key_is_not_static_hardcoded_fallback` — key must not be a known bad static value
  - `test_secret_key_differs_between_two_app_instances_without_env` — each app creates a unique key (not a constant)
  - `test_secret_key_uses_env_var_when_provided` — env var takes precedence

## Test Results

4 passed in 11.14s

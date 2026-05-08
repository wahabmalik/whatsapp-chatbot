# Story 7.9 — Store close() Lifecycle Detectability Test

**Epic**: 7 (Retrospective carry-forward)
**Status**: done
**Completed**: 2026-05-02

## Summary

Added `StoreCloseLifecycleTests` to `tests/test_expiring_store.py` asserting that `close()` is idempotent on both store backends, and that `_cleanup_extension_resources` in the app teardown actually calls `close()` on registered extensions (including continuing to close remaining extensions after one raises). Implements the Epic 2 carry-forward action: *"Add store teardown lifecycle test as a required story subtask when any new store backend is introduced."*

## Changes

- **`tests/test_expiring_store.py`** — Added `StoreCloseLifecycleTests` class with 4 tests:
  - `test_memory_store_close_is_idempotent`
  - `test_sqlite_store_close_is_idempotent`
  - `test_cleanup_teardown_calls_close_on_registered_extensions`
  - `test_cleanup_teardown_continues_after_close_exception`

## Test Results

`tests/test_expiring_store.py`: **8 passed** in 7.10s (4 pre-existing + 4 new)

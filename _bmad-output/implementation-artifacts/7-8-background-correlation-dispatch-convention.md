# Story 7.8 — Background Correlation ID Dispatch Convention Documentation

**Epic**: 7 (Retrospective carry-forward)
**Status**: done
**Completed**: 2026-05-02

## Summary

Added an explicit architecture comment block to `_complete_deferred_delivery` in `app/utils/whatsapp_utils.py` documenting the three-step thread context propagation requirement for all new background paths. Implements the Epic 2 and 6 carry-forward action: *"Document thread context propagation requirement for all new background paths."*

## Changes

- **`app/utils/whatsapp_utils.py`** — Added `THREAD CONTEXT PROPAGATION REQUIREMENT` comment block to `_complete_deferred_delivery` specifying:
  1. `request_id` must be passed explicitly as an argument
  2. `set_correlation_id(request_id)` must be called at the start of background execution
  3. `clear_correlation_id()` must be called in a `finally` block

## No New Tests Required

This story is documentation only. The existing `tests/test_deferred_delivery_observability.py` tests already assert the runtime behavior of the convention.

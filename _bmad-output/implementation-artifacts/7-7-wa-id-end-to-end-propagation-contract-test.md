# Story 7.7 — wa_id End-to-End Propagation Contract Test

**Epic**: 7 (Retrospective carry-forward)
**Status**: done
**Completed**: 2026-05-02

## Summary

Added contract tests verifying that the `wa_id` extracted from an inbound normalized message propagates correctly as the `to` field in the outbound WhatsApp API request payload. Implements the Epic 2 carry-forward action: *"Verify outbound recipient correctness explicitly in integration test fixtures — Test asserts wa_id value propagates end-to-end from inbound normalization to outbound API call."*

## Changes

- **`tests/test_wa_id_propagation_contract.py`** (NEW) — `WaIdPropagationContractTests` class with 3 tests:
  - `test_outbound_to_field_matches_inbound_wa_id_meta` — captures outbound `_send_request` call and asserts `data["to"]` equals the inbound contact `wa_id`
  - `test_outbound_to_field_matches_inbound_wa_id_different_number` — same assertion with a different phone number to prove no hardcoded value
  - `test_process_result_from_field_matches_inbound_wa_id` — asserts `result["from"]` in the process return value equals the inbound `wa_id`

## Test Results

`tests/test_wa_id_propagation_contract.py`: **3 passed** in 5.86s

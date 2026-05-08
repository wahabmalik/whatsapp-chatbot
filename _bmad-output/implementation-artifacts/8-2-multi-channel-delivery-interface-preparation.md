---
story_id: "8.2"
story_key: "8-2-multi-channel-delivery-interface-preparation"
status: "done"
epic: 8
story: 2
created: "2026-05-02"
estimate: "3 days"
type: "P1 feature prep"
depends_on:
  - "2.3 (outbound delivery retry and fallback)"
  - "5.2 (configuration validation and runtime guardrails)"
---

# Story 8.2: Multi-channel Delivery Interface Preparation

## Story

As a product owner,
I want outbound delivery abstracted behind a stable channel interface,
so that SMS or Messenger channels can be added in subsequent stories without rewriting the webhook pipeline.

## Epic 8 Transition Context

This is one of the selected P1 non-goal carry-ins for the transition sprint. Scope is intentionally interface-first, not full channel integration.

## Acceptance Criteria

1. A channel-agnostic outbound delivery interface is introduced, with WhatsApp as the active adapter.
2. Existing WhatsApp retry and fallback behavior remains unchanged from current contracts.
3. Channel selection configuration is explicit and safely validated.
4. At least one contract test verifies webhook flow uses the abstraction boundary (not direct WhatsApp-only calls).
5. Documentation captures extension points for upcoming SMS/Messenger implementation.
6. Scope guard passes: no new live non-WhatsApp channel credentials, endpoints, or sends are introduced in this story.

## Tasks

- [x] Define the outbound channel interface and adapter contract. (AC: 1)
- [x] Wrap existing WhatsApp sender as default adapter with no behavior change. (AC: 1, 2)
- [x] Add validated channel selection config with safe default behavior. (AC: 3)
- [x] Add focused contract tests for abstraction usage and no-regression behavior. (AC: 2, 4)
- [x] Update architecture and implementation notes for future channel add-ons. (AC: 5)
- [x] Verify no production multi-channel activation paths were added. (AC: 6)

## Validation Commands

```powershell
.venv\Scripts\python.exe -m pytest tests/test_reliability.py -q
.venv\Scripts\python.exe -m pytest tests/test_retry_escalation_contract.py -q
```

## Risk Closure Criteria

- [x] WhatsApp behavior parity confirmed against existing retry/fallback contracts.
- [x] All multi-channel changes remain behind interface boundaries only.
- [x] No new channel-specific secrets are required for this story to run.

## References

- `_bmad-output/planning-artifacts/next-cycle-readiness.md`
- `_bmad-output/planning-artifacts/epics.md`
- `app/services/`
- `tests/`

## Completion State

- Story completed and validated on 2026-05-03.
- Scope remained interface-only: no live non-WhatsApp channel send path was added.
- Risk closure criteria verified with all checkboxes completed.

## Dev Agent Record

### Files Changed

- `app/services/outbound_channels.py` - Introduced channel interface and adapter seam for outbound delivery.
- `app/utils/whatsapp_utils.py` - Routed outbound sends through channel abstraction boundary.
- `app/config.py` - Added channel selection validation and safe default behavior.
- `tests/test_reliability.py` - Preserved WhatsApp retry/fallback parity assertions under abstraction path.
- `tests/test_retry_escalation_contract.py` - Added/updated contract coverage proving webhook flow uses abstraction seam.

### Completion Notes

- AC1 and AC2: WhatsApp remained the active adapter with behavior parity retained.
- AC3: Channel selection strategy is explicit and validated.
- AC4: Contract tests verify the webhook path uses abstraction boundary rather than direct provider coupling.
- AC5: Extension points for follow-on channels were documented in code and story references.
- AC6: No additional production non-WhatsApp credentials/endpoints/sends were introduced.

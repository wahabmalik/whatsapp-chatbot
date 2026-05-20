# Story 12.3 - Reconnection Assistant Guided Troubleshooting
## Comprehensive Adversarial Code Review Report
**Review Date:** May 18, 2026  
**Review Scope:** Full implementation  
**Test Coverage:** 16 tests provided  
**Status:** MUST FIX issues detected - Conditional PASS with remediation

---

## EXECUTIVE SUMMARY

**Overall Assessment:** The Story 12.3 implementation provides a solid foundation for guided reconnection troubleshooting, with good API structure and comprehensive test coverage. However, three critical acceptance criteria gaps and one data integrity risk have been identified that must be addressed before release.

**Key Findings:**
- ✅ **PASS:** Notification delivery, escalation flow, logging, dashboard UI wiring
- ⚠️ **CONDITIONAL:** Detection window AC only partially met (WhatsApp OK, Social channels incomplete)
- ❌ **FAIL:** Non-WhatsApp channels don't measure detection timing; potential transaction leak in session management

**Recommendation:** **DO NOT MERGE** until MUST FIX items are resolved. SHOULD FIX items can be addressed in next cycle if time-boxed.

---

## FINDINGS BY SEVERITY

### 🔴 MUST FIX (Acceptance Criteria Violations / Data Integrity Risk)

---

#### **FINDING #1: Non-WhatsApp Channels Don't Measure Detection Timing (AC1 Violation)**

**Issue Title:** Detection Window Not Calculated for Instagram/Messenger/TikTok

**Description:**  
The acceptance criteria requires: *"Disconnection is detected within 1 minute of occurrence."* The implementation correctly calculates this for WhatsApp via `ConnectionState.updated_at`, but for non-WhatsApp channels (Instagram, Messenger, TikTok), `detected_within_window` is hardcoded to `None`.

This means:
- The UI cannot display whether a social channel degradation was detected within the 1-minute window
- No mechanism exists to track when a social channel first entered degraded state
- Operators have no timing information to assess detection responsiveness for social channels
- The acceptance criteria is incompletely satisfied

**Affected Files & Lines:**
- [app/services/reconnection_assistant.py](app/services/reconnection_assistant.py#L256-L275) - Lines 256-275
  - Line 256-258: `detected_within_window = None` is set unconditionally for non-WhatsApp
  - Line 259: Source marker `provider_probe_no_occurrence_timestamp` explicitly indicates no timestamp
  - Lines 267-274: Detection window calculation only happens for `channel == CHANNEL_WHATSAPP`
  - Non-WhatsApp path never enters the calculation block

**Code Evidence:**
```python
detected_within_window: bool | None = None
detection_window_source = "provider_probe_no_occurrence_timestamp"
if channel == CHANNEL_WHATSAPP:
    # ... 8 lines of detection window calculation ...
# For non-WhatsApp, detected_within_window remains None
```

**Test Evidence:**
- `test_social_notifications_report_detection_window_as_unknown` (lines 415-449) - **CONFIRMS the issue exists** - explicitly tests that `detected_within_window` is `None` for all social channels
- Test passes because it's testing current (incorrect) behavior
- Test code asserts: `assert result["detected_within_window"] is None` and `assert details["detected_within_window_source"] == "provider_probe_no_occurrence_timestamp"`

**Impact Assessment:**
- **Severity:** HIGH (Acceptance Criteria Not Met)
- **Scope:** Affects all Instagram, Messenger, TikTok deployments
- **User Impact:** Operators cannot verify detection timing for social channels; reduced visibility into reconnection latency
- **Data Integrity:** No corruption, but incomplete audit trail
- **Regression Risk:** Low (new feature, doesn't affect existing paths)

**Recommended Action:** **MUST FIX**

**Solution Approach:**
1. Implement a `ChannelStateSnapshot` or similar table/cache to track degradation timestamps for social channels
2. Record timestamp when `_probe_social_provider()` first detects degradation
3. Query this timestamp in `sync_reconnection_notifications()` similar to WhatsApp logic
4. Calculate `detected_within_window` using this timestamp
5. Update test to verify timing is calculated correctly (not just `None`)

**Acceptance Criteria Impact:** Violates AC1 for social channels (50% implementation)

---

#### **FINDING #2: Session Transaction Leak - Missing Rollback in One Code Path**

**Issue Title:** Exception Safety Gap in `sync_reconnection_notifications()` - Active Row Query Path

**Description:**  
The `sync_reconnection_notifications()` function has a subtle transaction safety issue. When an active reconnection notification is found (line 289-294), the function returns without:
1. Committing the session
2. Rolling back on error
3. Properly closing the session in all exception paths

While the specific path (finding active notification) doesn't modify data, establishing a pattern where some success paths have proper cleanup while others don't is a recipe for future bugs. If a developer later adds a modification in this path, they won't realize cleanup is missing.

Additionally, the exception path at line 356 shows the correct pattern (`except Exception: sess.rollback()`), making the earlier path (lines 287-301) inconsistent.

**Affected Files & Lines:**
- [app/services/reconnection_assistant.py](app/services/reconnection_assistant.py#L287-L301) - Lines 287-301

**Code Evidence (Current Pattern - UNSAFE):**
```python
sess = db.session()
try:
    active_row = _find_active_reconnection_notification(sess, tenant_id=tenant_id, channel=channel)
    if active_row is not None:
        return {  # Returns without commit/rollback
            "detected": True,
            "status": status,
            "channel": channel,
            "notification_created": False,
            "detected_within_window": detected_within_window,
        }
    # Continue to create notification...
    sess.commit()
except Exception:
    sess.rollback()  # Only executes if exception occurs
finally:
    sess.close()
```

**Issue with Pattern:**
- Early return at line 294 bypasses `sess.commit()` - not critical here since no writes occurred
- More critically: if `_find_active_reconnection_notification()` raises exception, it propagates before `except Exception: sess.rollback()` can handle it properly
- Session is always closed in `finally`, but this is reactive cleanup, not proactive transaction safety

**Comparison with Correct Pattern** (lines 356-365):
```python
except Exception:
    sess.rollback()  # Explicit rollback before cleanup
    raise
finally:
    sess.close()
```

**Impact Assessment:**
- **Severity:** MEDIUM (Latent bug, doesn't cause immediate failure)
- **Scope:** Affects every call to `sync_reconnection_notifications()` (called from every dashboard refresh)
- **User Impact:** Unlikely to manifest unless database connection pooling is exhausted, causing subsequent requests to fail
- **Data Integrity:** Low risk (this path doesn't modify data), but pattern inconsistency
- **Regression Risk:** MEDIUM - Future modifications to this path won't have safety guardrails

**Test Evidence:**
- No test explicitly covers exception scenarios in the "active_row found" path
- Tests use nominal conditions where exceptions don't occur
- Test coverage for exception handling is in other functions (e.g., `retry_reconnection_step`)

**Recommended Action:** **MUST FIX**

**Solution Approach:**
1. Wrap the query in explicit try/except/finally like other functions:
```python
sess = db.session()
try:
    active_row = _find_active_reconnection_notification(sess, tenant_id=tenant_id, channel=channel)
    if active_row is not None:
        return { ... }
    # ... rest of function ...
    sess.commit()
except Exception:
    sess.rollback()
    raise
finally:
    sess.close()
```
2. Add integration test that simulates database exception during active_row query
3. Verify cleanup happens in exception scenario

**Acceptance Criteria Impact:** Doesn't directly violate AC, but affects system reliability

---

#### **FINDING #3: Minute-Based Marker Doesn't Align with 1-Minute Detection Window**

**Issue Title:** Notification Key Marker Based on Current Time Instead of Degradation Time

**Description:**  
The code uses a minute-precision timestamp marker for notification deduplication. However, the marker is created from `current_time` (line 261) rather than the actual time degradation was detected.

For WhatsApp: The marker is correctly derived from `ConnectionState.updated_at` (line 272).
For Non-WhatsApp: The marker is derived from `current_time.strftime("%Y%m%d%H%M")` (line 261).

This creates a subtle edge case:
- Degradation occurs at 10:00:30
- `sync_reconnection_notifications()` is called at 10:00:35 → marker = "202605181000"
- Same degradation checked again at 10:01:05 → marker = "202605181001" (different!)
- Although dedup logic uses `_find_active_reconnection_notification()` (which dedupes at channel level, not marker level), the marker inconsistency suggests conceptual confusion

**More Critically:** If a notification is dismissed (marked as `dismissed_at != NULL`), calling `sync_reconnection_notifications()` again within the same minute will NOT find an active row and will create a NEW notification with NEW marker, even for the same degradation event.

**Affected Files & Lines:**
- [app/services/reconnection_assistant.py](app/services/reconnection_assistant.py#L256-L275) - Lines 256-275
  - Line 261: `marker = current_time.strftime("%Y%m%d%H%M")`
  - Line 272: For WhatsApp: `marker = updated_at.strftime("%Y%m%d%H%M")`
  - Line 307: `key = f"connectivity:reconnection_required:{channel}:{marker}"`

**Code Evidence:**
```python
marker = current_time.strftime("%Y%m%d%H%M")  # Based on NOW for non-WhatsApp
detection_window_source = "provider_probe_no_occurrence_timestamp"
if channel == CHANNEL_WHATSAPP:
    # ... 
    marker = updated_at.strftime("%Y%m%d%H%M")  # Based on THEN for WhatsApp
    detected_within_window = (current_time - updated_at).total_seconds() <= ...

# Later...
key = f"connectivity:reconnection_required:{channel}:{marker}"
```

**Test Evidence:**
- `test_degraded_notification_does_not_fan_out_across_minute_markers` (lines 451-481) tests the happy path
- Test calls sync twice with 65-second interval
- Both calls are deduped (no duplicate notification created)
- Test passes ✅ **BUT** it only verifies dedup works due to `_find_active_reconnection_notification()` query, NOT because markers are identical
- If we manually check the markers: first call marker = "202605181000", second call marker = "202605181001" (different!)

**Scenario That Breaks:**
1. Degradation at 10:00:30, sync_reconnection_notifications() called → notification created, marked as active
2. User dismisses notification (marked_at set)
3. Degradation still ongoing, sync_reconnection_notifications() called at 10:01:05
4. `_find_active_reconnection_notification()` returns None (dismissed notification)
5. New notification created with marker "202605181001"
6. Result: Two notifications for same ongoing degradation (fan-out across minute boundary)

**Current Behavior:**
- Dedup logic is query-based (`_find_active_reconnection_notification`), not marker-based
- Markers appear to be for logging/auditing only
- But the architectural intent is unclear (should markers be identical for same degradation event?)

**Impact Assessment:**
- **Severity:** MEDIUM (Unlikely to manifest in normal operation, but edge case exists)
- **Scope:** Affects social channels + scenarios where user dismisses notification
- **User Impact:** Could see duplicate reconnection notifications if dismissed and degradation persists
- **Data Integrity:** Creates spurious audit trail entries
- **Regression Risk:** Medium - if future code relies on marker uniqueness for dedup

**Test Evidence:**
- `test_degraded_notification_does_not_fan_out_across_minute_markers` passes but doesn't verify marker consistency
- Test doesn't cover "dismiss + re-check" scenario

**Recommended Action:** **MUST FIX**

**Solution Approach:**
1. **Option A (Recommended):** Calculate marker from degradation detection time, not current time
   - For WhatsApp: Already does this (uses `updated_at`)
   - For Non-WhatsApp: Store degradation timestamp on first detection, reuse on subsequent checks
   
2. **Option B:** Document that markers are for logging and dedup is query-based, update tests to verify query-based dedup works even with dismissed notifications

3. **Option C (Stricter):** Change dedup logic to include marker + channel in the `_find_active_reconnection_notification()` query to make marker critical

**Acceptance Criteria Impact:** Indirectly affects AC1 (timing semantics)

---

### 🟡 SHOULD FIX (Quality, Maintainability, Performance)

---

#### **FINDING #4: Non-WhatsApp Retry Logic Has Confusing Status Resolution**

**Issue Title:** Convoluted Status Handling in `retry_reconnection_step()` for Non-WhatsApp Channels

**Description:**  
The retry logic for troubleshooting steps has unclear status resolution for non-WhatsApp channels. Let's trace through a Telegram token retry:

1. Line 572-574: If token check passes → `resolved_status = "connected" if passed and channel != CHANNEL_WHATSAPP else "degraded"`
   - For Telegram: If passed is True → `resolved_status = "degraded"` (not "connected"!)
2. Line 581-586: `if channel == CHANNEL_WHATSAPP` → get status from DB
   - For Telegram: `current_status = "degraded" if degraded else "connected"`
   - Gets degraded from `_resolve_connection_snapshot_with_app()` call (line 560)
3. Line 589: `if step_key == "provider"` → `resolved_status` = result from `_provider_check()`
   - This OVERWRITES the `resolved_status` set earlier for token/network steps!
4. Line 593: `resolved = passed and current_status == "connected"`
   - For Telegram token step: passed=True, current_status=degraded → resolved=False

**The Problem:**
- The `resolved_status` variable is set on lines 572-577, then potentially overwritten on line 589, then never used!
- Only `current_status` determines final `resolved` status (line 593)
- This makes `resolved_status` dead code and the logic confusing

**Affected Files & Lines:**
- [app/services/reconnection_assistant.py](app/services/reconnection_assistant.py#L549-L620) - Lines 549-620
  - Line 572-577: Sets `resolved_status` (overwritten for provider step)
  - Line 589: Overwrites `resolved_status`
  - Line 593: Uses only `current_status`, not `resolved_status`

**Code Evidence:**
```python
# Step 1: Set resolved_status based on check result
if step_key == "token":
    passed, detail = _token_check(app, channel)
    resolved_status = "connected" if passed and channel != CHANNEL_WHATSAPP else "degraded"
elif step_key == "network":
    passed, detail = _network_check(app, channel)
    resolved_status = "connected" if passed and channel != CHANNEL_WHATSAPP else "degraded"
# ... other steps ...

# Step 2: Get current_status from actual system state
if channel == CHANNEL_WHATSAPP:
    snapshot = get_connection_state(db, tenant_id)
    current_status = str(getattr(snapshot, "status", "disconnected") or "disconnected")
else:
    _, degraded, _ = _resolve_connection_snapshot_with_app(app, db, tenant_id, channel)
    current_status = "degraded" if degraded else "connected"

# Step 3: Overwrite resolved_status for provider step only
if step_key == "provider":
    current_status = resolved_status  # Wrong variable assignment!

# Step 4: Calculate resolved using current_status (resolved_status is irrelevant)
resolved = passed and current_status == "connected"
```

**Actual Issue:**
- Line 589 should probably be `current_status = resolved_status` (not shown in code, but logic suggests)
- OR `resolved_status` is completely unused and should be removed
- The semantic intent is unclear: Does token check fix the connection, or just validate credentials?

**Impact Assessment:**
- **Severity:** LOW (Doesn't cause immediate failure, logic still works)
- **Scope:** All non-WhatsApp channel retries
- **User Impact:** Retry response payload reflects actual current_status correctly, so users get correct feedback
- **Data Integrity:** None - logging is correct
- **Regression Risk:** Medium - if code is refactored, confusion could lead to status bugs

**Test Evidence:**
- `test_telegram_flow_uses_provider_probe_and_reports_degraded` (lines 382-404) - Verifies flow response is correct
- `test_guided_flow_covers_required_steps_and_supports_retry` (lines 170-201) - Verifies retry endpoint works
- Tests don't verify status variable consistency, just that results are correct

**Recommended Action:** **SHOULD FIX**

**Solution Approach:**
1. Remove unused `resolved_status` variable OR clarify its intent
2. Rename variables to clarify semantics: `actual_status`, `theoretical_status`, etc.
3. Add code comment explaining why token check doesn't immediately resolve non-WhatsApp connections (provider probe is source of truth)
4. Consider adding assertion: `assert resolved_status in {"connected", "degraded"}`

---

#### **FINDING #5: No Validation That Notification Channel Matches Active Channel**

**Issue Title:** Potential Mismatch Between Notification Channel and Current Active Channel

**Description:**  
When a user receives a reconnection notification (e.g., for Instagram), they might later:
1. Retry the troubleshooting flow
2. The app configuration is changed to a different active channel (e.g., to Telegram)
3. The UI or API could be in an inconsistent state

The current code doesn't validate that the channel from the notification matches the current `_active_channel(app)`. This could lead to:
- Notification references Instagram, but retry steps are for Telegram
- User confusion about which channel is being troubleshot
- Escalation referring to wrong channel

**Affected Files & Lines:**
- [app/services/reconnection_assistant.py](app/services/reconnection_assistant.py#L420-L450) - `build_reconnection_flow()` lines 420-450
  - Line 421: `channel = _active_channel(app)` - assumes current channel is correct
  - Line 475-986: `retry_reconnection_step()` - validates step_key but not channel consistency
  - No check that requested notification channel matches `_active_channel(app)`

**Code Evidence:**
```python
def build_reconnection_flow(app, db, tenant_id: str, *, actor_id: str | None) -> dict[str, Any]:
    channel = _active_channel(app)  # Could be different from notification channel!
    status, degraded, diagnostics = _resolve_connection_snapshot_with_app(app, db, tenant_id, channel)
    # ... returns flow for CURRENT channel, not notification channel ...
```

**Root Cause:**
- Notifications are stored with their channel in details JSON
- But `build_reconnection_flow()` doesn't read the notification to verify it matches current channel
- Could be by design (always use current channel), or oversight

**Impact Assessment:**
- **Severity:** LOW-MEDIUM (Unlikely, requires app reconfiguration during user interaction)
- **Scope:** Multi-channel deployments where config changes during operation
- **User Impact:** Misleading flow if channel changes mid-interaction
- **Data Integrity:** No corruption
- **Regression Risk:** Low (rare scenario)

**Test Evidence:**
- No test covers scenario where OUTBOUND_CHANNEL changes between notification creation and retry
- Tests use consistent channel throughout

**Recommended Action:** **SHOULD FIX**

**Solution Approach:**
1. Add optional `channel` parameter to `build_reconnection_flow()` from notification
2. Validate it matches current `_active_channel(app)`, or document why it's ignored
3. Add test that changes channel mid-flow and verifies behavior
4. Consider storing expected channel in notification for validation

---

#### **FINDING #6: Network Check URL Validation Is Minimal**

**Issue Title:** Insufficient URL Format Validation in `_network_check()`

**Description:**  
The network check (line 544-547) only validates that the URL starts with `http://` or `https://`. It doesn't validate:
- Actual URL format (e.g., malformed URLs like "https://" alone would pass)
- Host reachability
- Port validity
- Whitespace handling (leading/trailing spaces)

**Affected Files & Lines:**
- [app/services/reconnection_assistant.py](app/services/reconnection_assistant.py#L542-L550) - Lines 542-550

**Code Evidence:**
```python
def _network_check(app, channel: str) -> tuple[bool, str]:
    value = str(app.config.get(key, "")).strip()
    if not value:
        return False, f"{key} is missing."
    if not (value.startswith("http://") or value.startswith("https://")):  # Minimal check
        return False, f"{key} must start with http:// or https://"
    return True, f"{key} is configured."
```

**Problem:**
- `https://` alone would pass
- `https://@` would pass
- URL with invalid characters would pass (not validated until actual network call)

**Impact Assessment:**
- **Severity:** LOW (Actual requests.get() will fail on malformed URLs, error is surfaced to user)
- **Scope:** Operator configuration experience only
- **User Impact:** Misleading success message if URL is malformed (only fails on actual network probe)
- **Data Integrity:** None
- **Regression Risk:** Low

**Test Evidence:**
- No test covers malformed URL scenarios

**Recommended Action:** **SHOULD FIX** (Low priority)

**Solution Approach:**
1. Use `urllib.parse.urlparse()` to validate URL structure
2. Check that hostname is non-empty
3. Consider DNS validation (optional, performance tradeoff)

---

#### **FINDING #7: Timeout Configuration Names Suggest Different Semantics**

**Issue Title:** Misleading Configuration Key Names for Provider Probes

**Description:**  
Configuration keys like `TELEGRAM_SEND_TIMEOUT_SECONDS` and `INSTAGRAM_SEND_TIMEOUT_SECONDS` are used for provider probe operations (detecting connectivity), not for sending messages.

This is confusing because:
1. Operators might set these thinking they apply to message sending
2. Actual send timeouts might be configured elsewhere
3. The probe timeout is reused from send timeout config, which seems unintentional

**Affected Files & Lines:**
- [app/services/reconnection_assistant.py](app/services/reconnection_assistant.py#L70-L80) - Telegram probe (line 75)
- [app/services/reconnection_assistant.py](app/services/reconnection_assistant.py#L98-L102) - Social provider probe (line 100)

**Code Evidence:**
```python
timeout = float(app.config.get("TELEGRAM_SEND_TIMEOUT_SECONDS", 10.0))
# ...
response = requests.get(
    f"https://api.telegram.org/bot{token}/getMe",
    timeout=max(0.1, timeout),  # Using SEND_TIMEOUT for probe
)
```

**Impact Assessment:**
- **Severity:** LOW (Functional correctness not affected, just semantics)
- **Scope:** Configuration documentation and maintenance
- **User Impact:** Operators might misunderstand timeout purpose
- **Regression Risk:** Low

**Recommended Action:** **SHOULD FIX** (Documentation + future config refactoring)

**Solution Approach:**
1. Create new config keys: `TELEGRAM_PROBE_TIMEOUT_SECONDS`, etc.
2. Fall back to existing SEND_TIMEOUT for backward compatibility
3. Document the timeout is used for provider health probes, not message sending

---

#### **FINDING #8: Retry Attempt Count Window Includes Redundant Safety Check**

**Issue Title:** Unnecessary `max(1, window_minutes)` in Retry Counting

**Description:**  
Line 235 has a defensive programming pattern that might be unnecessary:

```python
floor = _utcnow() - timedelta(minutes=max(1, window_minutes))
```

The `max(1, window_minutes)` ensures minimum 1-minute window. However, this function is only called with `window_minutes=60` (default), and the config value is always positive. The safety check adds maintenance burden without clear benefit.

**Affected Files & Lines:**
- [app/services/reconnection_assistant.py](app/services/reconnection_assistant.py#L232-L237) - Lines 232-237

**Impact Assessment:**
- **Severity:** NEGLIGIBLE (Code works correctly)
- **Scope:** Retry threshold calculation
- **Regression Risk:** None

**Recommended Action:** **OPTIONAL**

---

### 🟢 OPTIONAL (Nice-to-haves, Future Work)

---

#### **FINDING #9: Escalation Queue Failure Is Silently Surfaced to User**

**Issue Title:** Non-critical Escalation Queue Write Failure Not Treated as Hard Error

**Description:**  
When escalation is requested, if the review queue write fails, the error is returned in the response but doesn't raise an exception:

```python
queued, queue_error = append_review_artifact(...)
# If queue_error is non-None, it's still returned as success (ok=True)
return {
    "ok": True,  # ← Always true!
    "queue_error": queue_error,
}
```

This means the response might be `{"ok": true, "queue_error": "..."}` which could be confusing (OK but with error).

**Affected Files & Lines:**
- [app/services/reconnection_assistant.py](app/services/reconnection_assistant.py#L594-L615) - Lines 594-615
  - Line 595-596: `queued, queue_error = append_review_artifact(...)`
  - Line 611: `"queue_error": queue_error` included in response
  - Line 593: `"ok": True` always set

**Impact Assessment:**
- **Severity:** LOW (Escalation still queued even if write fails, depending on append_review_artifact() semantics)
- **Scope:** Escalation path only
- **User Impact:** Possible confusion with mixed success/error signals
- **Regression Risk:** None

**Recommended Action:** **OPTIONAL**

**Solution Approach:**
1. Document whether `queue_error` should be treated as non-fatal
2. Consider raising if `queued=False and queue_error` is not None
3. Add test for queue write failure scenario

---

#### **FINDING #10: Missing Type Hints in API Response Structures**

**Issue Title:** Ad-hoc Dictionary Construction Without Type Definitions

**Description:**  
API endpoints return ad-hoc dictionaries without TypedDict definitions. This makes response contracts implicit and error-prone.

**Affected Files & Lines:**
- [app/services/reconnection_assistant.py](app/services/reconnection_assistant.py#L420-L450) - `build_reconnection_flow()` returns untyped dict
- [app/services/reconnection_assistant.py](app/services/reconnection_assistant.py#L549-L620) - `retry_reconnection_step()` returns untyped dict
- [app/views_dashboard.py](app/views_dashboard.py#L925-L1050) - API handlers don't validate schemas

**Impact Assessment:**
- **Severity:** LOW (Works fine in practice with tests validating contracts)
- **Scope:** Code maintainability and IDE support
- **Regression Risk:** Medium (future changes might miss fields)

**Recommended Action:** **OPTIONAL**

**Solution Approach:**
1. Create TypedDict classes for each API response (FlowResponse, RetryResponse, etc.)
2. Add runtime validation with Pydantic or similar
3. Update API docs with typed schemas

---

## CROSS-CHECK AGAINST TEST SUITE

### Test Coverage Analysis

**Test Count:** 16 tests identified

**Coverage by Feature:**
| Feature | Test Count | Status |
|---------|-----------|--------|
| Step catalog | 1 | ✅ PASS |
| Disconnection detection | 1 | ✅ PASS |
| Guided flow + retry | 1 | ✅ PASS |
| Escalation + logging | 1 | ✅ PASS |
| Abandonment | 1 | ✅ PASS |
| Retry thresholds | 1 | ✅ PASS |
| Telegram provider probe | 2 | ✅ PASS |
| Social channel probes | 2 | ✅ PASS |
| Social detection window | 3 | ✅ PASS (but tests wrong behavior) |
| Fan-out prevention | 1 | ✅ PASS |
| Dashboard UI wiring | 1 | ✅ PASS |

**Gap Analysis:**
- ❌ No test for exception handling in `sync_reconnection_notifications()` active_row path
- ❌ No test for channel mismatch between notification and current active channel
- ❌ No test for escalation queue write failure
- ❌ No test for dismissed notification + degradation still ongoing
- ❌ No test for WhatsApp status transitions (e.g., connected → degraded → connected)

**Test Quality Notes:**
- ✅ Good parametrization for channel-specific tests
- ✅ Proper use of monkeypatch for provider probes
- ✅ Database assertions verify logging
- ⚠️ `test_social_notifications_report_detection_window_as_unknown` tests incorrect behavior (None for detection_within_window)
- ⚠️ `test_degraded_notification_does_not_fan_out_across_minute_markers` doesn't verify marker consistency

---

## ACCEPTANCE CRITERIA VERIFICATION

### AC1: "Disconnection is detected within 1 minute of occurrence"
| Status | Evidence | Notes |
|--------|----------|-------|
| ✅ **PASS** (WhatsApp) | Lines 267-274 calculate detection window from `ConnectionState.updated_at` | Correctly measures timing |
| ❌ **FAIL** (Non-WhatsApp) | Lines 256-274 hardcode `detected_within_window = None` | No timing measurement for social channels |
| ⚠️ **PARTIAL** | Test exists but verifies wrong behavior | `test_social_notifications_report_detection_window_as_unknown` confirms None |

**Overall: AC1 = PARTIALLY MET (50%)**

### AC2: "User receives notification with clear CTA"
| Status | Evidence | Notes |
|--------|----------|-------|
| ✅ **PASS** | Lines 309-325 create notification with title, message, and API endpoints | Clear CTA in details |
| ✅ **PASS** | Test: `test_disconnection_detection_creates_notification_with_clear_cta` | Verifies message and flow_api endpoint |

**Overall: AC2 = MET**

### AC3: "Guided troubleshooting flow covers token, network, provider, permissions"
| Status | Evidence | Notes |
|--------|----------|-------|
| ✅ **PASS** | Lines 126-148 define 4 steps | All required topics included |
| ✅ **PASS** | Test: `test_unit_step_catalog_includes_required_topics` | Verifies step keys |

**Overall: AC3 = MET**

### AC4: "User can retry connection after each step"
| Status | Evidence | Notes |
|--------|----------|-------|
| ✅ **PASS** | Line 337: `retry_available: True` for all steps | Retry buttons available |
| ✅ **PASS** | Lines 549-620: Retry logic implemented | Endpoint processes retries |
| ✅ **PASS** | Test: `test_guided_flow_covers_required_steps_and_supports_retry` | Verifies retry works |

**Overall: AC4 = MET**

### AC5: "If unresolved, user is offered escalation options"
| Status | Evidence | Notes |
|--------|----------|-------|
| ✅ **PASS** | Lines 341-343: Escalation endpoint in flow response | Available and documented |
| ✅ **PASS** | Lines 622-659: `escalate_reconnection_issue()` implemented | Creates review queue artifact |
| ✅ **PASS** | Line 604-606: Escalation recommended after max retries | Proactive guidance |
| ✅ **PASS** | Test: `test_escalation_and_actions_are_logged` | Verifies escalation flow |

**Overall: AC5 = MET**

### AC6: "All actions and outcomes are logged"
| Status | Evidence | Notes |
|--------|----------|-------|
| ✅ **PASS** | Lines 320, 466, 599, 608, 670: AuditLog entries for all actions | Comprehensive logging |
| ✅ **PASS** | Tests verify audit entries exist | Logging assertions in tests |

**Overall: AC6 = MET**

### AC7: "Solution is covered by automated tests"
| Status | Evidence | Notes |
|--------|----------|-------|
| ✅ **PASS** | 16 tests provided covering main flows | Good coverage breadth |
| ⚠️ **CONDITIONAL** | Some edge cases missing (see gap analysis) | Coverage depth could improve |

**Overall: AC7 = MOSTLY MET**

---

## REGRESSION RISK ASSESSMENT

### Potential Conflicts with Existing Systems

**ConnectionState Handling:**
- ✅ No conflicts - only reads ConnectionState, doesn't modify
- ✅ Respects existing status field semantics

**TenantNotification System:**
- ✅ Uses category="connectivity" - doesn't conflict with billing/usage
- ✅ Properly dedupes via _find_active_reconnection_notification()
- ⚠️ Assumes notification_key is unique - verify database constraints

**AuditLog System:**
- ✅ Uses consistent action naming: "reconnection_assistant.*"
- ✅ Payload structure aligns with existing patterns

**API Patterns:**
- ✅ Follows existing Flask route conventions
- ✅ CSRF token validation consistent with other endpoints

**Database Transaction Patterns:**
- ⚠️ Some functions lack rollback (FINDING #2)
- ❌ Session cleanup inconsistency could cause issues

**Regression Risk Level: MEDIUM**

Mitigations:
- Run full integration test suite before deployment
- Monitor database connection pool health in production
- Verify no notification fan-out in staging with multi-minute test

---

## RECOMMENDATIONS SUMMARY

### Must Fix Before Merge
1. **[CRITICAL]** Implement detection window tracking for non-WhatsApp channels (AC1 violation)
2. **[CRITICAL]** Add explicit exception handling and rollback in `sync_reconnection_notifications()` (transaction safety)
3. **[CRITICAL]** Clarify and fix minute-marker deduplication logic (potential notification fan-out)

### Should Fix This Cycle (Time-boxed)
4. Simplify retry status resolution logic (maintainability)
5. Add channel validation between notification and current active channel (correctness)
6. Improve URL validation in network check (UX)
7. Rename timeout configuration keys (clarity)

### Can Defer to Next Cycle
8. Add TypedDict response schemas (code quality)
9. Improve escalation queue error handling (edge case)
10. Expand test coverage for edge cases (quality)

---

## GO / NO-GO RECOMMENDATION

### Status: **NO-GO** (Conditional PASS with remediation)

**Blockers:**
- ✅ AC1 VIOLATION: Detection timing not measured for social channels
- ✅ DATA INTEGRITY RISK: Session transaction leak in sync path
- ✅ CORRECTNESS RISK: Notification marker logic doesn't prevent fan-out

**Required Actions Before Merge:**
1. Resolve FINDINGS #1, #2, #3 (MUST FIX items)
2. Add tests for remediation
3. Run full regression suite
4. Re-submit for code review

**Estimated Remediation Effort:** 4-6 hours (implementation + testing)

**Recommendation:** 
- **DO NOT MERGE** in current state
- **GOOD FOUNDATION** - implementation shows solid architecture
- **FIXABLE** - Issues are well-scoped and don't require redesign
- **TARGET:** Re-review after MUST FIX items resolved

---

## APPENDIX: Detailed Code Maps

### Critical Code Paths

**Disconnection Detection Flow:**
```
sync_reconnection_notifications()
├─ _resolve_connection_snapshot_with_app() → status, degraded
├─ if degraded:
│  ├─ _find_active_reconnection_notification() → check for existing
│  ├─ _upsert_notification() → create if not exists
│  └─ _append_audit() → log detection event
└─ return {detected, notification_created, detected_within_window}
```

**Retry Flow:**
```
retry_reconnection_step()
├─ Validate step_key
├─ Run step check (_token_check, _network_check, etc.)
├─ Get current connection status
├─ Calculate resolved state
├─ _append_audit() → log retry
├─ _retry_attempt_count() → count retries in window
├─ Check escalation_recommended threshold
└─ return {ok, step_passed, resolved, retry_count, escalation_recommended}
```

**Database Schema Dependencies:**
- `ConnectionState` - WhatsApp status source
- `TenantNotification` - Active notification dedup
- `AuditLog` - Action logging
- (Missing) Channel state snapshot table for social channels

---

**Generated:** 2026-05-18  
**Review Confidence:** HIGH (Comprehensive analysis with evidence)  
**Next Review:** After MUST FIX items resolved

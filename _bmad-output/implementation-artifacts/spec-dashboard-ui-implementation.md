---
title: 'Operator Dashboard UI Implementation'
type: 'feature'
created: '2026-04-28'
status: 'in-progress'
baseline_commit: 'b5f4ca2f853d494db8f899ae983281beafca61a8'
context: 
  - '_bmad-output/planning-artifacts/ux-design.md'
  - '_bmad-output/planning-artifacts/prd.md'
  - '_bmad-output/planning-artifacts/architecture.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Operators currently have only a basic agent selector dropdown. They lack visibility into bot health, message success/failure patterns, and centralized setup validation. This forces manual log inspection and unclear deployment readiness.

**Approach:** Build a responsive operator dashboard with 5 screens (Dashboard home, Setup wizard, Agent selector, Metrics, Message log) plus supporting services (log ring buffer, health check endpoint). All screens use the existing teal/mint visual system from `agents.html`. Focus on reducing setup friction and providing real-time operational visibility.

## Boundaries & Constraints

**Always:** 
- Use only existing dependencies (Flask, Jinja2, no new JS frameworks).
- Match CSS tokens from `app/templates/agents.html` (Segoe UI font, `#0f766e` accent, `#d1fae5` gradient).
- Responsive: works at 375 px (mobile) and 1200+ px (desktop). Sidebar nav becomes bottom tab bar below 768 px.
- No database; all state is in-memory or from env config.
- All new routes must be in a new `app/views_dashboard.py` blueprint.
- Metrics come from existing `MetricsCollector` service.

**Ask First:**
- If a new external service/library is required.
- If the ring buffer size (currently 100 messages) should differ.
- If auto-refresh frequency (30 s) should be different.

**Never:**
- Database or external storage for message log.
- Breaking changes to existing webhook or agent_registry APIs.
- Auth/RBAC — assume single operator per instance.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| First visit, missing .env keys | No `ACCESS_TOKEN`, `APP_SECRET`, etc. in env | Auto-redirect to `/setup`; checklist shows ✗ for missing keys | Skip to next step when key added; allow user to exit wizard |
| First visit, all .env keys present | All 5 required keys in env | Redirect to dashboard; show "Setup complete" badge once | N/A |
| Agent selector: zero agents found | No `skills/agent-*` folders | Empty state banner; save button hidden | N/A |
| Agent selector: one agent found | Single agent in `skills/` | Card is pre-selected; save is disabled (no choice) | N/A |
| Dashboard: metrics not yet collected | Fresh bot start, no messages received | Metric cards show "No data yet" placeholder | N/A |
| Dashboard: bot health check fails | `GET /health` returns 500 or timeout | Red status dot + "Not running"; all other UI stays visible | Fallback to last-known-good status if health check unavailable |
| Message log: ring buffer full | 100th message received | 101st message evicts oldest; buffer stays at 100 | N/A |
| Message log: OpenAI error on a message | OpenAI API fails (timeout, rate limit, etc.) | Row marked with ❌ status; expanded view shows error text | Error text truncated at 200 chars if very long |
| Agent switch: save fails | `data/agent_selection.json` write permission denied | Toast error "Could not save — check file permissions"; selection unchanged | N/A |
| Mobile layout at 375 px | Resize viewport | No horizontal scroll; nav becomes bottom tab bar; buttons fit | N/A |

</frozen-after-approval>

## Code Map

- `app/__init__.py` -- Flask app factory; will register new blueprint
- `app/views.py` -- Existing webhook/agent routes; no changes to this file
- `app/views_dashboard.py` -- NEW: Dashboard routes (GET /, /setup, /metrics, /logs; POST for agent save)
- `app/services/metrics.py` -- Existing MetricsCollector; will add public snapshot method if needed
- `app/services/message_log.py` -- NEW: In-memory ring buffer for messages
- `app/services/health_check.py` -- NEW: Bot health check logic
- `app/templates/base.html` -- NEW: Base layout with sidebar nav, CSS, shared scripts
- `app/templates/dashboard.html` -- NEW: Dashboard home screen
- `app/templates/setup.html` -- NEW: Setup wizard
- `app/templates/agents-enhanced.html` -- REPLACE: Enhanced agent selector (card layout)
- `app/templates/metrics.html` -- NEW: Metrics screen
- `app/templates/logs.html` -- NEW: Message log screen
- `app/static/css/dashboard.css` -- NEW: Dashboard-specific styles (if needed; may go in base.html)
- `app/static/js/dashboard.js` -- NEW: Auto-refresh logic for dashboard

## Tasks & Acceptance

**Execution:**

- [x] `app/services/message_log.py` -- Create MessageLogBuffer class with FIFO ring buffer (100 message limit), add_message, get_all, clear methods -- Foundational service for logs screen
- [x] `app/services/health_check.py` -- Create get_bot_health() function that returns {status, uptime_seconds, last_error} -- Used by dashboard status dot and logs endpoint
- [x] `app/config.py` -- Review and ensure all 5 required .env keys (ACCESS_TOKEN, APP_SECRET, PHONE_NUMBER_ID, VERIFY_TOKEN, OPENAI_API_KEY) are documented -- Setup wizard depends on clear key list
- [x] `app/templates/base.html` -- Create base layout with sidebar nav (desktop) / bottom tabs (mobile < 768px), shared CSS vars, Jinja2 blocks for content/title -- Parent for all dashboard screens
- [x] `app/templates/dashboard.html` -- Implement dashboard home: bot status dot, uptime, metrics cards (messages today, errors, avg response time), recent activity list with [View All] link -- Extends base.html
- [x] `app/templates/setup.html` -- Implement 5-step progressive setup wizard: welcome → checklist of .env keys (with ✓/✗) → webhook URL copy helper → verification test → success screen -- Auto-hides once complete
- [x] `app/templates/agents-enhanced.html` -- Replace dropdown with radio-button cards showing agent name/title/description, active badge, instant feedback toast on save -- Replaces current agents.html
- [x] `app/templates/metrics.html` -- Implement two sections: counter table (webhook.received, webhook.duplicates, openai.request, etc.) and duration bar chart (avg response times) -- Extends base.html
- [x] `app/templates/logs.html` -- Implement message log: time/from/status/preview columns, inline expand for full details, phone number masking with reveal toggle, filter by status -- Extends base.html, pagination not required (100 items max)
- [x] `app/views_dashboard.py` -- Create Blueprint with routes: GET / → render dashboard; GET /setup → render setup or redirect if complete; GET /agents → enhanced agents; POST /agents → save selection with toast response; GET /metrics; GET /logs -- All GET routes return HTML; POST returns JSON for toast feedback
- [x] `app/views_dashboard.py` -- Add AJAX endpoints: GET /api/metrics (returns JSON from MetricsCollector), GET /api/health (returns {status, uptime, last_error}), GET /api/logs (returns array of recent messages) -- Used by dashboard auto-refresh (30 s) and logs page load
- [x] `app/__init__.py` -- Register new dashboard blueprint and health check service in create_app() -- Wires dashboard into app startup
- [x] Verify message_log.py is integrated into webhook handler -- When webhook processes a message, call message_log.add_message({timestamp, from, to_num, agent, reply_text, status, error}) -- Without this, logs page shows no data
- [ ] Test all 5 screens with fresh .env (setup wizard), with complete .env (skip setup → dashboard), and verify nav highlights current page -- Manual browser walkthrough
- [ ] Verify mobile layout at 375 px: sidebar hidden, bottom tabs visible, all buttons reachable without horizontal scroll -- Chrome DevTools responsive mode

**Acceptance Criteria:**

- Given a fresh app with `.env` file missing required keys, when `/` is visited, then redirect to `/setup` and show ✗ for missing keys
- Given setup checklist with all 5 keys present, when "Send test ping" is clicked, then show ✅ and allow progress to next step
- Given setup complete and user returns to `/`, when page loads, then redirect to dashboard (no `/setup` loop)
- Given agent selector with ≥1 agent, when a card is clicked and [Save Selection] is pressed, then show green toast "Agent switched to [Name]" and update active badge
- Given dashboard on initial bot start (no messages yet), when page loads, then metric cards show "No data yet" placeholder text, not empty cells
- Given dashboard with collected metrics, when page auto-refreshes every 30 s, then metrics update without full page reload (AJAX)
- Given bot is not running (health check fails), when dashboard loads, then red status dot + "Not running" is visible and nav still renders
- Given message log with 100+ entries in ring buffer, when new message arrives, then oldest entry is evicted; buffer max stays at 100
- Given message log with a failed OpenAI response, when row is expanded, then error detail is shown (truncated to 200 chars if needed)
- Given message log with phone numbers, when "Reveal" toggle is clicked, then full phone number is shown; clicking again re-masks
- Given mobile viewport at 375 px, when dashboard/agents/metrics/logs are visited, then sidebar nav is hidden, bottom tab bar is visible, no horizontal scroll occurs
- Given agent-selection.json write fails, when [Save Selection] is clicked, then show red toast "Could not save — check file permissions on data/"

## Design Notes

**Auto-refresh strategy:** Dashboard uses a simple `setInterval(fetch_api_metrics, 30000)` with DOM swap — no WebSocket, no Websocket complexity. Metrics JSON is small enough for polling.

**Ring buffer implementation:** `MessageLogBuffer` uses a fixed-size array with a write pointer. When buffer.full, oldest entry is overwritten. This avoids memory creep and keeps the UI simple (no pagination).

**Setup wizard gating:** Each step checks the previous step's validation result before rendering next step. Step 4 (verify test) is only clickable after all 5 .env keys show ✓. This prevents operator confusion about what's blocking progress.

**Phone number masking:** Stored in log as full number; UI renders as `+44…1234` by default. Toggle in each row controls a CSS class or JS attribute to show/hide full number. Reduces PII risk in shared screen contexts.

## Verification

**Commands:**
- `flask --app run:app run` -- expected: Server starts on 0.0.0.0:8000 without config validation errors
- `curl -H "Accept: application/json" http://localhost:8000/api/health` -- expected: Returns `{status: "running", uptime_seconds: <N>, last_error: null}`
- `curl -H "Accept: application/json" http://localhost:8000/api/metrics` -- expected: Returns `{counters: {...}, durations: {...}}`
- `curl http://localhost:8000/setup` -- expected: 200 OK, renders setup wizard or redirects to `/` if complete

**Manual checks:**
- Navigate to `/setup` with fresh `.env` (missing keys): verify ✗ shown for missing keys, ✓ for present keys, next button disabled until all ✓
- Add missing .env keys, refresh: verify ✓ appears for all 5, next button enabled
- Click "Send test ping": verify ✅ shows and next step (success screen) appears
- Go to `/`: verify redirects to dashboard (not setup loop), shows bot status, recent activity, metrics cards
- Go to `/agents`: verify cards shown (not dropdown), current agent highlighted, one agent found → card pre-selected + save disabled
- Go to `/metrics`: verify counter table populated with real numbers, duration bars visible
- Go to `/logs`: verify table shows recent messages with time/from/status/preview, click row to expand and see full message + error (if any)
- Resize browser to 375 px: verify sidebar hidden, bottom tabs visible, all content reachable without horizontal scroll
- Send 5 test WhatsApp messages: verify `/logs` shows them with correct status (✅ sent or ❌ error), `/metrics` counters increment
- Switch agent on `/agents`, send message: verify message is handled by new agent (inspect reply behavior or logs)

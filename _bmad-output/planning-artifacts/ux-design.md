# UX Design Specification — python-whatsapp-bot Operator Dashboard

**Author:** Sally (UX Designer)  
**Date:** 2026-04-27  
**Status:** Ready for Implementation  
**Linked PRD:** `_bmad-output/planning-artifacts/prd.md`

---

## 1. User Context

### Personas

| # | Name | Role | Goal | Pain Today |
|---|------|------|------|-----------|
| P1 | **Operator Omar** | Support Ops Lead, Python-comfortable | Deploy and manage the bot reliably with no code deploys | Setup is opaque; no feedback on live bot health |
| P2 | **Dev Dana** | Backend Developer | Spin up the bot locally and validate webhook flow | `.env` requirements unclear; no way to see real-time errors |

### Key Jobs-to-be-Done

1. **Setup** — Get from cloned repo to first live WhatsApp message in ≤ 45 min.
2. **Monitor** — Know at a glance whether the bot is healthy and processing messages.
3. **Control** — Switch the active AI agent without touching code or restarting.
4. **Debug** — Understand what went wrong when a message fails.

---

## 2. Information Architecture

```
/ (Dashboard)
├── /agents        ← Active now (Agent Selector)
├── /metrics       ← NEW: Live metrics snapshot
├── /logs          ← NEW: Recent message log
└── /setup         ← NEW: First-time setup checklist
```

**Navigation:** Persistent left sidebar (desktop) / bottom tab bar (mobile-width). Active state highlighted with teal accent (`#0f766e`). Bot status indicator (green/red dot) always visible in nav header.

---

## 3. Screen Flows

### 3.1 First-Time Setup Flow

**Entry point:** `/setup`  
**Trigger:** Automatically redirect here if required `.env` keys are missing.

```
[1] Welcome splash
        ↓
[2] Checklist: Required .env keys
    • ACCESS_TOKEN       ✓/✗
    • APP_SECRET         ✓/✗
    • PHONE_NUMBER_ID    ✓/✗
    • VERIFY_TOKEN       ✓/✗
    • OPENAI_API_KEY     ✓/✗
        ↓
[3] Webhook URL copy helper
    "Your webhook URL is: https://YOUR_HOST/webhook"
    [Copy to clipboard]
        ↓
[4] Verification test
    [Send test ping →]  ← calls GET /webhook with stored VERIFY_TOKEN
        ↓
[5] ✅ All good — Redirect to Dashboard
```

**Acceptance Criteria:**
- Step 2 reads actual env vars at render time; shows ✓ for present, ✗ for absent.
- Steps are numbered and visually progressive (step indicators at top).
- User cannot reach Step 4 until all 5 keys show ✓.
- "Copy to clipboard" button shows inline "Copied!" feedback for 2 s.

---

### 3.2 Dashboard (Home)

**URL:** `/`  
**Entry point:** Default landing after setup complete.

**Layout (3-column grid on desktop, stacked on mobile):**

```
┌─────────────────────────────────────────────────┐
│  Bot Status: 🟢 Running   Active Agent: Support  │
│  Uptime: 3h 42m                                  │
├──────────────┬──────────────┬────────────────────┤
│  Messages    │  Errors      │  Avg Response Time  │
│  Today: 142  │  Today: 1    │  1.4 s              │
│  All time: … │              │                     │
├──────────────┴──────────────┴────────────────────┤
│  Recent Activity (last 5 messages — truncated)   │
│  [View All →]                                    │
└─────────────────────────────────────────────────┘
```

**Data Sources:**
- `MetricsCollector.snapshot()` → counters and averages
- Bot status = HTTP health check on self (`GET /health`, to be added)
- Active agent = `get_selected_agent_code()`

**Acceptance Criteria:**
- Metrics auto-refresh every 30 s without full page reload (fetch + DOM swap).
- "Bot Status" shows red dot + "Not running" if health check fails.
- Clicking any metric card navigates to `/metrics`.

---

### 3.3 Agent Selector (Existing — Enhanced)

**URL:** `/agents`  
**Current state:** Functional dropdown + save.

**Enhancements:**

1. **Agent card layout** — Replace `<select>` with radio-button cards showing:
   - Agent name + title
   - Short description from `customize.toml` (if present)
   - Currently active badge
2. **Instant feedback** — After save, show inline toast: "Agent switched to [Name]" (3 s, dismissible).
3. **No-agent empty state** — Current "no agents found" banner kept; add a direct link to `docs/botpress_connection.md` documentation.

**Wireframe (card layout):**
```
┌──────────────────────────┐  ┌──────────────────────────┐
│  ◉ WhatsApp Support Ops  │  │  ○ General Assistant      │
│  Handles tier-1 queries  │  │  Default fallback agent   │
│  [Active]                │  │                           │
└──────────────────────────┘  └──────────────────────────┘
                      [Save Selection]
```

**Acceptance Criteria:**
- Selected card has teal border + "Active" badge.
- Save button disabled when selection unchanged.
- On single-agent installs, card is pre-selected and save is disabled (no action needed).

---

### 3.4 Metrics Screen

**URL:** `/metrics`

**Layout:** Two sections.

**Section A — Counters (table)**

| Metric | Value |
|--------|-------|
| webhook.received | 145 |
| webhook.duplicate_suppressed | 3 |
| openai.request | 142 |
| openai.error | 1 |
| whatsapp.send_success | 141 |

**Section B — Durations (bar visual)**

```
openai.request_duration  ████████░░  avg 1.4 s
whatsapp.send_duration   ████░░░░░░  avg 0.7 s
```

**Acceptance Criteria:**
- Table rows sourced live from `MetricsCollector.snapshot()`.
- Duration bars scale relative to the highest average.
- "Reset metrics" button (secondary style) clears in-memory counters; shows confirm dialog first.
- Metrics page has a "Last refreshed" timestamp + manual "Refresh" button.

---

### 3.5 Message Log Screen

**URL:** `/logs`

> **Note:** This screen requires a new lightweight in-memory ring buffer (e.g., last 100 messages) added to the app layer. No database needed.

**Layout:**

```
Filter: [All ▼]   [From number: ________]   [Refresh]

┌────────┬───────────────┬────────┬──────────────────────┬──────────┐
│ Time   │ From          │ Status │ Preview               │ Agent    │
├────────┼───────────────┼────────┼──────────────────────┼──────────┤
│ 14:32  │ +44…1234      │ ✅ sent│ "Hi, my order is…"   │ Support  │
│ 14:29  │ +44…5678      │ ❌ err │ "When will my…"      │ Support  │
└────────┴───────────────┴────────┴──────────────────────┴──────────┘

[← Older]                                               [Newer →]
```

**Acceptance Criteria:**
- Max 100 entries in memory ring buffer (FIFO eviction).
- Error rows highlighted with light red row background.
- Clicking a row expands inline to show: full message text, OpenAI reply, error detail (if any), message ID.
- Phone numbers masked by default: `+44…1234`. Toggle to reveal (for operators with full access).
- Filter by status: All / Sent / Error.

---

## 4. UX Decisions

| Decision | Rationale |
|----------|-----------|
| **Sidebar nav, not top tabs** | Dashboard needs vertical space; sidebar scales to more screens. On mobile (<768 px), collapses to bottom tab bar to preserve thumb reach. |
| **Cards for agent selection** | Operators need to compare agents at a glance. Dropdown hides all but selected option, increasing cognitive load when choosing. |
| **No database for logs** | Keeps setup simple (PRD goal: ≤ 45 min to first message). In-memory ring buffer is sufficient for operator debug workflows. |
| **30 s auto-refresh on dashboard** | Operators need live status; polling is simpler than WebSockets for a single-user tool. |
| **Masked phone numbers** | Reduces PII exposure risk in shared screen contexts. Reveal toggle keeps utility without defaulting to raw data. |
| **Progressive setup wizard** | Removes ambiguity that currently causes deploy failures. Steps are gated so operators can't skip past broken config. |
| **Toast over full-page flash** | Agent selection save and copy actions are fast; full-page reload creates disorientation. Toast is less disruptive. |

---

## 5. Edge Cases

| Screen | Edge Case | Handling |
|--------|-----------|----------|
| Setup | All keys present on first visit | Skip setup, redirect to dashboard with "Setup complete" badge shown once |
| Setup | Verify token mismatch on test ping | Show inline error "Verification failed – check VERIFY_TOKEN matches Meta app settings" |
| Dashboard | Metrics collector empty (first start) | Show "No data yet – waiting for first message" placeholder in metric cards |
| Agent Selector | Zero agents found | Show empty state banner with docs link; save button hidden |
| Agent Selector | `agent_selection.json` write fails | Show error toast "Could not save – check file permissions on data/" |
| Metrics | All counters are zero | Show zeros; do not hide table. Prevents confusion about whether page loaded correctly |
| Logs | Ring buffer empty | Show "No messages received yet" placeholder row |
| Logs | OpenAI error on a message | Row marked ❌, expanded view shows error string from exception |
| All screens | Bot not running (health check fails) | Red status dot in nav header; no content is hidden — operator can still navigate |
| Mobile | Screen < 768 px | Sidebar collapses; bottom tab bar shows icons + labels for Dashboard, Agents, Metrics, Logs |

---

## 6. Accessibility & Usability Standards

- All interactive elements have visible focus rings.
- Color is never the sole indicator of status (icons + text labels accompany all color badges).
- Minimum touch target: 44 × 44 px.
- All form inputs have associated `<label>` elements.
- Toast notifications are announced via `aria-live="polite"`.
- Error messages identify the field/action that failed, not just "An error occurred".

---

## 7. Visual System (consistent with existing `agents.html`)

| Token | Value | Use |
|-------|-------|-----|
| `--accent` | `#0f766e` | Primary buttons, active states, links |
| `--bg-end` | `#d1fae5` | Page gradient end |
| `--card` | `#ffffff` | Card backgrounds |
| `--border` | `#d1d5db` | Card and input borders |
| `--ink` | `#1f2937` | Body text |
| `--muted` | `#6b7280` | Secondary/helper text |
| Error red | `#fef2f2` / `#dc2626` | Error row bg / error text |
| Warning amber | `#fffbeb` / `#92400e` | Warning banners (already used) |

Border radius: `10px` inputs, `18px` cards. Font: Segoe UI stack (already set globally).

---

## 8. Validation Plan

| What to validate | Method | Pass Criteria |
|-----------------|--------|---------------|
| Setup wizard completes successfully | Manual walkthrough with fresh `.env` | First test ping succeeds within 3 steps |
| Dashboard metrics reflect real traffic | Send 5 test messages, check counters | Counts match exactly |
| Agent switch takes effect immediately | Switch agent, send message, inspect reply behavior | Reply style matches new agent |
| Mobile layout at 375 px | Resize browser / DevTools | No horizontal scroll; tabs reachable by thumb |
| Masked phone number toggle | Click reveal, check number shown | Full number visible; clicking again re-masks |
| Empty state on no agents | Remove all `skills/agent-*` folders | Empty state banner visible, save button hidden |
| Log ring buffer eviction | Simulate 101 messages | Oldest entry evicted; buffer stays at 100 |
| Accessibility – keyboard only | Tab through all screens | Every action reachable without mouse |

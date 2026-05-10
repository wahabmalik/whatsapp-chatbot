---
date: 2026-05-09
author: Sally (UX Designer) + Maya (Design Thinking Coach)
version: 2.0
status: Complete Customer Journey Specification
linkedPRD: prd-whatsapp-ai-bot-saas-v1.md
linkedArchitecture: architecture-whatsapp-ai-bot-saas-v1.md
---

# UX Design Specification — Malixis Reply v1 (SaaS Customer Journey)

**Author:** Sally (UX Designer)  
**Coach:** Maya (Design Thinking Coach)  
**Date:** 2026-05-09  
**Status:** Ready for Implementation  
**Scope:** Complete 5-stage customer journey (Landing → Signup → Billing → Onboarding → Dashboard)

---

## 1. User Context & Journey

### Primary Persona
**Non-Technical SMB Owner/Manager**
- Goal: Connect WhatsApp bot in <10 minutes, manage business without code
- Pain: Current tools require API setup, configuration complexity
- Context: Non-technical, wants "batteries included" experience

### Secondary Personas
- **Billing Owner:** Needs to understand plan limits, upgrade path, usage transparency
- **Internal Admin Operator:** Needs visibility into all customer accounts, emergency controls

### 5-Stage Customer Journey

```
┌─────────────────────────────────────────────────────────────────┐
│ STAGE 1: PUBLIC LANDING PAGE                                    │
│ Hero, Features, Pricing, CTA, Social Proof                      │
│ Goal: Educate + convert to signup                              │
└─────────────────┬───────────────────────────────────────────────┘
                  ↓ [Get Started CTA]
┌─────────────────────────────────────────────────────────────────┐
│ STAGE 2: SIGNUP FLOW                                            │
│ Email, Password, Business Name, Segment                         │
│ Goal: Create account, establish tenant context                 │
└─────────────────┬───────────────────────────────────────────────┘
                  ↓ [Sign Up Button]
┌─────────────────────────────────────────────────────────────────┐
│ STAGE 3: BILLING (Plan Selection + Stripe Checkout)            │
│ Plan cards, pricing, payment method, Stripe redirect/embed     │
│ Goal: Activate subscription, collect payment                   │
└─────────────────┬───────────────────────────────────────────────┘
                  ↓ [Pay Now] → Stripe webhook success
┌─────────────────────────────────────────────────────────────────┐
│ STAGE 4: ONBOARDING WIZARD (4 Steps)                           │
│ Step 1: Scan QR → WhatsApp link                                │
│ Step 2: Name Your Bot (business name)                          │
│ Step 3: Configure AI Persona (prompt template)                 │
│ Step 4: Completion → Dashboard                                 │
│ Goal: Go live with first message in <10 min total              │
└─────────────────┬───────────────────────────────────────────────┘
                  ↓ [Complete Setup]
┌─────────────────────────────────────────────────────────────────┐
│ STAGE 5: DASHBOARD (Active Bot Management)                      │
│ Connection status, usage progress, configuration, settings      │
│ Goal: Operate bot, monitor usage, manage account               │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. STAGE 1: Public Landing Page

**URL:** `/` (or external domain)  
**Entry Point:** First-time visitor  
**Goal:** Educate visitor on value; drive conversion to signup

### 2.1 Landing Page Layout

```
┌──────────────────────────────────────────────────────┐
│  NAVBAR                                              │
│  [Logo] [Features] [Pricing] [Blog] [Sign In] [Get] │
│                                                      │
│                     HERO SECTION                     │
│  "WhatsApp Bot for Your Business — In 2 Minutes"   │
│  "No coding. No setup. Just connect and go live."  │
│  [Get Started] or [See Demo]                       │
│                                                      │
│                   FEATURES SECTION                  │
│  [Icon1] Instant Setup    [Icon2] AI Replies      │
│  Connect in 90 sec        Works 24/7 auto          │
│                                                      │
│  [Icon3] Usage Controls                             │
│  Clear plan limits, no surprises                    │
│                                                      │
│                   PRICING SECTION                   │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐│
│  │ Starter $29  │ │ Pro $49 ⭐  │ │ Business $99 ││
│  │ 2,000 conv   │ │ 5,000 conv   │ │ 15,000 conv  ││
│  │ [Start Free] │ │ [Start Free] │ │ [Start Free] ││
│  └──────────────┘ └──────────────┘ └──────────────┘│
│                                                      │
│                  SOCIAL PROOF                       │
│  Logos: [Customer 1] [Customer 2] [Customer 3]     │
│  Testimonials: "Helped us 10x response time"       │
│                "Setup in 5 minutes"                 │
│                                                      │
│                     FOOTER                          │
│  [Privacy] [Terms] [Support] [Twitter] [LinkedIn]  │
└──────────────────────────────────────────────────────┘
```

### 2.2 Acceptance Criteria

**Given** an unauthenticated visitor  
**When** they land on `/`  
**Then** they see:
- Hero section with headline + subheading + [Get Started] CTA
- 3 feature cards (Instant Setup, AI Replies, Usage Controls)
- 3 pricing cards (Starter/Pro/Business) with clear conversation limits
- Social proof section (3+ customer testimonials)
- Footer with links

**And** clicking [Get Started] or plan card CTA redirects to `/auth/signup`

**And** page loads in ≤ 1 second (p50) with no blocking JS

**And** page is mobile-responsive at 375px, 768px, 1920px viewports

**And** all CTAs use consistent teal accent color (`#0f766e`)

---

## 3. STAGE 2: Signup Flow

**URL:** `/auth/signup`  
**Entry Point:** User clicks [Get Started] on landing page  
**Goal:** Collect minimum info to create account + tenant

### 3.1 Signup Form Layout

```
┌───────────────────────────────────────────────────┐
│  [Logo] Malixis Reply                             │
│                                                   │
│  Create Your Account                              │
│  Step 1 of 2 → [Signup] [Billing] [Onboarding]  │
│                                                   │
│  Email Address                                    │
│  [________________@example.com_________]           │
│  ✓ Valid email format required                    │
│                                                   │
│  Password                                         │
│  [________________●●●●●●●_________]              │
│  ✓ Min 12 chars, 1 uppercase, 1 number, 1 symbol │
│  [Show password toggle]                            │
│                                                   │
│  Business Name                                    │
│  [________________Acme Repairs_________]          │
│  (100 char limit)                                 │
│                                                   │
│  Business Segment (optional)                      │
│  [Select ▼] → Repair | Retail | Services | Other │
│                                                   │
│  [ ] I agree to Terms & Privacy                   │
│                                                   │
│  [Create Account] [Sign In]                       │
│                                                   │
│  "Already have an account? Sign in"               │
└───────────────────────────────────────────────────┘
```

### 3.2 Signup Form Fields

| Field | Type | Validation | Required |
|-------|------|-----------|----------|
| Email | Email | Valid email format, not already registered | ✓ |
| Password | Password | Min 12 chars, 1 uppercase, 1 number, 1 symbol | ✓ |
| Business Name | Text | Max 100 chars, alphanumeric + spaces | ✓ |
| Business Segment | Select | Repair, Retail, Services, Other | ✗ |
| Terms Checkbox | Checkbox | Must accept | ✓ |

### 3.3 Acceptance Criteria

**Given** a visitor on `/auth/signup`  
**When** they fill all required fields with valid values and click [Create Account]  
**Then:**
- A new `users` record is created with hashed password
- A new `tenants` record is created and linked to user
- User session is set with `user_id` and `tenant_id`
- User is redirected to `/billing/plans`

**And** all form errors display inline below the field with red icon:
- Email taken: "This email is already registered"
- Weak password: "Password must include uppercase, number, and symbol"
- Empty required field: "This field is required"

**And** [Show password] toggle reveals/masks password on click

**And** Terms checkbox must be checked; if unchecked at submit, shows error

**And** page is accessible via keyboard only (Tab through fields, Enter to submit)

**And** error messages are announced to screen readers

---

## 4. STAGE 3: Billing (Plan Selection + Stripe Checkout)

**URL:** `/billing/plans`  
**Entry Point:** Redirect from signup success  
**Goal:** Collect payment, activate subscription

### 4.1 Plan Selection Page Layout

```
┌───────────────────────────────────────────────────┐
│  [Logo] Malixis Reply                             │
│                                                   │
│  Choose Your Plan                                 │
│  Step 2 of 2 → [Signup] [Billing] [Onboarding]  │
│                                                   │
│  ┌──────────────┐ ┌──────────────┐ ┌────────────┐ │
│  │ STARTER      │ │ PRO ⭐       │ │ BUSINESS   │ │
│  │ $29/month    │ │ $49/month    │ │ $99/month  │ │
│  ├──────────────┤ ├──────────────┤ ├────────────┤ │
│  │ ✓ 2,000 conv│ │ ✓ 5,000 conv │ │ ✓ 15k conv │ │
│  │ ✓ 1 bot     │ │ ✓ 3 bots     │ │ ✓ 10 bots  │ │
│  │ ✓ Email help│ │ ✓ Chat help  │ │ ✓ Phone sup│ │
│  │             │ │ ✓ Analytics  │ │ ✓ Advanced │ │
│  │             │ │              │ │ ✓ API      │ │
│  │ [Select]    │ │ [Selected]   │ │ [Select]   │ │
│  └──────────────┘ └──────────────┘ └────────────┘ │
│                                                   │
│  ☑ Enable monthly auto-renewal                   │
│  Cancel anytime from dashboard                    │
│                                                   │
│  [Proceed to Stripe] [Back to Signup]             │
└───────────────────────────────────────────────────┘
```

### 4.2 Plan Card Details

| Plan | Price | Conversations | Bots | Support | Extra |
|------|-------|---|---|---|---|
| Starter | $29/mo | 2,000 | 1 | Email | — |
| Pro | $49/mo | 5,000 | 3 | Chat | Analytics |
| Business | $99/mo | 15,000 | 10 | Phone | Advanced API |

### 4.3 Stripe Checkout Flow

**Option A: Redirect to Stripe Checkout (Recommended for v1)**
```
User clicks [Proceed to Stripe]
  ↓
POST /billing/checkout { plan_key: "pro" }
  ↓
API returns: { checkout_url: "https://checkout.stripe.com/pay/..." }
  ↓
Browser redirects to Stripe Checkout (hosted page)
  ↓
User enters payment details
  ↓
Stripe redirects to `/billing/checkout-success?session_id=XXX`
  ↓
Webhook: invoice.payment_succeeded
  ↓
User redirected to `/onboarding`
```

**Option B: Embedded Stripe Payment Element (Future Iteration)**
- Keep in-page form
- Use Stripe JS library for payment element
- Reduces redirect friction but adds client-side JS complexity

**Recommendation:** Use Option A (redirect) for v1 simplicity. Plan Option B for P1.

### 4.4 Acceptance Criteria

**Given** a user on `/billing/plans` with an active session  
**When** they select a plan and click [Proceed to Stripe]  
**Then:**
- A Stripe Checkout session is created with the selected plan
- User is redirected to Stripe hosted checkout page
- Payment form displays securely (Stripe-hosted, not sent to Flask)

**And** after user submits payment on Stripe:
- Stripe webhook: `invoice.payment_succeeded` is received
- `subscriptions` record is created/updated with plan, status=active, limit
- `usage_counters` record is created with used=0, is_blocked=false, period_start=today
- User session is updated with subscription info
- User is redirected to `/onboarding`

**And** if payment fails:
- Stripe redirects to `/billing/checkout-failure?reason=card_declined`
- Page shows error with option to [Retry] or [Try Different Card]

**And** auto-renewal checkbox is visible and checked by default

**And** Terms + Privacy links are shown before payment submission

---

## 5. STAGE 4: Onboarding Wizard (4 Steps)

**URL:** `/onboarding`  
**Entry Point:** Redirect from billing success  
**Goal:** Connect WhatsApp, configure bot, go live in <10 min

### 5.1 Onboarding Wizard Layout (Multi-Step)

```
Step Indicator: [1✓ QR Link] [2⊙ Name Bot] [3⊙ AI Persona] [4⊙ Done!]

═══════════════════════════════════════════════════════════════════

STEP 1: SCAN QR CODE TO LINK WHATSAPP

┌─────────────────────────────────────────────────────┐
│  Scan WhatsApp to Go Live                          │
│  Takes 30 seconds — most important step             │
│                                                     │
│  1. Open WhatsApp on your phone                     │
│  2. Scan this QR code with your camera              │
│  3. Tap the link to connect your number             │
│                                                     │
│  ┌───────────────────────────┐                      │
│  │                           │                      │
│  │    [QR CODE IMAGE]        │                      │
│  │                           │                      │
│  └───────────────────────────┘                      │
│                                                     │
│  Status: ⊙ Connecting...                           │
│  (or) ✓ Connected +447700900000                     │
│  (or) ✗ Not connected yet — try rescanning          │
│                                                     │
│  [Rescan] [I scanned, check again]                  │
│  [Troubleshoot]                                     │
│                                                     │
│                       [Continue →]                  │
└─────────────────────────────────────────────────────┘

═══════════════════════════════════════════════════════════════════

STEP 2: NAME YOUR BOT

┌─────────────────────────────────────────────────────┐
│  What's Your Business Name?                         │
│  This appears in WhatsApp conversations             │
│                                                     │
│  Business Name                                      │
│  [_____________Acme Repairs____________]            │
│  (100 character limit)                              │
│                                                     │
│  Preview in WhatsApp:                               │
│  ┌──────────────────────────────┐                   │
│  │ Acme Repairs                 │                   │
│  │ Hi! How can we help? 👋       │                   │
│  └──────────────────────────────┘                   │
│                                                     │
│  [← Back]            [Continue →]                   │
└─────────────────────────────────────────────────────┘

═══════════════════════════════════════════════════════════════════

STEP 3: CONFIGURE AI PERSONA (Optional but Recommended)

┌─────────────────────────────────────────────────────┐
│  Teach AI How to Respond                            │
│  Tell us about your business (optional)             │
│                                                     │
│  Persona Prompt                                     │
│  ┌─────────────────────────────────────────────────┐ │
│  │ You are a helpful customer service agent for   │ │
│  │ Acme Repairs. Your business specializes in     │ │
│  │ residential appliance repair. Keep responses    │ │
│  │ friendly, concise, and professional.            │ │
│  │ (max 2000 chars)                                │ │
│  └─────────────────────────────────────────────────┘ │
│                                                     │
│  Example replies will appear here based on prompt  │
│  (AI generates 2-3 example replies live)            │
│                                                     │
│  [← Back]            [Continue →]                   │
└─────────────────────────────────────────────────────┘

═══════════════════════════════════════════════════════════════════

STEP 4: SETUP COMPLETE!

┌─────────────────────────────────────────────────────┐
│  🎉 You're All Set!                                │
│                                                     │
│  ✓ WhatsApp connected: +447700900000               │
│  ✓ Business name: Acme Repairs                      │
│  ✓ AI persona configured                            │
│                                                     │
│  Your bot is now live and ready to reply to         │
│  customer messages. Visit your dashboard to:        │
│  • Monitor usage and conversations                  │
│  • View connection status                           │
│  • Update AI responses                              │
│  • Manage plan and billing                          │
│                                                     │
│  Next: Send a test message to your WhatsApp number │
│         from another number to see the bot reply!   │
│                                                     │
│  [Go to Dashboard]                                  │
└─────────────────────────────────────────────────────┘
```

### 5.2 Step 1: QR Code — Real-Time Status

**SSE Stream (Server-Sent Events):**
```javascript
// Connection at: /onboarding/status-stream?step=1

event: connection-status
data: {"status": "connecting", "message": "Waiting for you to scan..."}

event: connection-status
data: {"status": "connected", "phone": "+447700900000", "message": "Connected!"}

// Or after timeout:
event: connection-status
data: {"status": "timeout", "message": "QR expired. Refresh to get new code."}
```

**UX Behavior:**
- Status indicator animates: ⊙ → ✓ (on connected)
- Phone number displays below indicator
- [Continue →] button becomes active (clickable) when connected
- If disconnected/timeout, show [Rescan] button to refresh QR

### 5.3 Step 3: AI Persona — Live Example Generation

**UX Behavior:**
- As user types prompt, textarea shows live character count
- When user stops typing, show loading spinner: "Generating examples..."
- After 1-2 seconds, display 2-3 example replies based on current prompt
- Examples update if user modifies prompt

### 5.4 Acceptance Criteria

**Step 1 (QR Linking):**
- QR code displays from Evolution API
- Real-time status stream (SSE) updates status: connecting → connected
- [Continue] button disabled until status = connected
- If QR expires (>5 min), show [Rescan] to fetch new QR
- Phone number displays when connected

**Step 2 (Name Bot):**
- Business name field pre-filled from signup
- Character count shown (0/100)
- Preview pane updates live as user types
- [Continue] enabled after any name entry

**Step 3 (AI Persona):**
- Textarea with 2000 char limit
- Character count shown (0/2000)
- Example replies load after 1-2 sec of no typing
- User can skip (optional) and go to Step 4

**Step 4 (Completion):**
- Shows summary: connected phone, business name, persona status
- [Go to Dashboard] button redirects to `/dashboard`

**Overall:**
- All 4 steps in a linear flow; no step skipping
- Back button available on steps 2-4 (returns to previous step)
- Estimated time to complete: ≤ 5 minutes
- Page is fully functional on mobile (375px, 768px)

---

## 6. STAGE 5: Customer Dashboard

**URL:** `/dashboard`  
**Entry Point:** After onboarding complete, or login after session expires  
**Goal:** Operate bot, monitor usage, manage account

### 6.1 Dashboard Layout (Desktop)

```
┌──────────────────────────────────────────────────────────────────┐
│ NAVBAR: Malixis Reply | Dashboard | Settings | Support | [Profile ▼] │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  BOT STATUS BANNER (Top)                                        │
│  🟢 Connected: +447700900000 | Acme Repairs                    │
│  Plan: Pro ($49/mo) | 1,243 / 5,000 conversations used        │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ Conversations Used This Month                           │   │
│  │                                                         │   │
│  │ ████████████░░░░░ 1,243 / 5,000 (24.9%)               │   │
│  │                                                         │   │
│  │ Reset Date: June 3, 2026 (24 days remaining)           │   │
│  │                                                         │   │
│  │ [↑ Upgrade Plan] [View History]                        │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                  │
│  DASHBOARD GRID (3 columns)                                    │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │ QUICK STATS  │  │ RECENT CHATS │  │ BOT CONFIG  │         │
│  ├──────────────┤  ├──────────────┤  ├──────────────┤         │
│  │ Today: 47    │  │ Chat 1       │  │ Business    │         │
│  │ This week    │  │ 2h ago       │  │ Name: Acme  │         │
│  │ 234          │  │ (3 msgs)     │  │             │         │
│  │              │  │              │  │ AI Persona: │         │
│  │ Avg response │  │ Chat 2       │  │ "You are a" │         │
│  │ time: 1.2s   │  │ 1h ago       │  │ ...         │         │
│  │              │  │ (1 msg)      │  │             │         │
│  │ 98% success  │  │              │  │ [Edit]      │         │
│  │ rate         │  │ [View All]   │  │             │         │
│  └──────────────┘  └──────────────┘  └──────────────┘         │
│                                                                  │
│  SECONDARY ACTIONS                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │ 📊 Analytics │  │ ⚙️ Reconnect│  │ 💳 Billing  │         │
│  │ (P1 feature) │  │ WhatsApp    │  │ Manage plan │         │
│  └──────────────┘  └──────────────┘  └──────────────┘         │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

### 6.2 Dashboard Sections

#### Connection Status Banner
- **Connected:** 🟢 Green dot + phone number + business name
- **Disconnected:** 🔴 Red dot + "WhatsApp disconnected" + [Reconnect] CTA
- **Reconnecting:** 🟡 Yellow dot + "Reconnecting..."

#### Usage Progress
- Large progress bar: `used / limit` conversations
- Percentage and absolute count
- Reset date displayed
- If > 80% used: warning color (amber)
- If at limit: blocked state (see below)

#### Quick Stats (Cards)
| Card | Metric | Refresh Rate |
|------|--------|---|
| Today | Conversations in last 24h | 5 min |
| This Week | Conversations last 7 days | 5 min |
| Avg Response | Average AI reply time in ms | 5 min |
| Success Rate | % of replies that succeeded | 5 min |

#### Recent Chats
- Table of last 5 conversations (most recent first)
- Columns: Time, Contact (masked by default), Message Preview, Status (✓/✗)
- [View All] button → `/conversations` (P1)

#### Bot Configuration
- Business Name (editable inline)
- AI Persona Prompt (truncated, [Edit] → modal)
- [Edit] button opens inline editor with live examples

### 6.3 Dashboard — Blocked State (At Limit)

**When `is_blocked = true` and used >= limit:**

```
┌──────────────────────────────────────────────────────────────────┐
│                                                                  │
│  ⚠️ USAGE LIMIT REACHED                                         │
│                                                                  │
│  Your bot has reached the 5,000 conversation limit for this     │
│  month. New customer messages will not receive AI replies until │
│  your plan resets on June 3, 2026 (24 days).                   │
│                                                                  │
│  [Upgrade Now]                    [See All Plans]               │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘

Usage: 5,000 / 5,000 ████████████████████ (100%)
```

**[Upgrade Now]** → `/billing/upgrade` → Stripe checkout with higher plan

### 6.4 Dashboard — Mobile Layout (< 768px)

```
Stack vertically:
1. Status banner (full width)
2. Usage progress (full width)
3. Quick stats (1 per row)
4. Recent chats (scrollable table)
5. Bot config (full width)
6. Action buttons (full width stack)
```

### 6.5 Acceptance Criteria

**Given** a logged-in customer on `/dashboard`  
**When** page loads  
**Then:**
- Status banner shows connection state (green/red) + phone + business name
- Usage progress bar shows correct used/limit numbers
- Quick stat cards display current values (refreshed every 5 min)
- Recent chats table shows last 5 conversations
- Bot config section shows current business name + truncated persona
- All numbers match backend `/api/dashboard/summary` response (≤ 60s stale)

**And** when user clicks [Edit] on Business Name:
- Field becomes editable inline
- User can update and [Save]
- Backend `PUT /config/bot` is called
- Success toast: "Business name updated"

**And** when user clicks [Edit] on AI Persona:
- Modal opens with full textarea
- Live example replies load as user types
- User can [Save] or [Cancel]
- Backend `PUT /config/bot` is called

**And** when connection is disconnected:
- Status shows 🔴 "WhatsApp disconnected"
- [Reconnect] CTA button appears
- Clicking [Reconnect] → `/onboarding` (restart QR flow)

**And** when at usage limit:
- Blocked overlay appears over usage section
- [Upgrade Now] button redirects to `/billing/upgrade`
- Blocked state is styled with warning color

**And** page is fully functional on mobile (375px, 768px)

**And** [Settings] nav link → `/settings` (future: manage email, password, notifications)

**And** [Support] nav link → `/support` (contact form or help docs)

---

## 7. Shared UX Patterns & Components

### 7.1 Navigation (All Customer Pages)

**Desktop:** Persistent top navbar
- Logo | Dashboard | Settings | Support | [Profile ▼]
- Secondary menu on Profile: Account, Billing, Logout

**Mobile:** Bottom tab bar (375px-767px)
- Icons + labels: Dashboard | Settings | Profile
- Profile expands to: Account, Billing, Logout

### 7.2 Error Handling (All Pages)

**Validation Errors (Inline):**
```
Email Address
[_____________@example_________]
❌ This email is already registered
```

**Toast Errors (Top-right, 5 sec dismiss):**
```
❌ Failed to save configuration. Please try again.
[×]
```

**Page-Level Errors (Modal):**
```
⚠️ Error
Unable to load dashboard. Please refresh the page.
[Retry] [Go Back]
```

### 7.3 Loading States

**Spinner:** Rotating icon + text "Loading..."  
**Skeleton:** Placeholder boxes while data loads  
**Disable buttons:** While async operation in progress

### 7.4 Success Feedback

**Toast (bottom-right, 3 sec auto-dismiss):**
```
✓ Configuration saved successfully
```

**Inline badge:**
```
✓ Connected
```

### 7.5 Buttons & Links

| Element | Style | Use |
|---------|-------|-----|
| Primary Button | Teal `#0f766e`, white text | Main CTAs (Sign Up, Pay Now, Continue) |
| Secondary Button | Gray outline | Alternative actions (Back, Cancel) |
| Danger Button | Red `#dc2626` | Destructive (Disconnect, Delete) |
| Link | Teal underline | Navigation within pages |
| Disabled | Grayed out, cursor not-allowed | Unavailable action |

### 7.6 Form Validation Rules

| Rule | Message | Enforced |
|------|---------|----------|
| Email unique | "This email is already registered" | Server-side on signup |
| Email format | "Enter a valid email address" | Client + server |
| Password strength | "Min 12 chars, 1 uppercase, 1 number, 1 symbol" | Client + server |
| Password match (on reset) | "Passwords don't match" | Client + server |
| Required field | "This field is required" | Client + server |
| Max length (business name) | "Max 100 characters" | Client on input, server on save |
| Max length (persona) | "Max 2000 characters" | Client on input, server on save |

### 7.7 Accessibility Standards

- All interactive elements focusable via keyboard (Tab)
- Color never the sole indicator (icons + labels always present)
- Minimum touch target: 44 × 44 px
- Form inputs have associated `<label>` elements
- ARIA live regions for toast notifications
- Error messages linked to fields via `aria-describedby`
- Page titles update for each route

### 7.8 Performance Targets

| Metric | Target | Where |
|--------|--------|-------|
| Landing page load | ≤ 1 s p50 | Hero visible in 1s |
| Dashboard load | ≤ 2 s p50 | Core content visible |
| API response | ≤ 500 ms p50 | All endpoints |
| Form submission | ≤ 1 s | Visible feedback within 1s |
| Status stream (SSE) | ≤ 2 s | QR status update latency |

---

## 8. Visual Design System

### 8.1 Color Palette

| Token | Hex | Use |
|-------|-----|-----|
| Accent (Teal) | `#0f766e` | Primary buttons, active states, links |
| Success (Green) | `#10b981` | Connected status, success badges |
| Warning (Amber) | `#f59e0b` | High usage warning, caution states |
| Error (Red) | `#dc2626` | Errors, disconnected status, danger actions |
| Neutral (Gray) | `#6b7280` | Secondary text, disabled states |
| Background | `#ffffff` | Page/card backgrounds |
| Border | `#d1d5db` | Card borders, form inputs |
| Text (Dark) | `#1f2937` | Primary text |
| Text (Light) | `#9ca3af` | Helper text, placeholders |

### 8.2 Typography

| Element | Font | Size | Weight | Line Height |
|---------|------|------|--------|-------------|
| Hero Headline | Segoe UI | 48px | 700 | 1.2 |
| Page Title | Segoe UI | 32px | 700 | 1.3 |
| Section Header | Segoe UI | 20px | 600 | 1.4 |
| Body | Segoe UI | 16px | 400 | 1.5 |
| Small (Label) | Segoe UI | 14px | 500 | 1.4 |
| Input/Code | Monospace | 14px | 400 | 1.5 |

### 8.3 Spacing (8px grid)

| Token | Size | Use |
|-------|------|-----|
| xs | 4px | Inner padding, tight spacing |
| sm | 8px | Field padding, small gaps |
| md | 16px | Card padding, section gaps |
| lg | 24px | Major section spacing |
| xl | 32px | Page-level margins |

### 8.4 Borders & Shadows

| Element | Border | Shadow |
|---------|--------|--------|
| Cards | 1px solid `#d1d5db` | `0 1px 3px rgba(0,0,0,0.1)` |
| Inputs | 2px solid `#d1d5db` (on focus: `#0f766e`) | None |
| Buttons | None | None (text/background change on hover) |
| Modals | None | `0 20px 25px rgba(0,0,0,0.15)` |

### 8.5 Border Radius

| Element | Radius |
|---------|--------|
| Inputs | 8px |
| Cards | 12px |
| Buttons | 6px |
| Large modals | 16px |

---

## 9. Validation & Testing Plan

### 9.1 Usability Testing Checklist

| What | How | Pass Criteria |
|-----|-----|---|
| Landing page conversion | Track click-through to signup | ≥ 10% CTR |
| Signup form completion | Time to fill all fields | ≤ 2 min |
| QR scan success | % users reach connected state | ≥ 70% |
| Onboarding completion | % users finish all 4 steps | ≥ 75% |
| Dashboard comprehension | Users correctly identify usage limit | 100% accuracy |
| Mobile usability | Test at 375px / 768px viewports | No horizontal scroll, all CTAs reachable |

### 9.2 Accessibility Checklist

- [ ] Keyboard navigation works on all pages (Tab through all interactive elements)
- [ ] Screen reader announces all form labels and error messages
- [ ] Color contrast ≥ 4.5:1 for all text
- [ ] Focus ring visible on all focusable elements
- [ ] Touch targets ≥ 44 × 44 px on mobile
- [ ] No auto-playing video or sound
- [ ] Page titles and headings are descriptive

### 9.3 Performance Checklist

- [ ] Landing page initial load ≤ 1 s (p50)
- [ ] Dashboard initial load ≤ 2 s (p50)
- [ ] Stripe checkout loads within 2 s
- [ ] QR status updates within 2 s (SSE latency)
- [ ] Largest page size ≤ 2 MB (uncompressed)

### 9.4 Browser Support

| Browser | Versions | Testing |
|---------|----------|---------|
| Chrome | Latest 2 | Automated |
| Firefox | Latest 2 | Automated |
| Safari | Latest 2 | Manual on macOS |
| Edge | Latest 2 | Automated |
| Mobile Chrome | Latest | Manual |
| Mobile Safari | Latest | Manual |

---

## 10. Migration Path (Operator → Customer Dashboards)

**Current UX Design** (`ux-design.md`) covers operator/developer personas (setup wizard, metrics, logs, agent selector).

**New SaaS v1 UX** (this document) covers customer personas (landing, signup, billing, onboarding, dashboard).

**During implementation:**
- Operator pages remain unchanged at `/setup`, `/metrics`, `/logs`, `/agents`
- Customer pages are new at `/`, `/auth/signup`, `/billing/plans`, `/onboarding`, `/dashboard`
- Authentication layer differentiates roles (customer vs. admin)
- Navbar routing depends on user role

**Future consolidation:**
- If customer and operator are same person, provide tabs/switcher to toggle between dashboards
- If separate roles, maintain isolated navigation paths

### 10.1 Admin Customer Detail Flow (Internal)

- Entry point: `/admin/customers` list row action [View Details]
- Detail route: `/admin/customers/:tenant_id`
- The detail page must show: tenant metadata, current plan + subscription status, usage (`used/limit`, blocked state), WhatsApp connection status, bot configuration summary, and recent audit events.
- Actions on detail page:
  - [Disable Tenant] confirmation modal (requires reason)
  - [Enable Tenant] confirmation modal
- Safety constraints:
  - No secrets rendered (API keys, webhook signatures, password hashes)
  - Danger actions require explicit confirmation with tenant name
- API parity mapping (architecture Screen 8):
  - View detail: `GET /admin/api/customers/{tenant_id}`
  - Disable tenant: `POST /admin/api/customers/{tenant_id}/disable`
  - Enable tenant: `POST /admin/api/customers/{tenant_id}/enable`

---

## Appendix A: Page Inventory

| Stage | URL | Persona | Epic/Story |
|-------|-----|---------|-----------|
| 1 | `/` | All (public) | Landing page (new story) |
| 2 | `/auth/signup` | New customer | Epic 1.2a |
| 2 | `/auth/login` | Returning customer | Epic 1.2a |
| 2 | `/auth/forgot-password` | Returning customer | Epic 1.2b |
| 3 | `/billing/plans` | New/upgrading customer | Epic 2.1 |
| 3 | `/billing/checkout-success` | New customer | Epic 2.2 |
| 3 | `/billing/upgrade` | Active customer | Epic 4.5 |
| 4 | `/onboarding` | New customer (multi-step) | Epic 3.1, 3.2 |
| 5 | `/dashboard` | Active customer | Epic 4.1-4.5 |
| 5 | `/settings` | Active customer | Future |
| 5 | `/support` | Active customer | Future |
| Admin | `/admin/customers` | Internal admin | Epic 5.1 |
| Admin | `/admin/customers/:tenant_id` | Internal admin | Epic 5.2, 5.3 |
| Operator | `/` (local) | Operator | Existing `ux-design.md` |

---

**END OF CUSTOMER JOURNEY UX SPECIFICATION**


---
date: 2026-05-09
status: All 15 gaps fixed
---

# User Journey Validation Fixes Applied

## Summary

All 15 critical gaps identified in the user journey validation have been fixed across 4 documents:

1. **UX Design** (NEW): `ux-design-saas-v1.md` — Complete customer journey specification
2. **Architecture** (UPDATED): `architecture-whatsapp-ai-bot-saas-v1.md` — Multi-role auth & Stripe flow
3. **PRD** (UPDATED): `prd-whatsapp-ai-bot-saas-v1.md` — Scope clarifications
4. **Epics** (UPDATED): `epics-saas-v1.md` — Complete story acceptance criteria

---

## Gaps Fixed

### ✅ GAP-1: Public Landing Page (Discovery)
**Fixed in:** `ux-design-saas-v1.md` § 2  
**What:** Complete landing page design with hero, features (3 cards), pricing table, CTA, social proof  
**Acceptance Criteria:** Section 2.2 defines all required elements  
**Story:** New story needed: "Create Landing Page" (out of scope for Epic 1-6, recommend as pre-launch P0)

---

### ✅ GAP-2: Signup Form UX Design
**Fixed in:** `ux-design-saas-v1.md` § 3  
**What:** Form layout with fields (email, password, business name, segment), validation errors, password strength  
**Acceptance Criteria:** Section 3.2 specifies all fields and validation rules  
**Story:** Epic 1.2a updated with complete form field specs

---

### ✅ GAP-3: Signup Form Data Collection
**Fixed in:** `prd-whatsapp-ai-bot-saas-v1.md` § P0-R1 + `epics-saas-v1.md` § Story 1.2a  
**What:** Clarified that business name is collected at signup (used for bot branding); segment is optional  
**Acceptance Criteria:** Story 1.2a AC specifies exact fields: email, password, business_name (required), business_segment (optional)

---

### ✅ GAP-4: Billing Page UX Design
**Fixed in:** `ux-design-saas-v1.md` § 4  
**What:** Plan card layout (3-column grid desktop/stacked mobile), feature matrix, auto-renewal checkbox, Stripe flow  
**Acceptance Criteria:** Sections 4.1-4.4 define layout, plan details, and checkout flow (v1 = redirect, P1 = embedded)  
**Story:** Epic 2.1 updated with complete UX acceptance criteria

---

### ✅ GAP-5: Billing Page Payment Method
**Fixed in:** `architecture-whatsapp-ai-bot-saas-v1.md` § ADR-008  
**What:** Specified v1 uses Stripe-hosted checkout (redirect), P1 considers embedded Payment Element  
**Decision:** ADR-008 formalizes the choice and rationale

---

### ✅ GAP-6: Billing Page Trial/Promo Logic
**Fixed in:** `prd-whatsapp-ai-bot-saas-v1.md` § Business Model  
**What:** Clarified v1 has NO free trial or promo codes; immediate payment required  
**Scope:** Trial/promos are P1 considerations, noted as out-of-scope for v1

---

### ✅ GAP-7: Onboarding Wizard Flow UX Design
**Fixed in:** `ux-design-saas-v1.md` § 5  
**What:** Complete 4-step wizard design (QR, Name Bot, AI Persona, Completion) with step indicators, real-time status, examples  
**Acceptance Criteria:** Sections 5.1-5.5 define all 4 steps, UX patterns, and edge cases  
**Story:** Epic 3.1 updated to encompass full 4-step wizard (was previously only QR + status)

---

### ✅ GAP-8: Onboarding Step 2 (Name Bot) Scope
**Fixed in:** `epics-saas-v1.md` § Story 3.1 § Step 2  
**What:** Clarified "Name your bot" is PART OF onboarding wizard (not post-onboarding config)  
**Scope:** Steps 2-3 are collected during onboarding; post-onboarding dashboard (Story 4.2) allows updates

---

### ✅ GAP-9: Onboarding Step 3 (Auto-Responses Config) Scope
**Fixed in:** `epics-saas-v1.md` § Story 3.1 § Step 3  
**What:** "Configure AI Persona" (Step 3) is v1 scope, optional but recommended; not "auto-responses" (which implies complex rules)  
**Scope:** v1 collects persona prompt; complex rules/workflows are P1+

---

### ✅ GAP-10: Customer Dashboard UX Design (CRITICAL)
**Fixed in:** `ux-design-saas-v1.md` § 6  
**What:** Complete customer dashboard design (NOT operator dashboard) covering: status, usage progress, config, upgrade CTA, support  
**Acceptance Criteria:** Sections 6.1-6.5 define layout, sections, blocked state, and mobile responsiveness  
**Note:** Original `ux-design.md` was operator-focused; new `ux-design-saas-v1.md` covers customer personas

---

### ✅ GAP-11: Landing Page → Signup Redirect
**Fixed in:** `ux-design-saas-v1.md` § 2.2 AC  
**What:** Landing page CTA ["Get Started"] redirects to `/auth/signup`  
**Scope:** Landing page can be external or Flask-served; linkage is specified

---

### ✅ GAP-12: Signup → Billing Redirect
**Fixed in:** `epics-saas-v1.md` § Story 1.2a AC  
**What:** Signup success redirects to `/billing/plans`  
**Implementation:** Single-page form or multi-page funnel — both redirect to `/billing/plans` on success

---

### ✅ GAP-13: Billing → Onboarding Redirect
**Fixed in:** `epics-saas-v1.md` § Story 2.1 AC  
**What:** After Stripe webhook confirms payment (Story 2.2), user is redirected to `/onboarding`  
**Timing:** After Story 2.2 webhook processes, user sees confirmation page, then auto-redirects to `/onboarding`

---

### ✅ GAP-14: Onboarding → Dashboard Redirect
**Fixed in:** `ux-design-saas-v1.md` § 5.4 + `epics-saas-v1.md` § Story 3.1 AC  
**What:** After all 4 onboarding steps complete, [Go to Dashboard] redirects to `/dashboard`  
**No intermediate screen:** Direct redirect (celebration screen IS the completion screen)

---

### ✅ GAP-15: Operator vs. Customer Dashboard
**Fixed in:** `architecture-whatsapp-ai-bot-saas-v1.md` § ADR-006 (Multi-Role Support)  
**What:** Single Flask app serves both customer and admin dashboards; auth model uses `role` field in session  
**Routing:** 
- Customer login (`role = 'customer'`) → `/dashboard` (customer UI)
- Admin login (`role = 'admin'`) → `/admin/customers` (admin UI)
- Role determined at login: admin users in config; others default to customer
- Decorator pattern: `@require_role('customer')` guards customer routes; `@require_role('admin')` guards admin routes

---

## Documents Updated

### 1. **ux-design-saas-v1.md** (NEW, 800+ lines)
**Covers:** Complete 5-stage customer journey with wireframes, AC, visual design system  
**Key Sections:**
- § 1: User context & 5-stage journey map
- § 2: Landing page design (hero, features, pricing, social proof)
- § 3: Signup form (email, password, business name, segment)
- § 4: Billing page (plan cards, Stripe flow, portal link)
- § 5: Onboarding wizard (4-step flow with UX patterns)
- § 6: Customer dashboard (connection, usage, config, settings)
- § 7-10: Shared patterns, validation, accessibility, testing plan
- **Appendix A:** Page inventory (all URLs mapped to stories)

### 2. **architecture-whatsapp-ai-bot-saas-v1.md** (UPDATED)
**Changes:**
- ADR-006: Enhanced Flask-Login with multi-role support (customer vs. admin)
- ADR-008: Stripe checkout flow decision (v1 redirect, P1 embedded)
- Session carries `user_id`, `tenant_id`, and `role`
- Role-based redirect: customer → `/dashboard`, admin → `/admin/customers`

### 3. **prd-whatsapp-ai-bot-saas-v1.md** (UPDATED)
**Changes:**
- P0-R1: Clarified signup collects business_name + optional segment; multi-role login
- Business Model: Added trial/promo (NO for v1), landing page scope
- In Scope: Added public landing page
- Out of Scope: Clarified free trials, promo codes, segment analytics

### 4. **epics-saas-v1.md** (UPDATED)
**Changes:**
- Story 1.2a: Complete form field specs, multi-role routing, password strength rules, validation errors
- Story 2.1: Complete plan card design, Stripe checkout flow, billing portal, error handling
- Story 3.1: Comprehensive 4-step onboarding wizard (was 2 steps, now 4 with bot naming & AI persona)
- All stories now reference [ux-design-saas-v1.md](ux-design-saas-v1.md) for UX specifications

---

## Next Steps

### For Implementation:
1. **Epic 1 (Auth & Foundation):** Ready to start (all AC complete)
2. **Epic 2 (Billing):** Ready to start (all AC complete, Stripe flow specified)
3. **Epic 3 (Onboarding):** Ready to start (4-step wizard fully designed)
4. **Epic 4-6:** No changes needed; existing AC remain valid

### For Pre-Launch:
- **Landing Page Story:** New story needed (outside Epic 1-6) to build public landing page
  - Owner: Product/Marketing or Engineering (if internal)
  - UX spec: [ux-design-saas-v1.md § 2](ux-design-saas-v1.md#2-stage-1-public-landing-page)

### For QA/Testing:
- New [ux-design-saas-v1.md § 9 (Validation & Testing Plan)](ux-design-saas-v1.md#9-validation--testing-plan) provides usability, accessibility, and performance test cases

---

## Metrics Impact

| Metric | Spec | Status |
|--------|------|--------|
| SM-1: Signup-to-live ≤ 10 min | Now fully traceable through 5-stage journey | ✅ Complete |
| SM-2: Onboarding ≥ 70% | 4-step wizard with step tracking | ✅ Complete |
| SM-4: Paid conversion ≥ 20% | Landing → Signup → Billing funnel specified | ✅ Complete |
| SM-5-9: Other metrics | Dashboard & enforcement AC complete | ✅ Complete |

---

## Files Ready for Developer Handoff

All files are in `_bmad-output/planning-artifacts/`:
- ✅ [ux-design-saas-v1.md](ux-design-saas-v1.md) — **NEW** customer journey UX spec
- ✅ [architecture-whatsapp-ai-bot-saas-v1.md](architecture-whatsapp-ai-bot-saas-v1.md) — Updated with auth/Stripe decisions
- ✅ [prd-whatsapp-ai-bot-saas-v1.md](prd-whatsapp-ai-bot-saas-v1.md) — Updated with scope clarifications
- ✅ [epics-saas-v1.md](epics-saas-v1.md) — Updated with complete story AC

**All gaps closed. Ready to implement Epic 1 → 6 in sequence.**

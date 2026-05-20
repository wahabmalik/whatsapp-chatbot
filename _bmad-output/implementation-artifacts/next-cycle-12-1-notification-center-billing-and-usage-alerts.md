# Story 12.1 — Notification Center (Billing and Usage Alerts)

**Status:** ready-for-dev  
**Type:** feature / saas  
**Priority:** P1  
**Sprint:** 3 (conditional)  
**Story ID:** next-cycle-12-1  
**Epic:** Epic 12 — SaaS v1 Customer Value Pull  
**Depends on:** next-cycle-10-2 (Dashboard Analytics v1), next-cycle-11-2 (SQLite Rollback Drill)  
**Pull Condition:** Gate B + Gate C both complete AND full regression suite remains green  

---

## Problem Statement

Operators have no in-app alerts for billing events (trial expiry, payment failure) or usage thresholds. They discover problems after impact:
- Trial ends without warning → service suspension
- Payment fails silently → revenue churn risk
- Usage threshold breached → capacity runaway with no operator awareness

This creates a poor customer experience and increases support escalations.

---

## Solution Overview

Implement a **Notification Center** that delivers:

1. **Billing Alerts** (Stripe webhook-driven):
   - Trial expiry warnings (7-day, 1-day before end)
   - Payment failure alerts (immediate on invoice.payment_failed)

2. **Usage Alerts** (Analytics-driven):
   - Usage threshold warnings (configurable % of monthly conversation limit)
   - Computed from conversation_analytics_events with tenant isolation

3. **Persistence & UX**:
   - Notifications stored per tenant in `tenant_notifications` table
   - Individual dismissal with persistence across page reloads
   - Tenant-isolated display (no cross-tenant leakage)

---

## Acceptance Criteria

- **AC 12.1.1:** Notification center panel displays: trial expiry warnings (7-day, 1-day), payment failure alerts, and usage threshold warnings (configurable % of plan limit).
  - Supports configurable thresholds (default: 80%, configurable per environment or per plan)
  - Trial warnings compute remaining days dynamically from subscription period_end
  - Payment alerts triggered immediately on Stripe invoice.payment_failed event

- **AC 12.1.2:** Notifications are persisted per tenant and dismissed individually; dismissal survives page reload.
  - Database-backed using `TenantNotification` model
  - Each notification has unique `notification_key` per (tenant_id, notification_key) pair
  - Dismissal sets `dismissed_at` timestamp; active notifications have `dismissed_at IS NULL`
  - No dismissal on page reload (idempotent load-time behavior)

- **AC 12.1.3:** Billing alerts are triggered by Stripe webhook events (existing Stripe integration); no polling.
  - Webhook handler calls `create_stripe_billing_notifications()` in same transaction as webhook processing
  - Events: `invoice.payment_failed`, `customer.subscription.updated` (for trial status changes)
  - Event deduplication via `notification_key` uniqueness constraint

- **AC 12.1.4:** Usage threshold alerts are computed from conversation analytics event counts (Story 10.1 data).
  - Pulls from `conversation_analytics_events.jsonl` (existing analytics store)
  - Filters by tenant_id + current billing period start date
  - Counts unique conversation_key values as proxy for conversation volume
  - Computed on-demand via `sync_usage_threshold_notifications()` called on dashboard page load

- **AC 12.1.5:** Notifications are tenant-isolated — no cross-tenant leakage.
  - All queries include `tenant_id` filter
  - TenantNotification model has `tenant_id` foreign key + index
  - Unique constraint enforces tenant_id + notification_key uniqueness
  - Dashboard API enforces current_tenant_id via session context

---

## Out of Scope

- Email/SMS delivery (notification delivery channel is the dashboard only)
- Push notifications (browser notifications are not in scope)
- Admin-broadcast notification type (only auto-generated alerts in Sprint 3)
- Notification scheduling/delay (all alerts are immediate)
- Multi-language notifications (English only for v1)

---

## Architecture & Implementation Strategy

### 1. Database Layer

**Table: `tenant_notifications`** (already modeled in `app/models/__init__.py`)

```python
class TenantNotification(Base):
    __tablename__ = "tenant_notifications"

    id = Column(String(36), primary_key=True, default=new_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False, index=True)
    
    # Alert classification
    category = Column(String(50), nullable=False)  # "billing" | "usage"
    alert_type = Column(String(100), nullable=False)  # "payment_failed", "trial_expiry_7d", "trial_expiry_1d", "usage_threshold_80"
    severity = Column(String(20), nullable=False, default="info")  # "info", "warning", "error"
    
    # Display content
    title = Column(String(255), nullable=False)  # e.g., "Payment failure detected"
    message = Column(Text, nullable=False)  # e.g., "A recent invoice payment failed..."
    
    # Deduplication
    notification_key = Column(String(255), nullable=False)  # e.g., "billing:payment_failed:evt_123abc"
    
    # Extensibility
    details_json = Column(Text, nullable=True)  # {"stripe_event_id": "...", "subscription_id": "..."}
    
    # Lifecycle
    dismissed_at = Column(DateTime(timezone=True), nullable=True)  # NULL = active, set = dismissed
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    tenant = relationship("Tenant", back_populates="notifications")

    __table_args__ = (
        UniqueConstraint("tenant_id", "notification_key", 
                        name="uq_tenant_notifications_tenant_key"),
        Index("idx_tenant_notifications_active", "tenant_id", "dismissed_at", "created_at"),
    )
```

**Indexes:**
- PK on `id`
- FK index on `tenant_id`
- Composite index on `(tenant_id, dismissed_at, created_at)` for efficient active notification queries

**Migrations:**
- If table doesn't exist: Create `tenant_notifications` table (add migration if using Alembic)
- If adding `category` column: Add with default "billing" for backcompat

---

### 2. Service Layer

**File: `app/services/notification_center.py`**

Already partially implemented with these functions:

#### `create_stripe_billing_notifications(sess, *, event: Any, stripe_event_id: str) -> int`

Called from Stripe webhook handler. Creates notification records from Stripe events.

**Events handled:**
- `invoice.payment_failed`: Creates "payment_failed" alert
- `customer.subscription.updated`: Evaluates trial status and creates "trial_expiry_7d" / "trial_expiry_1d" alerts

**Deduplication:**
- Uses `_upsert_tenant_notification()` helper which checks for existing `(tenant_id, notification_key)` pair
- If exists: returns False (no new notification created)
- If not exists: creates new row, commits, returns True

**Error handling:**
- Missing `tenant_id` in webhook metadata: returns 0 (skipped)
- Invalid subscription data: skipped with defensive checks
- Database errors: allowed to propagate (webhook handler should retry)

#### `sync_usage_threshold_notifications(app, db, tenant_id: str) -> int`

Called on operator dashboard page load (or via background sync). Computes usage from analytics.

**Logic:**
1. Load tenant's subscription record (latest by updated_at)
2. If no subscription or `conversation_limit <= 0`: return 0 (no limits to check)
3. Load configured thresholds: `USAGE_ALERT_THRESHOLD_PCTS` env var (comma-separated, default "80")
4. Get analytics events from retention store (Story 10.1 backend)
5. Filter by tenant_id + created within current billing period
6. Count unique `conversation_key` values (each inbound message starts a conversation)
7. For each threshold: if `(used / limit) * 100 >= threshold` and no existing notification: create one
8. Return count of new notifications created

**Thresholds:**
- Config: `USAGE_ALERT_THRESHOLD_PCTS` (env var)
- Format: "80" or "50,75,90" (comma-separated integers)
- Coercion: Skip non-integers, skip values outside 1-100 range
- Default: [80] if empty or missing

**Severity:**
- threshold < 100: "warning"
- threshold >= 100: "error"

#### `list_tenant_notifications(db, tenant_id: str) -> list[dict[str, Any]]`

Fetches active (non-dismissed) notifications for a tenant.

**Query:**
```sql
SELECT * FROM tenant_notifications
WHERE tenant_id = ? AND dismissed_at IS NULL
ORDER BY created_at DESC
```

**Returns:**
List of dicts with keys: id, category, alert_type, severity, title, message, created_at, details (parsed JSON)

#### `dismiss_tenant_notification(db, tenant_id: str, notification_id: str) -> bool`

Marks a notification as dismissed (sets `dismissed_at` to current UTC time).

**Validation:**
- Verify notification exists and belongs to tenant_id (prevent cross-tenant manipulation)
- If already dismissed: idempotent (return True)
- If not found or wrong tenant: return False

**Returns:**
- True if dismissed (new or already dismissed)
- False if not found or tenant mismatch

---

### 3. Webhook Integration

**File: `app/views.py`**

Modify existing Stripe webhook handler (around line 350-450).

**Current flow:**
```python
@webhook_blueprint.post("/webhook")
def webhook_post():
    # Validate signature
    # Parse event
    # Route to handler (customer.subscription.updated, invoice.payment_failed, etc.)
    # Return 200 OK
```

**Modification:**
After processing existing webhook logic, inject notification creation:

```python
@webhook_blueprint.post("/webhook")
def webhook_post():
    # ... existing signature validation and event parsing ...
    
    # NEW: Create billing notifications from event
    if hasattr(event, 'get'):
        event_type = event.get('type', '')
        if event_type in ('invoice.payment_failed', 'customer.subscription.updated'):
            try:
                sess = db.session()
                created = create_stripe_billing_notifications(
                    sess, 
                    event=event, 
                    stripe_event_id=event.get('id', 'unknown')
                )
                sess.commit()
                app.logger.info(f"Created {created} billing notification(s) from Stripe event")
            except Exception as e:
                sess.rollback()
                app.logger.error(f"Failed to create billing notifications: {e}")
            finally:
                sess.close()
    
    return {"status": "ok"}, 200
```

---

### 4. API Layer

**File: `app/views_dashboard.py`**

Add two API endpoints to `dashboard_api` blueprint:

#### `GET /api/notifications`

Fetch active notifications for current operator's tenant.

**Handler:**
```python
@dashboard_api.get("/api/notifications")
@require_operator_auth
def get_notifications():
    """List active notifications for current tenant."""
    tenant_id = current_tenant_id()
    try:
        notifications = list_tenant_notifications(db, tenant_id)
        return {"notifications": notifications, "count": len(notifications)}, 200
    except Exception as e:
        app.logger.error(f"Error fetching notifications: {e}")
        return {"error": "Unable to fetch notifications"}, 500
```

**Response:**
```json
{
  "notifications": [
    {
      "id": "notif_uuid",
      "category": "billing",
      "alert_type": "trial_expiry_7d",
      "severity": "warning",
      "title": "Trial ends soon",
      "message": "Your trial period ends in 7 day(s).",
      "created_at": "2026-05-18T14:30:00+00:00",
      "details": {
        "stripe_event_id": "evt_...",
        "subscription_id": "sub_...",
        "days_remaining": 7
      }
    },
    {
      "id": "notif_uuid_2",
      "category": "usage",
      "alert_type": "usage_threshold_80",
      "severity": "warning",
      "title": "Usage reached 80%",
      "message": "You have used 800 of 1000 monthly conversations (80.0%).",
      "created_at": "2026-05-17T10:15:00+00:00",
      "details": {
        "threshold_pct": 80,
        "conversations_used": 800,
        "conversation_limit": 1000,
        "usage_percent": 80.0
      }
    }
  ],
  "count": 2
}
```

**Status codes:**
- 200: Success (may return empty list)
- 401: Not authenticated
- 403: Not operator role
- 500: Server error

#### `POST /api/notifications/<notification_id>/dismiss`

Dismiss (mark as read) a specific notification.

**Handler:**
```python
@dashboard_api.post("/api/notifications/<notification_id>/dismiss")
@require_operator_auth
def dismiss_notification(notification_id):
    """Dismiss a notification for current tenant."""
    tenant_id = current_tenant_id()
    try:
        success = dismiss_tenant_notification(db, tenant_id, notification_id)
        if success:
            return {"status": "dismissed"}, 200
        else:
            return {"error": "Notification not found or already dismissed"}, 404
    except Exception as e:
        app.logger.error(f"Error dismissing notification: {e}")
        return {"error": "Unable to dismiss notification"}, 500
```

**Response:**
```json
{
  "status": "dismissed"
}
```

**Status codes:**
- 200: Dismissed (idempotent)
- 401: Not authenticated
- 403: Not operator role
- 404: Not found or already dismissed
- 500: Server error

---

### 5. Frontend Layer

**File: `app/templates/dashboard.html`**

Add a notification center panel to the operator dashboard.

**HTML Structure:**
```html
<!-- Notification Center Panel (top of dashboard, persistent) -->
<section id="notification-center" class="notification-center">
  <div class="notification-header">
    <h3>Alerts</h3>
    <button id="notification-close-btn" class="close-btn" aria-label="Close alerts">×</button>
  </div>
  
  <div id="notification-list" class="notification-list">
    <!-- Populated via JavaScript -->
  </div>
  
  <div id="notification-empty" class="notification-empty" style="display: none;">
    <p>No active alerts</p>
  </div>
</section>

<!-- Notification Badge (in header) -->
<div id="notification-badge" class="notification-badge" style="display: none;">
  <span id="notification-count" class="badge-count">0</span>
  <span class="badge-label">Alerts</span>
</div>
```

**CSS Classes** (in `app/static/css/dashboard.css`):
```css
.notification-center {
  background: #f9f9f9;
  border: 1px solid #e0e0e0;
  border-radius: 4px;
  padding: 16px;
  margin-bottom: 24px;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.08);
}

.notification-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.notification-header h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: #333;
}

.notification-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.notification-item {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  padding: 12px;
  border-radius: 4px;
  border-left: 4px solid;
  background: white;
}

.notification-item.severity-error {
  border-left-color: #d32f2f;
  background: #ffebee;
}

.notification-item.severity-warning {
  border-left-color: #f57c00;
  background: #fff3e0;
}

.notification-item.severity-info {
  border-left-color: #1976d2;
  background: #e3f2fd;
}

.notification-item-content {
  flex: 1;
}

.notification-item-title {
  font-weight: 600;
  font-size: 14px;
  margin: 0 0 4px 0;
  color: #333;
}

.notification-item-message {
  font-size: 13px;
  margin: 0;
  color: #666;
  line-height: 1.4;
}

.notification-item-dismiss {
  margin-left: 12px;
  background: none;
  border: none;
  color: #999;
  cursor: pointer;
  font-size: 18px;
  padding: 0;
  line-height: 1;
}

.notification-item-dismiss:hover {
  color: #333;
}

.notification-empty {
  text-align: center;
  color: #999;
  padding: 16px;
  font-size: 13px;
}

.notification-badge {
  display: inline-block;
  background: #d32f2f;
  color: white;
  border-radius: 12px;
  padding: 4px 8px;
  font-size: 12px;
  font-weight: 600;
}

.badge-count {
  margin-right: 4px;
}
```

**JavaScript** (inline or in `app/static/js/notifications.js`):
```javascript
// Initialize notification center on page load
document.addEventListener('DOMContentLoaded', async () => {
  await loadNotifications();
  // Refresh every 30 seconds
  setInterval(loadNotifications, 30000);
});

async function loadNotifications() {
  try {
    const response = await fetch('/api/notifications');
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    
    const data = await response.json();
    renderNotifications(data.notifications);
  } catch (error) {
    console.error('Failed to load notifications:', error);
  }
}

function renderNotifications(notifications) {
  const listEl = document.getElementById('notification-list');
  const emptyEl = document.getElementById('notification-empty');
  const badgeEl = document.getElementById('notification-badge');
  const countEl = document.getElementById('notification-count');
  
  if (notifications.length === 0) {
    listEl.innerHTML = '';
    emptyEl.style.display = 'block';
    badgeEl.style.display = 'none';
    return;
  }
  
  emptyEl.style.display = 'none';
  badgeEl.style.display = 'inline-block';
  countEl.textContent = notifications.length;
  
  listEl.innerHTML = notifications.map(n => `
    <div class="notification-item severity-${n.severity}">
      <div class="notification-item-content">
        <div class="notification-item-title">${escapeHtml(n.title)}</div>
        <div class="notification-item-message">${escapeHtml(n.message)}</div>
      </div>
      <button class="notification-item-dismiss" 
              onclick="dismissNotification('${n.id}')" 
              aria-label="Dismiss">×</button>
    </div>
  `).join('');
}

async function dismissNotification(notificationId) {
  try {
    const response = await fetch(`/api/notifications/${notificationId}/dismiss`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    });
    
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    
    // Reload to reflect dismissal
    await loadNotifications();
  } catch (error) {
    console.error('Failed to dismiss notification:', error);
  }
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}
```

---

### 6. Dashboard Page Load Hook

**File: `app/views_dashboard.py`**

Modify operator dashboard route to sync usage threshold notifications on each load:

```python
@dashboard_blueprint.route("/dashboard/operator")
@require_operator_auth
def operator_dashboard():
    """Operator dashboard page."""
    tenant_id = current_tenant_id()
    
    # Sync usage threshold notifications before rendering
    try:
        created = sync_usage_threshold_notifications(current_app, db, tenant_id)
        if created > 0:
            current_app.logger.info(f"Created {created} usage threshold notifications")
    except Exception as e:
        current_app.logger.error(f"Error syncing usage notifications: {e}")
        # Non-fatal: continue to render dashboard
    
    # ... render dashboard template ...
    return render_template('dashboard.html', ...)
```

---

## Test Strategy

### Unit Tests

**File: `tests/test_story_12_1_notification_center.py`**

#### Test Suite 1: Notification Persistence

```python
def test_tenant_notification_creation_idempotent():
    """Same notification_key → only one record created."""
    sess = db.session()
    result1 = _upsert_tenant_notification(
        sess,
        tenant_id="tenant1",
        category="billing",
        alert_type="payment_failed",
        severity="error",
        title="Payment failed",
        message="...",
        notification_key="billing:payment_failed:evt_abc"
    )
    assert result1 is True
    
    result2 = _upsert_tenant_notification(
        sess,
        tenant_id="tenant1",
        category="billing",
        alert_type="payment_failed",
        severity="error",
        title="Payment failed",
        message="...",
        notification_key="billing:payment_failed:evt_abc"
    )
    assert result2 is False
    
    sess.close()

def test_tenant_notification_dismissal_idempotent():
    """Dismissing twice is safe."""
    sess = db.session()
    # Create notification
    notif = TenantNotification(
        tenant_id="tenant1",
        category="billing",
        alert_type="payment_failed",
        severity="error",
        title="Payment failed",
        message="...",
        notification_key="billing:payment_failed:evt_xyz"
    )
    sess.add(notif)
    sess.commit()
    notif_id = notif.id
    
    # Dismiss
    dismiss_tenant_notification(db, "tenant1", notif_id)
    
    # Dismiss again
    success = dismiss_tenant_notification(db, "tenant1", notif_id)
    assert success is True
    
    sess.close()

def test_tenant_isolation_dismiss():
    """Cannot dismiss another tenant's notification."""
    sess = db.session()
    # Create as tenant1
    notif = TenantNotification(
        tenant_id="tenant1",
        category="billing",
        alert_type="trial_expiry_7d",
        severity="warning",
        title="Trial ends",
        message="...",
        notification_key="billing:trial_expiry_7d:sub_123:2026-05-25"
    )
    sess.add(notif)
    sess.commit()
    notif_id = notif.id
    
    # Try dismiss as tenant2
    success = dismiss_tenant_notification(db, "tenant2", notif_id)
    assert success is False
    
    sess.close()
```

#### Test Suite 2: Billing Alert Creation from Stripe Events

```python
def test_create_stripe_billing_notifications_payment_failed():
    """invoice.payment_failed → payment_failed alert."""
    sess = db.session()
    
    event = {
        'type': 'invoice.payment_failed',
        'id': 'evt_payment_failed_123',
        'data': {
            'object': {
                'subscription': 'sub_xyz',
                'metadata': {'tenant_id': 'tenant_billing_1'}
            }
        }
    }
    
    created = create_stripe_billing_notifications(sess, event=event, stripe_event_id='evt_payment_failed_123')
    assert created == 1
    
    # Verify notification record exists
    notif = sess.query(TenantNotification).filter(
        TenantNotification.tenant_id == 'tenant_billing_1',
        TenantNotification.alert_type == 'payment_failed'
    ).first()
    assert notif is not None
    assert notif.severity == 'error'
    assert 'Payment failure' in notif.title
    
    sess.close()

def test_create_stripe_billing_notifications_trial_7d():
    """Trial ending in 7 days → trial_expiry_7d alert."""
    sess = db.session()
    
    from datetime import datetime, timezone, timedelta
    
    period_end = datetime.now(timezone.utc) + timedelta(days=6, hours=12)  # 6.5 days away
    
    event = {
        'type': 'customer.subscription.updated',
        'id': 'evt_trial_7d_123',
        'data': {
            'object': {
                'status': 'trialing',
                'current_period_end': period_end.timestamp(),
                'metadata': {'tenant_id': 'tenant_trial_1'}
            }
        }
    }
    
    created = create_stripe_billing_notifications(sess, event=event, stripe_event_id='evt_trial_7d_123')
    assert created >= 1  # Should create trial_expiry_7d alert
    
    notif = sess.query(TenantNotification).filter(
        TenantNotification.tenant_id == 'tenant_trial_1',
        TenantNotification.alert_type == 'trial_expiry_7d'
    ).first()
    assert notif is not None
    
    sess.close()

def test_create_stripe_billing_notifications_trial_1d():
    """Trial ending in < 24 hours → trial_expiry_1d alert."""
    sess = db.session()
    
    from datetime import datetime, timezone, timedelta
    
    period_end = datetime.now(timezone.utc) + timedelta(hours=12)  # 12 hours away
    
    event = {
        'type': 'customer.subscription.updated',
        'id': 'evt_trial_1d_123',
        'data': {
            'object': {
                'status': 'trialing',
                'current_period_end': period_end.timestamp(),
                'metadata': {'tenant_id': 'tenant_trial_2'}
            }
        }
    }
    
    created = create_stripe_billing_notifications(sess, event=event, stripe_event_id='evt_trial_1d_123')
    
    notif = sess.query(TenantNotification).filter(
        TenantNotification.tenant_id == 'tenant_trial_2',
        TenantNotification.alert_type == 'trial_expiry_1d'
    ).first()
    assert notif is not None
    assert notif.severity == 'error'
    
    sess.close()

def test_stripe_event_missing_tenant_id():
    """Event without tenant_id metadata → skipped."""
    sess = db.session()
    
    event = {
        'type': 'invoice.payment_failed',
        'id': 'evt_no_tenant',
        'data': {
            'object': {
                'subscription': 'sub_xyz',
                'metadata': {}  # No tenant_id
            }
        }
    }
    
    created = create_stripe_billing_notifications(sess, event=event, stripe_event_id='evt_no_tenant')
    assert created == 0
    
    sess.close()
```

#### Test Suite 3: Usage Threshold Notifications

```python
def test_sync_usage_threshold_notifications_simple():
    """100 conversations, 80% threshold, 1000 limit → alert created."""
    app = create_test_app()
    
    # Create subscription
    tenant_id = "tenant_usage_1"
    sub = Subscription(
        tenant_id=tenant_id,
        conversation_limit=1000,
        current_period_start=datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    )
    sess = db.session()
    sess.add(sub)
    sess.commit()
    
    # Create 100 analytics events (different conversation_keys)
    with open(app.config['ANALYTICS_EVENT_STORE_PATH'], 'w') as f:
        for i in range(100):
            event = {
                'tenant_id': tenant_id,
                'conversation_key': f'conv_{i:04d}',
                'stage': 'inbound_receive',
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
            f.write(json.dumps(event) + '\n')
    
    # Sync notifications
    app.config['USAGE_ALERT_THRESHOLD_PCTS'] = '80'
    created = sync_usage_threshold_notifications(app, db, tenant_id)
    assert created == 1  # 80% alert created
    
    # Verify
    notif = sess.query(TenantNotification).filter(
        TenantNotification.tenant_id == tenant_id,
        TenantNotification.alert_type == 'usage_threshold_80'
    ).first()
    assert notif is not None
    assert 'Usage reached 80%' in notif.title
    details = json.loads(notif.details_json)
    assert details['conversations_used'] == 100
    assert details['conversation_limit'] == 1000
    
    sess.close()

def test_sync_usage_threshold_multiple_thresholds():
    """Usage at 90% with thresholds 80,90 → both alerts created."""
    app = create_test_app()
    
    tenant_id = "tenant_usage_multi"
    sub = Subscription(
        tenant_id=tenant_id,
        conversation_limit=1000,
        current_period_start=datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    )
    sess = db.session()
    sess.add(sub)
    sess.commit()
    
    # 900 conversations (90% of 1000)
    with open(app.config['ANALYTICS_EVENT_STORE_PATH'], 'w') as f:
        for i in range(900):
            event = {
                'tenant_id': tenant_id,
                'conversation_key': f'conv_{i:04d}',
                'stage': 'inbound_receive',
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
            f.write(json.dumps(event) + '\n')
    
    app.config['USAGE_ALERT_THRESHOLD_PCTS'] = '80,90'
    created = sync_usage_threshold_notifications(app, db, tenant_id)
    assert created == 2  # Both 80% and 90% alerts
    
    sess.close()

def test_sync_usage_threshold_filters_old_events():
    """Events before billing period start → excluded."""
    app = create_test_app()
    
    tenant_id = "tenant_usage_old"
    period_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    sub = Subscription(
        tenant_id=tenant_id,
        conversation_limit=100,
        current_period_start=period_start
    )
    sess = db.session()
    sess.add(sub)
    sess.commit()
    
    # Old event (yesterday)
    old_date = (period_start - timedelta(days=1)).isoformat()
    # New event (today)
    new_date = datetime.now(timezone.utc).isoformat()
    
    with open(app.config['ANALYTICS_EVENT_STORE_PATH'], 'w') as f:
        f.write(json.dumps({
            'tenant_id': tenant_id,
            'conversation_key': 'conv_old',
            'stage': 'inbound_receive',
            'timestamp': old_date
        }) + '\n')
        f.write(json.dumps({
            'tenant_id': tenant_id,
            'conversation_key': 'conv_new',
            'stage': 'inbound_receive',
            'timestamp': new_date
        }) + '\n')
    
    app.config['USAGE_ALERT_THRESHOLD_PCTS'] = '80'
    created = sync_usage_threshold_notifications(app, db, tenant_id)
    assert created == 0  # Only 1 conversation in period (1% < 80%)
    
    sess.close()

def test_sync_usage_threshold_tenant_isolated():
    """Only counts events for specific tenant_id."""
    app = create_test_app()
    
    tenant1 = "tenant_iso_1"
    tenant2 = "tenant_iso_2"
    period_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    sub1 = Subscription(tenant_id=tenant1, conversation_limit=100, current_period_start=period_start)
    sub2 = Subscription(tenant_id=tenant2, conversation_limit=100, current_period_start=period_start)
    sess = db.session()
    sess.add(sub1)
    sess.add(sub2)
    sess.commit()
    
    # 50 events for tenant1, 50 for tenant2
    with open(app.config['ANALYTICS_EVENT_STORE_PATH'], 'w') as f:
        for i in range(50):
            f.write(json.dumps({
                'tenant_id': tenant1,
                'conversation_key': f'conv_t1_{i:04d}',
                'stage': 'inbound_receive',
                'timestamp': datetime.now(timezone.utc).isoformat()
            }) + '\n')
        for i in range(50):
            f.write(json.dumps({
                'tenant_id': tenant2,
                'conversation_key': f'conv_t2_{i:04d}',
                'stage': 'inbound_receive',
                'timestamp': datetime.now(timezone.utc).isoformat()
            }) + '\n')
    
    app.config['USAGE_ALERT_THRESHOLD_PCTS'] = '80'
    
    # Sync for tenant1: should NOT alert (only 50%)
    created1 = sync_usage_threshold_notifications(app, db, tenant1)
    assert created1 == 0
    
    # Sync for tenant2: should NOT alert (only 50%)
    created2 = sync_usage_threshold_notifications(app, db, tenant2)
    assert created2 == 0
    
    sess.close()
```

#### Test Suite 4: API Endpoints

```python
def test_get_notifications_api_lists_active():
    """GET /api/notifications returns active notifications."""
    app = create_test_app()
    client = app.test_client()
    
    with app.app_context():
        # Create notifications
        sess = db.session()
        notif1 = TenantNotification(
            tenant_id="test_tenant",
            category="billing",
            alert_type="payment_failed",
            severity="error",
            title="Payment failed",
            message="...",
            notification_key="billing:payment_failed:evt_1"
        )
        notif2 = TenantNotification(
            tenant_id="test_tenant",
            category="usage",
            alert_type="usage_threshold_80",
            severity="warning",
            title="Usage 80%",
            message="...",
            notification_key="usage:threshold:80:2026-05-01",
            dismissed_at=datetime.now(timezone.utc)  # Dismissed
        )
        sess.add(notif1)
        sess.add(notif2)
        sess.commit()
        
        # API call (with auth)
        with client.session_transaction() as sess_obj:
            sess_obj['tenant_id'] = 'test_tenant'
        
        response = client.get('/api/notifications')
        assert response.status_code == 200
        data = response.json
        assert data['count'] == 1  # Only active (notif2 dismissed)
        assert data['notifications'][0]['alert_type'] == 'payment_failed'
        
        sess.close()

def test_dismiss_notification_api_idempotent():
    """POST /api/notifications/<id>/dismiss idempotent."""
    app = create_test_app()
    client = app.test_client()
    
    with app.app_context():
        sess = db.session()
        notif = TenantNotification(
            tenant_id="test_tenant",
            category="billing",
            alert_type="trial_expiry_7d",
            severity="warning",
            title="Trial ends",
            message="...",
            notification_key="billing:trial_expiry_7d:sub_123:2026-05-25"
        )
        sess.add(notif)
        sess.commit()
        notif_id = notif.id
        
        with client.session_transaction() as sess_obj:
            sess_obj['tenant_id'] = 'test_tenant'
        
        # Dismiss
        response1 = client.post(f'/api/notifications/{notif_id}/dismiss')
        assert response1.status_code == 200
        
        # Dismiss again
        response2 = client.post(f'/api/notifications/{notif_id}/dismiss')
        assert response2.status_code == 200
        
        sess.close()

def test_dismiss_notification_api_cross_tenant_protection():
    """Cannot dismiss another tenant's notification via API."""
    app = create_test_app()
    client = app.test_client()
    
    with app.app_context():
        sess = db.session()
        notif = TenantNotification(
            tenant_id="tenant_a",
            category="billing",
            alert_type="payment_failed",
            severity="error",
            title="Payment failed",
            message="...",
            notification_key="billing:payment_failed:evt_x"
        )
        sess.add(notif)
        sess.commit()
        notif_id = notif.id
        
        with client.session_transaction() as sess_obj:
            sess_obj['tenant_id'] = 'tenant_b'  # Different tenant
        
        response = client.post(f'/api/notifications/{notif_id}/dismiss')
        assert response.status_code == 404
        
        sess.close()
```

### Integration Tests

**File: `tests/test_story_12_1_integration.py`**

```python
def test_stripe_webhook_to_dashboard_end_to_end():
    """Stripe webhook event → API response includes notification."""
    app = create_test_app()
    client = app.test_client()
    
    with app.app_context():
        tenant_id = "tenant_integration_1"
        
        # Simulate Stripe webhook
        event = {
            'type': 'invoice.payment_failed',
            'id': 'evt_int_1',
            'data': {
                'object': {
                    'subscription': 'sub_int_1',
                    'metadata': {'tenant_id': tenant_id}
                }
            }
        }
        
        # POST webhook
        response = client.post(
            '/webhook',
            json=event,
            headers={'Content-Type': 'application/json'}
        )
        assert response.status_code == 200
        
        # GET notifications as operator
        with client.session_transaction() as sess_obj:
            sess_obj['tenant_id'] = tenant_id
        
        response = client.get('/api/notifications')
        assert response.status_code == 200
        
        data = response.json
        assert data['count'] >= 1
        
        # Verify content
        found = False
        for notif in data['notifications']:
            if notif['alert_type'] == 'payment_failed':
                assert notif['severity'] == 'error'
                assert 'Payment failure' in notif['title']
                found = True
        assert found

def test_usage_threshold_sync_on_dashboard_load():
    """Dashboard page load → sync_usage_threshold_notifications called."""
    app = create_test_app()
    client = app.test_client()
    
    with app.app_context():
        tenant_id = "tenant_load_1"
        period_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        sub = Subscription(
            tenant_id=tenant_id,
            conversation_limit=100,
            current_period_start=period_start
        )
        sess = db.session()
        sess.add(sub)
        sess.commit()
        
        # Create 85 analytics events (85% of limit)
        with open(app.config['ANALYTICS_EVENT_STORE_PATH'], 'w') as f:
            for i in range(85):
                f.write(json.dumps({
                    'tenant_id': tenant_id,
                    'conversation_key': f'conv_{i:04d}',
                    'stage': 'inbound_receive',
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }) + '\n')
        
        app.config['USAGE_ALERT_THRESHOLD_PCTS'] = '80'
        
        with client.session_transaction() as sess_obj:
            sess_obj['tenant_id'] = tenant_id
        
        # Load dashboard (triggers sync)
        response = client.get('/dashboard/operator')
        assert response.status_code == 200
        
        # Verify notification was created
        notif = sess.query(TenantNotification).filter(
            TenantNotification.tenant_id == tenant_id,
            TenantNotification.alert_type == 'usage_threshold_80'
        ).first()
        assert notif is not None
        
        sess.close()
```

---

## Risk Assessment & Mitigation

### Risk 1: Analytics Data Contamination
**Risk:** Old analytics events without tenant_id cause incorrect usage counts.
**Likelihood:** Medium (legacy events may exist)
**Impact:** High (usage alerts for wrong tenants or excessive alerts)
**Mitigation:**
- Explicit check: skip events where `tenant_id` is empty/None
- Test covers tenant isolation (see test suite)
- Document in analytics event schema that tenant_id is mandatory
- Plan remediation: backfill tenant_id for old events in Story 12.X

### Risk 2: Stripe Webhook Delivery Failure
**Risk:** Stripe webhook never reaches notification handler → billing alerts never created.
**Likelihood:** Low (Stripe is reliable)
**Impact:** Critical (operators never see payment alerts)
**Mitigation:**
- Non-blocking: webhook errors logged but don't block HTTP response
- Monitor: log all webhook processing errors for ops review
- Fallback: plan batch sync job in Story 12.X (periodic Stripe API sweep)
- Document: ops runbook includes manual stripe event recovery steps

### Risk 3: Notification Deduplication Failure
**Risk:** Same alert created multiple times (notification_key collision or unique constraint bug).
**Likelihood:** Low (uniqueness constraint is in DB)
**Impact:** Medium (UX clutter, but not data loss)
**Mitigation:**
- Test covers idempotent insertion (see unit tests)
- Unique constraint enforced at DB level (not app logic)
- Monitoring: query for duplicate notification_keys per tenant

### Risk 4: Cross-Tenant Leakage
**Risk:** Operator A sees notifications for Tenant B.
**Likelihood:** Medium (common security pitfall)
**Impact:** Critical (regulatory, privacy breach)
**Mitigation:**
- All queries include explicit `tenant_id` filter
- Foreign key constraint on TenantNotification.tenant_id
- Test covers cross-tenant isolation (see unit tests)
- Code review checklist: verify every SQL query has tenant_id filter

### Risk 5: Dashboard Performance Regression
**Risk:** Syncing usage alerts on every page load causes P50 latency spike.
**Likelihood:** Low (analytics queries are bounded)
**Impact:** Medium (UX slowness)
**Mitigation:**
- Bounded analytics queries: events within 90-day retention window only
- Caching: store computed usage percent in subscription record (next sprint)
- Monitoring: measure sync latency, alert if > 500ms
- Fallback: make sync async/background job if needed

### Risk 6: Trial Expiry Logic Edge Cases
**Risk:** Trial warning timing is wrong (off-by-one days, timezone bugs).
**Likelihood:** Medium (datetime math is tricky)
**Impact:** Low (wrong timing but operator still gets alert eventually)
**Mitigation:**
- Explicit UTC handling throughout (`datetime.now(timezone.utc)`)
- Test covers 7-day and 1-day thresholds with edge case times
- Manual testing: set trial to expire tomorrow and verify 1-day alert fires
- Document: trial alert timing formula in code comments

---

## Dependencies & Ordering

### Must Complete Before Story 12.1:
- **Story 10.2** (Dashboard Analytics v1): provides analytics event structure and retention
- **Story 11.2** (Rollback Drill): SQLite readiness confirmation

### Story 12.1 Enables:
- **Story 12.2** (Conversation History): uses notification center pattern for other alerts
- **Story 12.5** (Cost Guardrails): reuses notification infrastructure for spend alerts

### Integration Points:
1. **Stripe Integration** (existing): webhook handler modified to call `create_stripe_billing_notifications()`
2. **Analytics Events** (Story 10.1): usage calculations consume conversation analytics
3. **Dashboard** (Story 10.2): notification center panel rendered in operator dashboard
4. **Subscription Model** (existing): read current_period_start and conversation_limit

---

## Implementation Checklist

- [ ] **Database**: Alembic migration for `tenant_notifications` table (if not already present)
- [ ] **Models**: Verify `TenantNotification` model complete in `app/models/__init__.py`
- [ ] **Service Layer**:
  - [ ] Implement `create_stripe_billing_notifications()`
  - [ ] Implement `sync_usage_threshold_notifications()`
  - [ ] Implement `list_tenant_notifications()`
  - [ ] Implement `dismiss_tenant_notification()`
- [ ] **Webhook Integration**: Modify Stripe webhook handler to call notification creation
- [ ] **API Endpoints**:
  - [ ] `GET /api/notifications` (list active)
  - [ ] `POST /api/notifications/<id>/dismiss` (dismiss)
- [ ] **Frontend**:
  - [ ] Add notification center HTML panel to `dashboard.html`
  - [ ] Add CSS classes for notification styling
  - [ ] Add JavaScript for load/render/dismiss flow
- [ ] **Dashboard Hook**: Call `sync_usage_threshold_notifications()` on operator dashboard page load
- [ ] **Configuration**:
  - [ ] Document `USAGE_ALERT_THRESHOLD_PCTS` env var (default: "80")
  - [ ] Document `ANALYTICS_RETENTION_DAYS` env var (default: 90)
- [ ] **Testing**:
  - [ ] Unit tests: notification persistence, billing alerts, usage alerts, API
  - [ ] Integration tests: Stripe webhook → dashboard flow
  - [ ] Manual QA: verify trial/payment alerts, verify dismissal persists
- [ ] **Documentation**: Add section to ops runbook for notification troubleshooting
- [ ] **Deployment**: Plan rollout (feature flag optional if needed)

---

## Success Criteria

**AC 12.1.1:** Notification center panel displays trial expiry warnings (7-day, 1-day), payment failure alerts, and usage threshold warnings.
- ✅ Panel visible on operator dashboard
- ✅ Shows at least one alert per category (if applicable)
- ✅ Styling distinguishes severity levels

**AC 12.1.2:** Notifications persisted per tenant, dismissed individually, dismissal survives reload.
- ✅ Database records created for each alert
- ✅ Dismiss button updates `dismissed_at` column
- ✅ Page reload shows only non-dismissed notifications

**AC 12.1.3:** Billing alerts triggered by Stripe webhook events; no polling.
- ✅ Stripe webhook handler creates notifications in same transaction
- ✅ No background jobs or polling logic
- ✅ Alert created within 1 second of webhook receipt

**AC 12.1.4:** Usage threshold alerts computed from conversation analytics.
- ✅ Query counts unique conversation_key values from analytics store
- ✅ Filters by tenant_id and current billing period
- ✅ Respects configured thresholds (configurable via env var)

**AC 12.1.5:** Notifications tenant-isolated.
- ✅ All database queries include `tenant_id` filter
- ✅ Foreign key constraint enforces relationship
- ✅ Test confirms cross-tenant queries fail
- ✅ API validates tenant_id from session context

---

## References

- **Epic 12:** `_bmad-output/planning-artifacts/epics-next-cycle.md` (lines 340-400)
- **Sprint Plan:** `_bmad-output/planning-artifacts/sprint-plan-next-iteration-2026-05-18.md`
- **Sprint Status:** `_bmad-output/implementation-artifacts/sprint-status-next-cycle.yaml`
- **Related Stories:** Story 10.1 (Analytics API), Story 10.2 (Dashboard), Story 11.2 (SQLite)
- **Existing Patterns:** `app/services/notification_center.py`, `app/models/__init__.py`

---

## Sign-Off

**Story created:** 2026-05-18  
**Status:** ready-for-dev  
**Pull condition:** Gate B + Gate C complete, full suite green  

**Next steps:**
1. Review story with team and confirm all acceptance criteria are understood
2. Create feature branch from main (pre-Gate B completion if developing in parallel)
3. Implement in order: Database → Service → API → Frontend → Tests
4. Validate against acceptance criteria before PR
5. PR review checklist: tenant isolation, error handling, test coverage

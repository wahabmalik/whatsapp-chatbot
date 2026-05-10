# Railway Deployment Guide for WhatsApp AI Bot

## Overview
This guide walks through deploying the WhatsApp AI Bot SaaS app to Railway for the first time. Railway automatically handles SSL/TLS, auto-scaling, and provides a public URL.

---

## Step 1: Complete Environment Variables Reference

Railway will inject these variables. Create them in the Railway dashboard under **Variables**.

### Core Flask & Security
```
FLASK_SECRET_KEY=<generate: python -c "import secrets; print(secrets.token_hex(32))">
# Long random 64-char hex string. Required for production.
```

### WhatsApp Provider (Choose ONE)

**If using Meta Cloud API:**
```
WHATSAPP_PROVIDER=meta
ACCESS_TOKEN=<from Meta Business Acct>
APP_ID=<from Meta App Dashboard>
APP_SECRET=<from Meta App Dashboard>
PHONE_NUMBER_ID=<WhatsApp Business Account ID>
VERIFY_TOKEN=<any random string you choose>
VERSION=v18.0
RECIPIENT_WAID=<optional fallback number, digits only>
```

**If using Evolution API (recommended for Pakistan):**
```
WHATSAPP_PROVIDER=evolution
EVOLUTION_API_URL=http://<your-evolution-instance>:3333
EVOLUTION_API_KEY=<from Evolution API dashboard>
EVOLUTION_INSTANCE_NAME=<instance name>
EVOLUTION_WEBHOOK_SECRET=<random string>
EVOLUTION_WEBHOOK_SECRET_HEADER=apikey
```

### AI Services
```
OPENAI_API_KEY=sk-...
OPENAI_ASSISTANT_ID=asst_...
USE_OPENAI_SERVICE=true

# Optional: Google AI as fallback
GOOGLE_AI_API_KEY=
```

### Paddle Billing (Sandbox for Testing)
```
PADDLE_API_KEY=<from Sandbox dashboard: Settings → Authentication → API Keys>
PADDLE_CLIENT_TOKEN=<from Sandbox dashboard: Authentication → Client-side tokens>
PADDLE_WEBHOOK_SECRET=<from Sandbox dashboard: Notifications → Webhooks>
PADDLE_STARTER_PRICE_ID=pri_...
PADDLE_PRO_PRICE_ID=pri_...
PADDLE_BUSINESS_PRICE_ID=pri_...
```

> **Note:** Paddle requires **TWO** different credentials for sandbox:
> - Dashboard: https://sandbox-vendors.paddle.com (for credentials)
> - Checkout: Uses `https://sandbox-checkout.paddle.com` (automatic in SDK)

### Database (Railway-managed PostgreSQL)
```
DATABASE_URL=<Railway will auto-inject this>
# Format: postgresql://user:pass@host:5432/dbname
```

### Email (SMTP - Optional for Password Reset)
```
APP_BASE_URL=https://<your-railway-url>
SMTP_HOST=<SMTP server, or empty to disable>
SMTP_PORT=587
SMTP_USERNAME=<email address>
SMTP_PASSWORD=<app password or token>
SMTP_FROM_ADDRESS=noreply@yourdomain.com
SMTP_USE_TLS=true
PASSWORD_RESET_TOKEN_TTL_MINUTES=30
```

### App Configuration
```
STATE_STORE_BACKEND=memory
# (memory = no disk persistence, or sqlite for local storage)
OUTBOUND_CHANNEL=whatsapp
```

### Gunicorn Tuning (Optional - Railway defaults are fine)
```
GUNICORN_WORKERS=3
GUNICORN_THREADS=2
GUNICORN_TIMEOUT=120
GUNICORN_LOG_LEVEL=info
```

---

## Step 2: Create Railway Account & Project

### 2.1 Sign Up
1. Go to https://railway.app
2. Click **"Start New"**
3. Sign in with GitHub (recommended for easier deployment)

### 2.2 Create a New Project
1. Click **"+ Create New Project"**
2. Select **"Deploy from GitHub Repo"**
3. Connect your GitHub account if not already connected
4. Select `wahabmalik/whatsapp-chatbot` repository
5. Click **"Deploy Now"**

Railway will detect your `Procfile` and begin deployment. You'll see the build logs in real-time.

---

## Step 3: Add PostgreSQL Database

### 3.1 Add Postgres Service
1. In the Railway project dashboard, click **"+ Add Service"**
2. Select **"Database"** → **"PostgreSQL"**
3. Railway will spin up a managed PostgreSQL instance
4. Click on the PostgreSQL service card to see credentials

### 3.2 Verify DATABASE_URL
1. In PostgreSQL service settings, click the **"Variables"** tab
2. You should see `DATABASE_URL` already created
3. Copy this value — it's automatically available to your web service

### 3.3 Run Database Migrations
After the first deployment, you need to run migrations:

**Option A: Using Railway Shell**
1. In Railway dashboard, click your web service
2. Go to **"Deployments"** tab
3. Click the latest deployment
4. Click **"View Logs"** → **"Shell"** tab (or click the terminal icon)
5. Run:
   ```bash
   flask db upgrade
   # or
   alembic upgrade head
   ```

**Option B: Via One-Off Job (Recommended)**
1. Click **"+ Add Service"**
2. Select **"Run a Job"**
3. Configure:
   - **Command:** `flask db upgrade` (or `alembic upgrade head`)
   - **Cron:** Leave empty (one-time execution)
4. Click **"Deploy"**
5. Job will run once, then clean up

---

## Step 4: Get Your Public URL & Deploy

### 4.1 Get the Public URL
1. Go to your Railway project dashboard
2. Click the web service (Python app)
3. In the **"Environment"** section, scroll to **"Domains"**
4. You'll see something like: `whatsapp-chatbot-production.up.railway.app`
5. Copy this URL

### 4.2 Trigger Deployment
Your app is already deploying! Check **Deployments** tab for build progress.

To force a re-deployment:
1. Go to **"Settings"** tab on the service
2. Click **"Redeploy Latest"**

Wait for the build to complete (typically 2-3 minutes).

### 4.3 Verify App is Running
1. Visit `https://whatsapp-chatbot-production.up.railway.app` in your browser
2. You should see your Flask app (login page or dashboard)
3. Check Railway logs for any errors: **Deployments** → **View Logs**

---

## Step 5: Register Railway URL as Paddle Webhook

### 5.1 Update Paddle Sandbox Settings
1. Go to https://sandbox-vendors.paddle.com
2. Navigate to **Notifications** → **Webhooks**
3. Click **"Add Webhook"**
4. Configure:
   - **Endpoint URL:** `https://<your-railway-url>/api/webhook/paddle`
   - **Webhook Events:**
     - `transaction.completed`
     - `transaction.updated`
     - `subscription.created`
     - `subscription.updated`
     - `subscription.cancelled`
5. Click **"Save"**
6. You'll see the webhook appear; click it and copy the **"Secret Key"**

### 5.2 Update Paddle Secret in Railway
1. Go to your Railway project → web service
2. Click **"Variables"** tab
3. Find `PADDLE_WEBHOOK_SECRET`
4. Paste the secret from step 5.1
5. Click **"Update"**

### 5.3 Verify Webhook Signature Verification
Your app verifies incoming webhooks using the secret. Check that:
- `PADDLE_WEBHOOK_SECRET` is set in Railway
- Your app's webhook handler validates the `Paddle-Signature` header

(The code in `views_auth.py` handles this automatically.)

---

## Step 6: Verify End-to-End Checkout Flow

### 6.1 Test the Checkout Flow (Sandbox Mode)

#### A. Log in to your deployed app
1. Visit `https://<your-railway-url>`
2. Sign up for a new account (or use test account)
3. Fill out the onboarding form

#### B. Trigger a Checkout
1. Navigate to the **Billing** or **Upgrade Plan** page
2. Click **"Upgrade to Pro"** (or any plan button)
3. You should be redirected to **Paddle's Sandbox Checkout** (hosted checkout overlay)
   - Note: URL will be `https://sandbox-checkout.paddle.com`

#### C. Complete Test Payment
1. Enter **Paddle test card:**
   - Card: `4111 1111 1111 1111`
   - Expiry: `12/25` (any future date)
   - CVV: `123`
   - Cardholder: any name
2. Click **"Complete Payment"**

#### D. Verify Webhook Received
1. Go back to Railway dashboard
2. Click web service → **Logs** tab
3. Search for `PADDLE_WEBHOOK` or `transaction.completed`
4. You should see a log entry showing webhook received and processed

#### E. Verify Subscription Updated in Database
1. Go to **Deployments** → **Shell**
2. Run:
   ```bash
   python
   >>> from app import create_app
   >>> app = create_app()
   >>> with app.app_context():
   ...     from app.models import User
   ...     user = User.query.filter_by(email='your-test-email').first()
   ...     print(f"Plan: {user.subscription_plan}")
   ...     print(f"Status: {user.subscription_status}")
   ```
3. Plan should show `pro` (or whichever plan you purchased)
4. Status should show `active`

---

## Step 7: Post-Deployment Checklist

- [ ] **Environment Variables:** All required variables set in Railway
- [ ] **Database:** PostgreSQL running and connected
- [ ] **Migrations:** `flask db upgrade` completed successfully
- [ ] **Public URL:** App responds at `https://<your-railway-url>`
- [ ] **WhatsApp Provider:** Either Meta API or Evolution API credentials configured
- [ ] **Paddle Webhook:** Registered in Paddle sandbox and secret configured
- [ ] **SSL/TLS:** Railway handles this automatically (HTTPS enabled)
- [ ] **Logging:** Check Railway logs for any startup errors
- [ ] **Test Checkout:** Completed end-to-end with test card
- [ ] **Session Storage:** Flask sessions working (Railway disk persists)

---

## Step 8: Troubleshooting

### App Won't Start
```
Error: ModuleNotFoundError: No module named 'psycopg2'
```
**Fix:** Railway auto-installs from `requirements.txt`. If persists, delete and redeploy.

### Database Connection Error
```
Error: SQLALCHEMY_DATABASE_URI not set or invalid
```
**Fix:** 
1. Ensure PostgreSQL service is running in Railway
2. Check `DATABASE_URL` variable is present
3. Run migrations: `flask db upgrade`

### Webhook Not Triggering
```
Checkout completes but no subscription created
```
**Checklist:**
1. Webhook registered in Paddle sandbox dashboard
2. `PADDLE_WEBHOOK_SECRET` matches Paddle dashboard
3. Endpoint URL is exactly: `https://<your-railway-url>/api/webhook/paddle`
4. Check Railway logs for incoming POST requests to `/api/webhook/paddle`

### Paddle Checkout Fails
```
Error: PADDLE_API_KEY invalid or missing
```
**Fix:**
1. Get API key from **Paddle Sandbox Dashboard** → **Authentication**
2. Make sure you're using **SANDBOX** credentials (not production)
3. Restart the web service after updating variable

### Session/Cookie Issues
```
Users logged out after page reload
```
**Fix:**
1. Ensure `FLASK_SECRET_KEY` is set (same across deploys)
2. Don't use `> /dev/null` or similar in Procfile (keeps logs)
3. Check Railway disk space is available

---

## Step 9: Moving to Production (Paddle Live)

When ready to accept real payments:

1. **Create Production Paddle Credentials:**
   - Go to https://vendors.paddle.com (production)
   - Follow same process: Authentication → Create API Key & Client Token
   - Create webhook in Paddle (production)

2. **Create Production Railway Project:**
   - Optional: Create a separate Railway project for production
   - Or add a "production" environment in the same project

3. **Update Environment Variables:**
   - Switch `PADDLE_API_KEY`, `PADDLE_CLIENT_TOKEN`, `PADDLE_WEBHOOK_SECRET` to production values
   - Update `PADDLE_*_PRICE_ID` to production price IDs

4. **Re-Deploy:**
   - Railway auto-redeploys when variables change
   - Or manually trigger: **Settings** → **Redeploy Latest**

---

## Step 10: Monitoring & Maintenance

### Monitor Logs
- Railway dashboard → **Logs** tab shows real-time output
- Check for `ERROR` or `CRITICAL` levels regularly

### Scale Horizontally
- Railway can auto-scale based on CPU/memory
- Configure in **Settings** → **Deployment** → **Scaling**

### Backup Database
- Railway provides automated backups (included in free tier)
- Manual backups via: `pg_dump` over SSH

### Update App
- Push to GitHub main branch
- Railway auto-deploys (if enabled) or manually redeploy

---

## Summary of Steps Completed

| Step | Task | Status |
|------|------|--------|
| 1 | Gather env vars | ✅ See above |
| 2 | Create Railway account & project | ⏳ Do now |
| 3 | Add PostgreSQL & run migrations | ⏳ After step 2 |
| 4 | Get public URL & verify deployment | ⏳ After step 3 |
| 5 | Register Paddle webhook | ⏳ After step 4 |
| 6 | Test checkout flow | ⏳ After step 5 |
| 7 | Verify e2e success | ⏳ After step 6 |
| 8 | Move to production | Later |

---

## Quick Reference: Railway CLI (Optional)

If you prefer command-line:

```bash
# Install Railway CLI
npm install -g @railway/cli

# Login
railway login

# Link to your project
railway link

# View logs in real-time
railway logs

# Run a shell command in the web service
railway shell

# Run a one-off job
railway run flask db upgrade
```

---

**Next Step:** Start with **Step 2** — create your Railway account!

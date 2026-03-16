# Quickstart: Gmail Mail Sync

**Feature**: 002-gmail-mail-sync  
**Audience**: Repair Café operators setting up the mail sync for the first time

---

## Prerequisites

- Feature 001 (core infrastructure) is deployed and healthy (`GET /health` returns `db: ok`)
- You have a Google account with Gmail that receives Repair Café visit request emails
- You have access to the `.env` file on the Raspberry Pi (via SSH or Portainer)

---

## Step 1: Create a Google Cloud Project and OAuth 2.0 credentials

1. Go to [console.cloud.google.com](https://console.cloud.google.com) and create a new project
   (e.g., "Repair Cafe Mail Assistant").

2. Enable the **Gmail API**:
   - Navigate to **APIs & Services → Library**
   - Search for "Gmail API" and click **Enable**

3. Create **OAuth 2.0 Client credentials**:
   - Navigate to **APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID**
   - Application type: **Desktop app** (or **Web application** with `http://localhost` as
     redirect URI)
   - Download the JSON file

4. Add yourself (and any co-coordinators) as **Test Users**:
   - Navigate to **APIs & Services → OAuth consent screen → Test users**
   - Add the Gmail address used for receiving visit requests
   - *(This is required while the app remains in "Testing" mode — refresh tokens for test
     users expire after 7 days unless the app is published)*

---

## Step 2: Obtain a refresh token

Run the following one-time script locally (not on the Pi) to exchange your OAuth credentials
for a refresh token:

```bash
pip install google-auth-oauthlib

python - <<'EOF'
import json
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
flow = InstalledAppFlow.from_client_secrets_file("client_secrets.json", SCOPES)
creds = flow.run_local_server(port=0)

print("GMAIL_CLIENT_ID =", creds.client_id)
print("GMAIL_CLIENT_SECRET =", creds.client_secret)
print("GMAIL_REFRESH_TOKEN =", creds.refresh_token)
EOF
```

This opens a browser window. Sign in with the Gmail account that receives visit requests and
grant the requested read-only permission. Copy the three printed values.

---

## Step 3: Add Gmail credentials to `.env`

On the Raspberry Pi (or in the Portainer env-vars panel), add the three values to `.env`:

```dotenv
GMAIL_CLIENT_ID=your_client_id_here
GMAIL_CLIENT_SECRET=your_client_secret_here
GMAIL_REFRESH_TOKEN=your_refresh_token_here
```

> **Security**: The `.env` file is excluded from version control (`.gitignore`). Never commit
> these values to any repository.

Restart the application container:
```bash
docker compose restart backend
```

---

## Step 4: Verify credentials on the config page

1. Open the application in your browser (e.g., `http://raspberrypi.local:8000`)
2. Navigate to **Config** → **Test mail connection**
3. You should see: **✓ ok — Gmail credentials are present**

The health dashboard also shows `mail: ok` once credentials are present.

---

## Step 5: Configure the visit-request filter (optional)

By default the sync fetches all emails in your inbox (`in:inbox`). To narrow to visit requests:

1. Navigate to **Config**
2. Set **Mail filter** to a Gmail search query, for example:
   - `subject:Aanmelding` — Dutch "registration" subject line
   - `from:aanmelding@example.com` — specific sender
   - `label:visit-requests` — custom Gmail label
3. Click **Save**

---

## Step 6: Run your first sync

1. Navigate to **Mail** in the sidebar
2. Click **Sync Mail**
3. The button changes to **⟳ Syncing…** while the sync runs
4. On completion you see: *"N new email(s) fetched, 0 duplicate(s) skipped"*
5. All fetched emails appear in the list, newest first

On a fresh deployment the first sync fetches **all** emails matching the filter (no date
lower bound). Subsequent syncs only fetch emails received since the last successful sync,
minus the 5-minute overlap window.

---

## Step 7: Enable background polling (optional)

To have the system check for new emails automatically:

1. Navigate to **Config**
2. Set **Mail poll interval** to a positive integer (e.g., `15` for every 15 minutes)
3. Click **Save**

The scheduler starts immediately — no restart required. Set to `0` to disable.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Sync fails with "credentials invalid or expired" | Refresh token revoked or >6 months unused | Re-run Step 2 to get a new token |
| Sync fails with "credentials invalid or expired" for a test app | Refresh token expired after 7 days | Add yourself as a test user (Step 1 point 4) or publish the OAuth app |
| Sync shows 0 emails but inbox has messages | Mail filter is too restrictive | Check the **Mail filter** setting on the config page |
| Sync shows duplicates | Should not happen — open a bug; `gmail_message_id` UNIQUE constraint enforces deduplication | |
| Health shows `mail: unconfigured` | One or more `GMAIL_*` env vars are missing | Check `.env` and restart the backend container |
| Background polling not triggering | Interval set to `0` or scheduler restart needed | Check **Mail poll interval** on config page; restart if needed |

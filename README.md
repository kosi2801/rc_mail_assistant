# rc_mail_assistant
An AI assistant that supports Repair Café initiatives by drafting mail responses on event-visit-requests past responses.

## Setup

### 1. Clone and configure environment

```bash
cp .env.example .env
```

Edit `.env` and fill in at minimum `SECRET_KEY` and `POSTGRES_PASSWORD`. Gmail credentials are optional at startup — the app runs in degraded mode without them.

### 2. Set up Gmail OAuth credentials

The app reads emails from a Gmail inbox using OAuth 2.0. Follow these steps once to obtain credentials and connect your Gmail account.

#### 2.1 Create a Google Cloud project and OAuth client

1. Go to [console.cloud.google.com](https://console.cloud.google.com) and create a new project (or select an existing one).
2. Navigate to **APIs & Services → Library**, search for **Gmail API**, and click **Enable**.
3. Go to **APIs & Services → OAuth consent screen**:
   - Choose **External** as the user type.
   - Fill in the required fields (app name, support email).
   - On the **Scopes** step, add the scope `https://www.googleapis.com/auth/gmail.readonly`.
   - On the **Test users** step, add the Gmail address you want to read mail from.
   - Save and continue through to the end.
4. Go to **APIs & Services → Credentials → Create Credentials → OAuth client ID**:
   - Application type: **Web application**
   - Name: e.g. `rc-mail-assistant`
   - Under **Authorised redirect URIs**, add the exact callback URL for your deployment.
     For a default local Docker setup this is:
     ```
     http://localhost:8000/auth/gmail/callback
     ```
   - Click **Create**.
5. Note down the **Client ID** and **Client Secret** shown in the confirmation dialog.

#### 2.2 Configure `.env`

Add the following values to your `.env`:

```env
GMAIL_CLIENT_ID=<your-client-id>
GMAIL_CLIENT_SECRET=<your-client-secret>

# Must match EXACTLY the redirect URI you registered in step 2.1 above.
# Required when running in Docker or behind a reverse proxy.
GMAIL_REDIRECT_URI=http://localhost:8000/auth/gmail/callback
```

> **Why `GMAIL_REDIRECT_URI`?**
> When running inside Docker the app cannot auto-detect the external URL your browser
> uses. If this value is missing or doesn't match the URI registered in Google Cloud
> Console, Google will reject the authorization with **Error 400: redirect_uri_mismatch**.
> The value here and the value in the Google Cloud Console must be identical, including
> the scheme (`http`/`https`), host, port, and path.

#### 2.3 Connect Gmail from the Configuration page

Once the application is running with the three `GMAIL_*` values set:

1. Open the web UI at [http://localhost:8000](http://localhost:8000).
2. Navigate to the **Configuration** page.
3. In the **Gmail Connection** section, click **Connect Gmail**.
4. Google's account picker opens — select the Gmail account you added as a test user
   in step 2.1 and grant access.
5. After successful authorization you are redirected back to the Configuration page
   with a confirmation banner: _"Gmail connected successfully."_

The refresh token is stored encrypted in the application database (AES-128-CBC via
Fernet, key derived from `SECRET_KEY`). You do **not** need to copy or paste any
tokens manually.

To **re-authorize** (e.g. after revoking access or rotating `SECRET_KEY`), click
**Re-authorize** on the Configuration page — the account picker will pre-select
the previously connected account. To **disconnect**, click **Disconnect**.

> **Note:** `GMAIL_REFRESH_TOKEN` is no longer required in `.env`. If it is still
> present from a previous setup, the application will automatically import it into
> the database on first boot and log a reminder to remove the redundant entry.

### 3. Start the application

```bash
docker compose up --build
```

The web UI is available at [http://localhost:8000](http://localhost:8000).

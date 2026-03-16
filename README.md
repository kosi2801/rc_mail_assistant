# rc_mail_assistant
An AI assistant that supports Repair Café initiatives by drafting mail responses on event-visit-requests past responses.

## Setup

### 1. Clone and configure environment

```bash
cp .env.example .env
```

Edit `.env` and fill in at minimum `SECRET_KEY` and `POSTGRES_PASSWORD`. Gmail credentials are optional at startup — the app runs in degraded mode without them.

### 2. Set up Gmail OAuth credentials

The app reads emails from a Gmail inbox using OAuth 2.0. Follow these steps once to obtain the three `GMAIL_*` values for your `.env`.

#### 2.1 Create a Google Cloud project and OAuth client

1. Go to [console.cloud.google.com](https://console.cloud.google.com) and create a new project (or select an existing one).
2. Navigate to **APIs & Services → Library**, search for **Gmail API**, and click **Enable**.
3. Go to **APIs & Services → OAuth consent screen**:
   - Choose **External** as the user type.
   - Fill in the required fields (app name, support email).
   - On the **Scopes** step, add the scope `https://mail.google.com/`.
   - On the **Test users** step, add the Gmail address you want to read mail from.
   - Save and continue through to the end.
4. Go to **APIs & Services → Credentials → Create Credentials → OAuth client ID**:
   - Application type: **Web application**
   - Name: e.g. `rc-mail-assistant`
   - Under **Authorised redirect URIs**, add: `http://localhost`
   - Click **Create**.
5. Note down the **Client ID** and **Client Secret** shown in the confirmation dialog.
   Set them in your `.env`:
   ```
   GMAIL_CLIENT_ID=<your-client-id>
   GMAIL_CLIENT_SECRET=<your-client-secret>
   ```

#### 2.2 Obtain a refresh token via OAuth Playground

1. Open [Google OAuth 2.0 Playground](https://developers.google.com/oauthplayground).
2. Click the **⚙️ gear icon** (top right) and check **"Use your own OAuth credentials"**.
3. Enter your **Client ID** and **Client Secret** from step 2.1.
4. In the left panel, scroll to **Gmail API v1** and select the scope:
   `https://mail.google.com/`
5. Click **Authorize APIs** and sign in with the Gmail account you added as a test user.
6. After consent, click **Exchange authorization code for tokens**.
7. Copy the **Refresh token** from the response panel.
8. Set it in your `.env`:
   ```
   GMAIL_REFRESH_TOKEN=<your-refresh-token>
   ```

> **Note:** The refresh token is long-lived. Store it securely and never commit it to version control.

### 3. Start the application

```bash
docker compose up --build
```

The web UI is available at [http://localhost:8000](http://localhost:8000).

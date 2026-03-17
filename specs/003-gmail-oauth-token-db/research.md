# Research: Gmail OAuth Token Secure Storage

**Feature**: `003-gmail-oauth-token-db` | **Phase**: 0 (Pre-design) | **Date**: 2025-06-26

All NEEDS CLARIFICATION items from Technical Context resolved below.
Decisions are final inputs to Phase 1 design.

---

## R-001 · Fernet Key Derivation from `SECRET_KEY`

**Question**: `SECRET_KEY` is an arbitrary string; Fernet requires exactly 32 bytes
encoded as URL-safe base64. How should the key be derived?

**Decision**: SHA-256 hash of the UTF-8-encoded `SECRET_KEY`, then
`base64.urlsafe_b64encode(digest)`.

```python
import base64, hashlib
from cryptography.fernet import Fernet

def _fernet_key(secret_key: str) -> bytes:
    digest = hashlib.sha256(secret_key.encode("utf-8")).digest()  # 32 bytes
    return base64.urlsafe_b64encode(digest)                       # Fernet-compatible

fernet = Fernet(_fernet_key(settings.secret_key))
```

**Rationale**:
- SHA-256 always produces 32 bytes regardless of `SECRET_KEY` length or content
- `base64.urlsafe_b64encode` of 32 bytes is always 44 characters — exactly what
  Fernet expects
- Deterministic: the same `SECRET_KEY` always yields the same Fernet key; no
  separate key-storage problem is introduced
- Intentional side-effect: rotating `SECRET_KEY` changes the Fernet key, making
  stored ciphertext unreadable — treated as "Token Error / Reconnection Required"
  (spec §Edge Cases; FR-011)

**Alternatives considered**:
- `PBKDF2` key stretching — adds salt-storage complexity; unnecessary for this use
  case since `SECRET_KEY` is already a high-entropy operator secret
- Dedicated `FERNET_KEY` env var — adds operator burden; the spec explicitly calls
  for derivation from the existing `SECRET_KEY`
- `secrets.token_bytes(32)` at startup — non-deterministic; breaks every restart

> **Canonical implementation reference**: `data-model.md §Encryption helper` — the `_make_fernet()` snippet there is the authoritative source. The snippet above is illustrative; implementation MUST follow data-model.md.

---

## R-002 · OAuth2 Authorization Code Exchange: google-auth-oauthlib vs. raw httpx

**Question**: Should the authorization code → token exchange use
`google-auth-oauthlib` or a direct `httpx.AsyncClient` POST to Google's token
endpoint?

**Decision**: Use **`google-auth-oauthlib`** (`Flow.from_client_config`) for the
redirect URL construction and the blocking exchange; wrap in
`asyncio.get_event_loop().run_in_executor(None, ...)` to keep the FastAPI
handler async (same pattern already used in `GmailAdapter` for all
`googleapiclient` calls).

```python
from google_auth_oauthlib.flow import Flow

flow = Flow.from_client_config(
    client_config={
        "web": {
            "client_id": settings.gmail_client_id,
            "client_secret": settings.gmail_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    },
    scopes=GMAIL_SCOPES,
    state=state_token,
)
flow.redirect_uri = redirect_uri
# exchange (sync call, run in executor)
flow.fetch_token(code=authorization_code)
creds = flow.credentials  # .refresh_token is the value to store
```

**Rationale**:
- `google-auth-oauthlib` handles the exact same credential types already used by
  `GmailAdapter` (`google.oauth2.credentials.Credentials`) — no format conversion
- Consistent with the existing `google-auth` ecosystem already in `pyproject.toml`
- The `Flow` object validates `state` implicitly when constructed with the same
  `state` value; additional manual validation is still done for the signed cookie
  (see R-003)
- `google-auth-oauthlib` is almost certainly already present as a transitive
  dependency of `google-api-python-client`; adding it explicitly pins the version
  and makes the dependency visible

**Alternatives considered**:
- Raw `httpx` POST — avoids the dependency but requires manual JSON parsing,
  field validation, and token-type checking; more code, more surface for bugs
- `google-auth-oauthlib` async variant — does not exist; the library is sync-only

---

## R-003 · CSRF State Storage: Signed Cookie Approach

**Question**: How should the OAuth `state` parameter be stored between
`/auth/gmail/initiate` and `/auth/gmail/callback` to prevent CSRF attacks
without adding session middleware?

**Decision**: At `/initiate`, generate a 32-byte `secrets.token_urlsafe(32)`
`state` value. Sign it using `itsdangerous.URLSafeTimedSerializer` (already
available as a dependency of `python-multipart` / FastAPI ecosystem; if not
present, add `itsdangerous`). Store the signed token in an **`HttpOnly`,
`SameSite=Lax`, `Secure` (if HTTPS), `Max-Age=600`** cookie named
`oauth_state`. At `/callback`, re-derive the signed cookie value, verify
the signature and the 10-minute expiry, and compare the `state` query parameter
to the cookie value before proceeding.

```python
# initiate
from itsdangerous import URLSafeTimedSerializer
signer = URLSafeTimedSerializer(settings.secret_key)
state = secrets.token_urlsafe(32)
signed = signer.dumps(state)
response.set_cookie(
    "oauth_state", signed,
    httponly=True, samesite="lax", max_age=600, path="/",
    secure=request.url.scheme == "https",
)
# redirect to Google with state=state

# callback
cookie_val = request.cookies.get("oauth_state")
stored_state = signer.loads(cookie_val, max_age=600)  # raises SignatureExpired / BadSignature
assert stored_state == request.query_params["state"]
response.delete_cookie("oauth_state")
```

**Rationale**:
- No DB table, no session middleware — exactly as specified in clarifications
- `itsdangerous` is bundled with Starlette (which FastAPI depends on), so it is
  already in the virtualenv; no new package needed
- `SameSite=Lax` blocks cross-site form POST attacks; `HttpOnly` prevents XSS
  token theft; `Max-Age=600` limits the CSRF window to 10 minutes (spec FR-002)
- The cookie is cleared at callback — one-use only

**Alternatives considered**:
- Store state in DB — requires a new table and cleanup job; overkill for a
  10-minute CSRF token
- Store state in application memory (`app.state`) — fails with multiple workers
  or container restarts during the OAuth window
- PKCE (Proof Key for Code Exchange) — provides similar protection but requires
  Google's OAuth endpoint to support it with `code_challenge_method=S256`;
  for server-side flows the signed cookie is simpler and equally effective

---

## R-004 · Gmail OAuth Scopes

**Question**: What Gmail API scopes should be requested during the Authorization
Code flow?

**Decision**: Request only **`https://www.googleapis.com/auth/gmail.readonly`**.

**Rationale**:
- The application reads emails (`users.messages.list`, `users.messages.get`) — it
  never sends, modifies, or deletes messages
- `gmail.readonly` is the least-privilege scope that covers all current operations
- Requesting a narrower scope reduces the attack surface and the Google OAuth
  consent screen warning level
- If draft/send features are added in a future feature, the scope list will need
  to be extended and operators will need to re-authorize (acceptable, documented)

**Alternatives considered**:
- `https://mail.google.com/` (full access) — unnecessarily broad
- `https://www.googleapis.com/auth/gmail.modify` — allows read + modify but not
  send; still broader than needed

---

## R-005 · GmailAdapter Constructor Refactor: Credential Injection

**Question**: Should `GmailAdapter` continue reading credentials from
`app_settings`, or should it accept them explicitly?

**Decision**: Refactor `GmailAdapter.__init__` to accept
`refresh_token: str`, `client_id: str`, `client_secret: str` as explicit
parameters. Remove all `app_settings.gmail_*` reads from the adapter.
The `GmailCredentialService` (or `main.py` lifespan) is responsible for
fetching and decrypting the token, then passing it to the constructor.

```python
class GmailAdapter(MailAdapter):
    def __init__(
        self,
        refresh_token: str,
        client_id: str,
        client_secret: str,
    ) -> None:
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
        )
        creds.refresh(Request())  # eager fail-fast
        self._svc = build("gmail", "v1", credentials=creds, cache_discovery=False)
```

**Rationale**:
- Constitution §IV: adapters MUST NOT cross service-layer boundaries; DB access
  belongs in the service layer
- Enables unit testing of `GmailAdapter` without a database or env vars
- `get_status()` can remain a lightweight credential-presence check (parameters
  are already injected at construction time)

**Alternatives considered**:
- Keep reading from `app_settings` and add a DB-read fallback — creates a
  confusing dual-source priority and violates §IV modular boundary
- Pass a `GmailCredential` model object — leaks ORM types into the adapter layer;
  rejected for the same §IV reason

---

## R-006 · Singleton Pattern for `gmail_credentials` Table

**Question**: How should the single-credential constraint be enforced at the
database level?

**Decision**: Use a **fixed `id = 1`** primary key with
`INSERT … ON CONFLICT (id) DO UPDATE` (Postgres upsert). The `id` column is an
`INTEGER PRIMARY KEY` — no autoincrement.

```python
stmt = pg_insert(GmailCredential).values(
    id=1,
    encrypted_refresh_token=ciphertext,
    account_email=email,
    connected_at=func.now(),
    updated_at=func.now(),
).on_conflict_do_update(
    index_elements=["id"],
    set_={
        "encrypted_refresh_token": ciphertext,
        "account_email": email,
        "updated_at": func.now(),
    },
)
```

**Rationale**:
- Idempotent by construction — satisfies Constitution §V
- `id = 1` is a widely understood singleton pattern; no CHECK constraint or
  trigger needed
- Re-authorization simply re-runs the upsert; old ciphertext is atomically
  replaced
- `DELETE FROM gmail_credentials WHERE id = 1` is the "Disconnect" path

**Alternatives considered**:
- `UNIQUE` constraint on a status column — requires a sentinel value; awkward
- Delete-then-insert — non-atomic; risks brief "no credential" window during
  re-auth if a concurrent request checks status between the two statements

---

## R-007 · Startup Migration: `GMAIL_REFRESH_TOKEN` env var → DB (FR-009)

**Question**: How and where should the one-time migration of a legacy
`GMAIL_REFRESH_TOKEN` env var into the database be performed?

**Decision**: Implement `GmailCredentialService.maybe_migrate_from_env()` as an
async method called from `main.py` lifespan after migrations run. The method:
1. Checks if `settings.gmail_refresh_token` is non-empty
2. Checks if a credential row already exists in the DB
3. If env var present AND no DB row: encrypts the token, inserts with
   `account_email = "migrated-from-env"`, logs a structured deprecation warning
4. If env var present AND DB row exists: logs a warning to remove the redundant
   env var; takes no other action
5. Does nothing if env var is absent

```python
# Structured deprecation log (FR-009 — example)
logger.warning(
    "gmail_token_migrated_from_env",
    message="GMAIL_REFRESH_TOKEN has been imported into the database. "
            "Remove it from .env at your convenience.",
)
```

**Rationale**:
- Startup lifespan is the correct place: DB is already connected, migrations
  have run, the credential table exists
- Non-destructive: never deletes the env var (that's the operator's job)
- Idempotent: the "row already exists" branch is a no-op
- `account_email = "migrated-from-env"` is a clear sentinel; the real email
  can be updated when the operator re-authorizes via the UI

**Alternatives considered**:
- Alembic data migration — runs before the application starts, no access to
  `app_settings.secret_key` for encryption at Alembic time; rejected
- CLI `manage.py migrate-token` command — requires operator action; spec requires
  automatic migration

---

## R-008 · `ConnectorStatus` Extension: `TOKEN_ERROR` State

**Question**: The existing `ConnectorStatus` enum has `OK`, `UNCONFIGURED`,
`ERROR`. Should `TOKEN_ERROR` (Fernet decryption failure) be a new variant
or reuse `ERROR`?

**Decision**: Add `TOKEN_ERROR = "token_error"` as a new variant to the
`ConnectorStatus` enum in `mail_service.py`.

**Rationale**:
- `TOKEN_ERROR` has a distinct recovery path (re-authorize via UI) vs. generic
  `ERROR` (which may indicate a network or API issue)
- The config page template needs to render different UI affordances
  (show "Re-authorize" button for `TOKEN_ERROR` vs. general error message)
- Keeping the enum in `mail_service.py` (the shared interface layer) ensures
  all consumers see the same status vocabulary
- `UNCONFIGURED` remains correct for "no credential in DB and no env var"

**Alternatives considered**:
- Reuse `ERROR` with a detail string — loses type safety at call sites; the
  template cannot branch on string comparison reliably
- New `CredentialStatus` enum separate from `ConnectorStatus` — over-engineering
  for this feature; the two statuses are closely related

---

## R-009 · `itsdangerous` Availability

**Question**: Is `itsdangerous` already available in the virtualenv, or does it
need to be added to `pyproject.toml`?

**Decision**: **Do not add** `itsdangerous` explicitly — it is a transitive
dependency of `starlette`, which is a direct dependency of `fastapi`. It will
always be present. Verify during implementation with `python -c "import itsdangerous"`.
If the transitive dependency ever disappears, add it explicitly then.

**Rationale**:
- Adding a transitive dep explicitly creates version-conflict risk when the
  upstream (Starlette) updates its own pin
- The `itsdangerous` API used here (`URLSafeTimedSerializer`) has been stable
  across all versions in Starlette's dependency range

---

## R-010 · Token Masking in API / Template Responses

**Question**: What format should the masked account identifier take in the
config page UI?

**Decision**: Display the `account_email` stored at authorization time, but
mask the local-part: show only the first 2 characters before `@`, then `***`,
then the full domain. Example: `re***@gmail.com`.

```python
def mask_email(email: str) -> str:
    if "@" not in email or email == "migrated-from-env":
        return "(account unknown — please re-authorize)"
    local, domain = email.split("@", 1)
    visible = local[:2] if len(local) >= 2 else local
    return f"{visible}***@{domain}"
```

**Rationale**:
- Confirms to the operator which account is connected without exposing the full
  address (volunteer privacy, Constitution §I)
- Consistent with common OAuth UI patterns
- `migrated-from-env` sentinel returns a user-friendly prompt to re-authorize
  rather than exposing the internal code artefact string

**Alternatives considered**:
- Full email display — marginally more useful but unnecessary given the
  single-account constraint; operator already knows which account they authorized
- Show only domain — too little context if the operator has multiple Gmail
  addresses on the same domain

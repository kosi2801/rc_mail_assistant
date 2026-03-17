# Research: Gmail Account Picker

**Feature**: `004-gmail-account-picker` | **Phase**: 0 | **Date**: 2025-07-21

> All questions relevant to this feature were resolved during the clarification session
> documented in `spec.md §Clarifications (Session 2026-03-17)`. No external research
> was required. This file records the decisions and rationale for traceability.

---

## R-001 — Which `prompt` value forces the account picker AND guarantees a refresh token?

**Decision**: `prompt="select_account consent"` (space-separated string)

**Rationale**:
- `select_account` instructs Google to always display the account chooser, regardless
  of how many sessions are active in the browser. Without it, Google may silently use
  the first active session.
- `consent` forces the consent screen to appear on every authorization, which in turn
  guarantees that Google issues a new `refresh_token`. Without `consent`, Google only
  issues a `refresh_token` on the first grant — subsequent re-authorizations return
  `refresh_token: null`, which the callback already guards against
  (`/config?gmail_error=no_refresh_token`).
- Both values must appear together, space-separated, as a single string.

**Alternatives considered**:
- `prompt="consent"` alone (current implementation): fixes the refresh-token problem
  but does not guarantee the account picker when multiple sessions are active.
- `prompt="select_account"` alone: shows the picker but does not guarantee a refresh
  token on re-authorization.
- `prompt="select_account"` + `access_type="offline"`: not sufficient — `consent` is
  still required to force re-issuance of an already-granted `offline` token.

**Source**: `spec.md §Clarifications` (confirmed by Google OAuth 2.0 documentation).

---

## R-002 — How should `login_hint` be sourced to satisfy FR-003?

**Decision**: Server-side DB lookup via `GmailCredentialService.get()` injected as
`session: AsyncSession = Depends(get_session)` into `gmail_initiate()`.

**Rationale**:
- The spec explicitly prohibits client-supplied hints (FR-003): the hint MUST come
  from the server-side credential store to prevent spoofing.
- `GmailCredentialService.get()` already returns `GmailCredential | None` and reads
  the singleton row (id=1). The `account_email` column is the correct source.
- Injecting `AsyncSession` via `Depends(get_session)` is the established pattern in
  this codebase (see `gmail_callback`, `gmail_disconnect`).
- `login_hint` is purely advisory (FR-004, spec §Edge Cases): Google treats it as a
  pre-selection hint, not a hard constraint. The user may still choose a different
  account; the callback already handles that correctly since it records the email
  returned by `gmail.users().getProfile()`, not the hint.

**Alternatives considered**:
- Accept `login_hint` as a query parameter from the client: rejected — violates FR-003
  (must not be client-supplied).
- Read `account_email` from a separate settings field: rejected — the DB row is the
  authoritative source and already exists.

**Source**: `spec.md §Clarifications` and `spec.md §Assumptions`.

---

## R-003 — Must `access_type="offline"` be preserved?

**Decision**: Yes — `access_type="offline"` MUST remain alongside
`prompt="select_account consent"`.

**Rationale**: Both parameters together are required to guarantee a refresh token:
- `access_type="offline"` tells Google to include a refresh token in the response.
- `prompt="consent"` (part of the new value) forces the consent screen so Google
  actually re-issues the token for previously-authorized accounts.
- Removing either breaks token refresh; the callback's `no_refresh_token` guard would
  trigger on re-authorization.

**Source**: `spec.md §Assumptions`.

---

## Summary of Decisions

| ID | Decision | Spec ref |
|----|----------|----------|
| R-001 | Use `prompt="select_account consent"` | FR-001, §Clarifications |
| R-002 | Source `login_hint` from `GmailCredentialService.get().account_email` | FR-003, §Clarifications |
| R-003 | Preserve `access_type="offline"` unchanged | §Assumptions |

No NEEDS CLARIFICATION items remain. No external dependencies or new packages required.

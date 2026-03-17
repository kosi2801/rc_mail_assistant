# Feature Specification: Gmail Account Picker

**Feature Branch**: `004-gmail-account-picker`  
**Created**: 2025-07-21  
**Status**: Draft  
**Input**: User description: "Force Google account picker on Connect Gmail OAuth flow; add login_hint for re-authorization"

## Overview

When a volunteer with multiple Google accounts signed in to their browser clicks "Connect Gmail", the application silently authenticates with the first active Google session — which may not be their Repair Café inbox. This feature ensures the account picker is always shown, so users can consciously choose the correct account. A secondary enhancement pre-selects the already-connected account when the user re-authorizes, reducing friction.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Account Picker on First Connect (Priority: P1)

A volunteer clicks "Connect Gmail" for the first time (or after disconnecting). Even though they have multiple Google accounts signed in to their browser, they are always shown the Google account chooser and can pick the correct Repair Café inbox account.

**Why this priority**: This directly solves the reported bug. Without this fix, volunteers silently connect the wrong account and see someone else's — or their personal — inbox, breaking the core workflow. Delivering P1 alone is a viable and shippable fix.

**Independent Test**: Can be fully tested by signing in to two Google accounts in a browser, clicking "Connect Gmail" in the RC mail assistant, and verifying that Google displays the account chooser instead of skipping straight to the consent screen.

**Acceptance Scenarios**:

1. **Given** a volunteer has two or more Google accounts active in their browser and no Gmail account is currently connected, **When** they click "Connect Gmail", **Then** Google displays the account picker before the consent screen, allowing them to choose which account to connect.
2. **Given** a volunteer has exactly one Google account active in their browser, **When** they click "Connect Gmail", **Then** Google still presents the account picker (with only one option), and the flow completes normally.
3. **Given** a volunteer selects their preferred Repair Café account from the picker and grants consent, **When** the OAuth flow completes, **Then** the application stores credentials for that specific account and displays the correct email address as connected.

---

### User Story 2 - Correct Account Pre-selected on Re-authorization (Priority: P2)

A volunteer who already has a Gmail account connected clicks "Re-authorize" (e.g., because their token expired). The account picker opens but their previously connected Repair Café account is pre-selected, so they don't have to scan a list of accounts to find the right one.

**Why this priority**: This is a usability enhancement that reduces re-authorization friction, particularly valuable for volunteers who manage many Google accounts. It is safe to skip if P1 is the only concern, but adds meaningful polish with minimal extra effort.

**Independent Test**: Can be fully tested by connecting an account (P1), then triggering re-authorization and verifying the account picker opens with the previously connected email pre-highlighted/pre-selected.

**Acceptance Scenarios**:

1. **Given** a Gmail account is already connected and the volunteer clicks "Re-authorize", **When** the account picker opens, **Then** the previously connected email address is pre-selected in the picker.
2. **Given** a Gmail account is already connected but the volunteer intentionally selects a different account in the picker during re-authorization, **When** they complete the flow, **Then** the newly selected account replaces the previously connected one.
3. **Given** the stored account email is no longer valid or the matching Google session has been removed, **When** the account picker opens with the login hint, **Then** the picker still allows the volunteer to choose any available account (the hint is advisory, not blocking).

---

### Edge Cases

- What happens when the volunteer closes the account picker without making a selection? The OAuth flow is abandoned and the user is returned to the application in the same state as before (no account connected / still the old account).
- What happens when no Google accounts are active in the browser? Google prompts the volunteer to sign in to a Google account before showing the picker — existing browser behaviour, no change required.
- What happens if the previously stored account email for login hint is missing or malformed? The system falls back to showing an unpre-selected account picker; the flow must not error out.

## Clarifications

### Session 2026-03-17

- Q: Where does `login_hint` come from? → A: Server-side DB lookup via `Depends(get_session)` in `gmail_initiate()`. Add `session: AsyncSession = Depends(get_session)` to the endpoint, look up the stored `account_email` server-side, and pass it as `login_hint` to `flow.authorization_url()` when present.
- Q: Which Google OAuth `prompt` value forces the account picker AND guarantees a refresh token? → A: `prompt="select_account consent"` (space-separated). Forces both the Google account chooser dialog AND re-consent on every authorization, guaranteeing a refresh token is issued. Replaces the previous `prompt="consent"` value.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The "Connect Gmail" authorization flow MUST always display the Google account chooser, regardless of how many Google sessions are active in the user's browser. This MUST be implemented by passing `prompt="select_account consent"` (space-separated) to `flow.authorization_url()`, replacing any prior use of `prompt="consent"` alone.
- **FR-002**: The account chooser MUST also appear when reconnecting or starting a fresh connection after a previous account has been disconnected. Because `prompt="select_account consent"` is set unconditionally (FR-001), this behaviour is guaranteed for all connection scenarios without additional branching.
- **FR-003**: When a volunteer initiates re-authorization for an already-connected Gmail account, the authorization URL MUST carry a `login_hint` parameter identifying the previously connected email address so that Google can pre-select it in the account picker. The `account_email` MUST be retrieved server-side via a database lookup (injected as `session: AsyncSession = Depends(get_session)` in `gmail_initiate()`) and passed to `flow.authorization_url(login_hint=account_email)` when present; it MUST NOT be supplied by the client.
- **FR-004**: If no previously connected email address is available (first-time connection, or stored email absent), the system MUST initiate the flow without a `login_hint`; the absence of a hint MUST NOT cause an error.
- **FR-005**: After the account picker flow completes, the application MUST store credentials associated with the account the user actually selected, even if that differs from any login hint provided.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of "Connect Gmail" initiations display the Google account chooser — verifiable by manual test with a multi-account browser session and by inspecting the constructed authorization URL for `prompt=select_account+consent` (URL-encoded form of `prompt="select_account consent"`).
- **SC-002**: 0 cases where a user can silently connect an account other than the one they intended — the account picker removes the ambiguity entirely.
- **SC-003**: Re-authorization flows for accounts with a stored email pre-select the correct account in the picker on every attempt — verifiable by manual test.
- **SC-004**: The authorization URL construction introduces no regression in existing single-account or unauthenticated browser scenarios — all pre-existing OAuth acceptance tests continue to pass.

## Assumptions

- The feature applies exclusively to the "Connect Gmail" OAuth entry points; no other OAuth flows in the application are affected.
- The stored `account_email` (used for the `login_hint`) is already persisted in the `gmail_credentials` table as the `account_email` column of the `GmailCredential` singleton record (id = 1). The existing `GmailCredentialService.get()` method (returns `GmailCredential | None`) is the correct server-side lookup path; no new persistence logic is required for this feature.
- `access_type="offline"` is already set in the existing `flow.authorization_url()` call and MUST remain set alongside `prompt="select_account consent"`. Both parameters together guarantee that Google returns a refresh token; removing either breaks token refresh.
- Google's account picker behaviour (pre-selection via login hint) is handled by Google's own UI; the application is only responsible for passing the correct parameters.
- Volunteers who have only one Google account signed in will still see the account picker — this is acceptable and consistent with the requirement for explicit account selection.

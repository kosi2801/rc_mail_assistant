# Feature Specification: Dashboard Gmail Connectivity Status Indicator

**Feature Branch**: `005-dashboard-gmail-status`
**Created**: 2026-03-17
**Status**: Implemented

## Overview

The dashboard page currently shows general system health (database, LLM, mail credentials) but does not reflect the true Gmail OAuth2 connection state. Operators cannot tell from the dashboard whether Gmail is actually usable — only that credentials *exist* in the environment. This feature adds a Gmail status section to the dashboard that shows two complementary pieces of information: (1) whether the OAuth2 client credentials (`GMAIL_CLIENT_ID` / `GMAIL_CLIENT_SECRET`) are configured in the environment, and (2) the real OAuth2 token connectivity state — whether a valid, decryptable refresh token is stored in the database. Together these give the operator everything needed to diagnose Gmail readiness at a glance and navigate to `/config` for remediation.

**Scope**: Display-only change to the dashboard. No new database tables, no new public API endpoints. The Configuration page Gmail section is already complete and is unchanged.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — At-a-Glance Gmail Status on Dashboard (Priority: P1)

A Repair Café volunteer operator opens the dashboard to verify the system is ready to process emails. They need to confirm at a glance that Gmail is actually connected — not just that credentials exist in configuration files.

**Why this priority**: This is the core ask. Without it, operators must navigate to the Config page every time they want to confirm Gmail is working. A wrong assumption (thinking Gmail is connected when it isn't) means emails go unprocessed silently.

**Independent Test**: Can be fully tested by loading the dashboard while the database holds a valid, decryptable Gmail refresh token — the indicator must show a green "Connected" badge. Delivers clear operational confidence on a single page.

**Acceptance Scenarios**:

1. **Given** a valid Gmail refresh token is stored and decryptable, **When** the operator loads the dashboard, **Then** a green "✓ Connected" indicator appears in the Gmail status area.
2. **Given** no Gmail refresh token exists in the database (never authorized), **When** the operator loads the dashboard, **Then** an amber/grey "Not Connected" indicator appears in the Gmail status area.
3. **Given** a Gmail refresh token is stored but cannot be decrypted (key was rotated or token corrupted), **When** the operator loads the dashboard, **Then** a red "⚠ Token Error" indicator appears in the Gmail status area.
4. **Given** `GMAIL_CLIENT_ID` and/or `GMAIL_CLIENT_SECRET` are absent from the environment, **When** the operator views the dashboard, **Then** the Gmail section clearly indicates that the OAuth2 app credentials are not configured.
5. **Given** any Gmail status state, **When** the operator views the indicator, **Then** the indicator is presented as a link or clearly shows a path to `/config` so they can act on it.

---

### User Story 2 — Navigating to Config from a Token Error (Priority: P2)

An operator sees a red token-error indicator on the dashboard after the application's encryption key was rotated. They need to navigate directly to the Configuration page to re-authorize Gmail without hunting for the link.

**Why this priority**: The red state is actionable — the operator *must* re-authorize. If the dashboard provides no path to fix the issue, the indicator increases anxiety without providing relief.

**Independent Test**: Can be fully tested by simulating a `TOKEN_ERROR` state and confirming the dashboard indicator links to `/config`. Independently delivers a complete remediation flow from the dashboard.

**Acceptance Scenarios**:

1. **Given** the Gmail status is `TOKEN_ERROR`, **When** the operator sees the dashboard indicator, **Then** the indicator includes a visible link or call-to-action directing them to `/config`.
2. **Given** the operator clicks the link from a `TOKEN_ERROR` indicator, **When** the Config page loads, **Then** they land on the Config page where the Gmail Connection section is immediately visible and actionable.

---

### User Story 3 — Masked Account Email Shown When Connected (Priority: P3)

When Gmail is successfully connected, the operator wants a quick reminder of *which* account is authorized — without exposing the full email address in the UI.

**Why this priority**: This is a "nice to have" for operators managing multiple deployments or accounts. It adds contextual confidence but does not block the core workflow.

**Independent Test**: Can be fully tested by loading the dashboard with a connected Gmail account and verifying the masked email (e.g., `al***@example.com`) appears alongside the green indicator.

**Acceptance Scenarios**:

1. **Given** Gmail status is `OK` and an account email is on record, **When** the operator views the dashboard, **Then** the masked account email appears next to the "Connected" indicator.
2. **Given** Gmail status is `OK` but no account email is recorded (legacy/sentinel value), **When** the operator views the dashboard, **Then** the indicator shows "Connected" without crashing, omitting or gracefully substituting the account display.

---

### Edge Cases

- What happens when the database is unreachable while fetching Gmail status? → The dashboard's overall health check already surfaces a DB error; the Gmail status indicator should degrade gracefully (show an indeterminate/unknown state rather than crash the entire health fragment).
- What happens if the health fragment is requested before any Gmail credentials have ever been configured (fresh install, no env vars)? → The indicator should show "Not Connected" (same as `UNCONFIGURED`) — not an error.
- What if the Gmail status check takes longer than expected? → Because the dashboard loads the health fragment asynchronously (HTMX), a slow Gmail status check should not block the initial page render; it may delay only the fragment.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The dashboard health fragment MUST display a dedicated Gmail connectivity status indicator that reflects the real OAuth2 token state — whether a valid, decryptable refresh token exists in the database.
- **FR-002**: The Gmail status indicator MUST present three distinct visual states:
  - **Connected** (green) — token is present and successfully decryptable
  - **Not Connected** (amber or grey) — no token exists or OAuth2 client credentials are absent
  - **Token Error** (red) — a token record exists but cannot be decrypted
- **FR-003**: The Gmail status indicator MUST include a navigational link to `/config` in all three states so the operator can act on the displayed status.
- **FR-004**: The Gmail status source MUST be `GmailCredentialService.get_connection_status()`, which is the authoritative evaluator of token health — not a simple environment-variable presence check.
- **FR-005**: The dashboard health fragment route MUST inject the Gmail status value into the health fragment template without requiring a separate API call from the browser.
- **FR-006**: The existing "Gmail Credentials" row in the health fragment (which checks only env-var presence) MUST be replaced by the new Gmail status section. The new section MUST retain visibility of whether `GMAIL_CLIENT_ID` and `GMAIL_CLIENT_SECRET` are configured (as a distinct sub-indicator or secondary label alongside the token status), so the operator can distinguish between "app credentials missing" and "credentials present but not yet authorized". There must be no duplication or contradiction between the new section and any remaining health rows.
- **FR-007**: When Gmail status is `OK` and an account email is available, the dashboard MUST display the masked email alongside the "Connected" label.
- **FR-008**: The Gmail status indicator MUST degrade gracefully when the database is unavailable — displaying an indeterminate or unknown state rather than raising an unhandled error. The template renders `ConnectorStatus.ERROR` (a fourth enum value) via the `{% else %}` branch, showing "? Unknown"; this state satisfies FR-008's graceful degradation requirement.
- **FR-009**: No new database tables and no new public-facing API endpoints shall be introduced by this feature.
- **FR-010**: The dashboard health fragment route MUST supply both the OAuth2 client credential presence (`gmail_oauth_configured: bool`, derived from `settings.gmail_client_id` and `settings.gmail_client_secret`) and the token connectivity status (from `GmailCredentialService.get_connection_status()`) as separate template context variables, so the template can render both indicators independently.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator can determine both the Gmail OAuth2 client credential configuration state (`GMAIL_CLIENT_ID`/`GMAIL_CLIENT_SECRET` present or absent) and the token connectivity state (Connected / Not Connected / Token Error) by looking at the dashboard alone, without navigating to any other page — verifiable by user observation across all combinations of the two states.
- **SC-002**: The dashboard continues to load in full within the same time budget as before this feature — the Gmail status check does not introduce a perceptible delay beyond the existing health-check latency.
- **SC-003**: An operator who sees a Token Error on the dashboard can reach the Config page's Gmail Connection section in one click — verifiable by following the link from the indicator.
- **SC-004**: Zero regressions on the existing dashboard health indicators (Database, LLM/Ollama) — all three existing rows continue to display correctly after the change.
- **SC-005**: The dashboard Gmail indicator and the Config page Gmail Connection section show consistent state for the same underlying token record — they never contradict each other.

## Assumptions

- The `GmailCredentialService.get_connection_status()` method is already safe to call from the health-fragment request context (it does not perform network I/O to Google; it only inspects the stored token).
- The health fragment is loaded asynchronously by the browser via HTMX after the main dashboard page renders, so an additional database read inside the health-fragment route is acceptable without affecting initial page load time.
- The existing "Gmail Credentials" `mail` check in `HealthResult` (which checks only env-var presence) will be superseded by the new indicator; however, the credential presence information is preserved as a secondary sub-indicator within the new Gmail status section (FR-006, FR-010). The `mail` field in `HealthResult` may be retired or kept for backward compatibility with any future API consumers — this decision is deferred to the plan phase.
- Visual design follows the existing inline-style convention used throughout the Config page (no external CSS framework changes needed).
- The feature targets operators (single-tenant, self-hosted deployment); no multi-user or role-based access concerns apply.

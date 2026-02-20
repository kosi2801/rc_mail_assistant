## 1 — Constitution (project charter)

**Project name**: Repair Cafe Mail Assistant

**Purpose / mission**
- Provide the Repair Cafe volunteer team with a lightweight, private web application that helps triage incoming visitor emails, automatically draft reply suggestions based on past similar correspondence, and allow safe manual sync to Gmail for sending.

**Scope**
- In-scope:
  - Manual one‑click sync from a Gmail account to a local Postgres database (text only, no attachments or HTML)
  - Processing & deduplication of email threads; removal of quoted mail thread remnants per message
  - Detecting visitor visit-intent messages vs other community messages and ignoring non-visitor communication
  - Finding similar historical threads (vector search) and using them to generate draft reply(s) with LLMs (Ollama by default, fallback to llama.cpp)
  - UI for review/editing of draft replies and manual sync of drafts back to Gmail as local Gmail Drafts
  - Config page for connectivity, LLM choice, and event metadata (next event date/location/offerings)
  - Basic logs, health checks and connection tests
- Out-of-scope:
  - Automatic sending of replies (no outbound send without explicit user action from Gmail UI)
  - Multi-user access control or authentication beyond local network access
  - Handling of attachments beyond storing a metadata placeholder

**Principles & constraints**
- Privacy-first: store only textual content locally. No attachments. No public hosting of mail data.
- Manual synchronization model: user must trigger inbound/outbound sync actions.
- Minimal dependencies and small footprint to run on a Raspberry Pi 5 (8GB) in Docker/Portainer.
- Modular design: make LLM, database, mail connector and search components replaceable.
- Robust to nightly Docker shutdowns: operations must be idempotent, resumable, and safe across restarts.

**Stakeholders**
- Repair Cafe volunteers (primary users)
- Site maintainers / system operator (single admin user)

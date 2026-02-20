# Repair Cafe — Spec Kit Drafts

> This document contains draft artifacts for the project Spec Kit: Constitution, Project Specification, Specification Clarification, Plan Creation, Plan Validation and Task Breakdown. Use these drafts as starting points — they are intentionally detailed so you can copy, paste, or adapt into your GitHub Spec Kit repository.

---

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

---

## 2 — Project specification (high-level technical spec)

### 2.1 Overview
The app is a single‑node web application (Python back end + lightweight front end) that lives in Docker containers. The backend connects to a local Postgres to store emails, uses a vector DB (Chroma or local sqlite-backed Chroma) to index message embeddings for similarity search, and calls a local LLM through Ollama API by default (or llama.cpp backend optionally) to generate draft replies.

### 2.2 Architecture components
- **Mail Connector**: Gmail API client layer (OAuth2) that can:
  - Fetch messages (text/plain fallback): up to a configurable lookback window
  - Fetch message headers and body text, strip HTML and quoted blocks
  - Detect thread membership and map to local `threads` and `messages`
  - Push drafts to Gmail as Draft objects (no send)
  - Provide connection test endpoints
- **Database**: PostgreSQL (containerized) with volumes for persistence. Schema includes `threads`, `messages`, `senders`, `drafts`, `sync_log`, `config`.
- **Search Index**: ChromaDB (local) or pluggable vector index. Stores embeddings for incoming messages and historical responses.
- **Embedding Provider**: Use configured LLM/embedding method: either Ollama with a compact embedding model, or local llama.cpp converted embeddings. Make embedding pipeline pluggable so you can swap providers.
- **LLM Inference Layer**: Abstraction that can call into:
  - **Ollama API container** (default). Uses HTTP API on localhost to run model inference and embeddings.
  - **llama.cpp** via a small inference service wrapper (local socket or HTTP) when chosen.
- **Web UI**: Single-page app (server-side templating or simple React/HTMX) with a responsive 3‑column layout (threads / incoming messages / outgoing/draft view). Minimal JS dependencies.
- **Worker / Job Queue**: Lightweight job runner (RQ/Redis or a simple persistent job table + background thread) for CPU bound tasks like embedding generation and similarity indexing. Jobs must be resumable after restart.
- **Admin & Config**: Page to edit settings (Gmail OAuth, LLM backend, model name, embeddings model, sync window, Next Event metadata) and to run connection tests.

### 2.3 System constraints & non-functional requirements
- Must run on Raspberry Pi 5 with 8GB RAM; choose models and defaults that fit this device (small quantized models recommended).
- Disk persistence via Docker volumes for Postgres, Chroma, and application data.
- Manual sync only: inbound `Sync incoming` and outbound `Sync Drafts` buttons.
- Nightly container shutdowns: job states must be transactional (in-progress → re-queue on restart), partial progress saved in DB.
- Minimal external dependencies, prefer pure‑Python libraries with easy packaging.
- Local network access only (no public endpoint unless the operator configures reverse proxy). Recommend firewall rules.

### 2.4 Data model (high-level)
- `threads` (id, gmail_thread_id, subject, last_message_at, status_flag)
- `messages` (id, thread_id, gmail_message_id, from_email, to_email, date, plain_text, snippet, is_incoming, cleaned_text)
- `drafts` (id, message_id, content, created_at, synced_to_gmail_draft_id)
- `senders` (email, name, first_contact_at, profile_info_cached)
- `embeddings` (message_id, vector)
- `sync_log` (timestamp, item, action, status, details)

### 2.5 Major workflows
1. **Sync incoming** (manual)
   - Operator clicks `Sync incoming` and chooses lookback window (configurable default e.g., 180 days)
   - Mail Connector calls Gmail API, fetches metadata and plain text bodies
   - For each message: strip quoted text, map to thread, store or update message record if changed
   - Enqueue embedding creation + similarity search job for new/changed messages
2. **Draft generation**
   - For each inbound, unanswered message, system finds N similar historical messages via Chroma (configurable N)
   - Compose an LLM prompt with: current event metadata (next event date/location/offerings), visitor message cleaned text, and relevant snippets from similar historical replies
   - Call LLM to generate a draft response; save as `drafts` associated to the message
3. **Review & Sync Drafts**
   - Operator reviews draft in UI, can edit, then press `Sync Drafts` for selected drafts
   - Drafts are uploaded to Gmail as Draft objects (not sent). The local draft receives `synced_to_gmail_draft_id`

### 2.6 Email cleaning rules
- Remove HTML markup; prefer text/plain parts
- Remove trailing quoted thread remnants using heuristics: common markers (e.g., "On <date>, <name> wrote:", "-----Original Message-----") and by comparing repeated segments across thread messages
- Keep only the visitor's latest message content for intent detection and reply generation

### 2.7 Similarity & retrieval
- Store dense embeddings per message in Chroma
- Use cosine similarity to select the top K prior messages that were answered by volunteers
- Optionally apply heuristic filters: same language, matching keywords ("repair", "visit", "bike", "sewing", postal code), or recent time window

### 2.8 LLM prompt engineering
- Build a concise system prompt: explain the role (help visitor plan their visit), include event metadata, emphasize brevity, friendliness, and local volunteer constraints
- Include 2–4 similar prior replies as examples (few-shot) and label them as "Past reply"
- Limit prompt size to fit the chosen local model; if using a small model, prefer summary-style context (extract 2–4 short snippets rather than full message history)

### 2.9 UI spec (high level)
- 3-column responsive layout:
  - Left column: list of threads, search & filter (unanswered, location tag, date range, keyword). Thread rows show last activity, unread/highlight for incoming-unanswered.
  - Middle column: messages for selected thread (incoming messages stack). Each incoming message shows cleaned_text, metadata and a generate-draft button.
  - Right column: drafted reply or outgoing sent mail. Editor with markdown/plain-text, Save, Re-generate (uses LLM), Mark as Reviewed, Sync to Gmail Draft.
- Visual styling: simple, readable, clear contrast for threads with latest activity as incoming (use a stronger background)
- Admin config screen with test-connect buttons for Gmail, Ollama, llama.cpp, Postgres, Chroma. Show clear error messages.

---

## 3 — Specification clarification (assumptions, unknowns, and open decisions)

### 3.1 Assumptions
- The Gmail account uses OAuth2 and can be authorized by the operator interactively at setup.
- The operator is comfortable exposing the Raspberry Pi on the local network and running containers via Portainer.
- Attachments are intentionally excluded from local storage due to privacy and disk reasons.
- All usage is single-user; no auth system is required.

### 3.2 Open decisions to confirm
- Which exact LLM models will be shipped by default in the app (recommendation: default to a compact Ollama model with instructions for switching to llama.cpp and quantized models)
- Whether to include an optional scheduled (cron) sync in addition to manual sync. (User requested manual-only for safety.)
- Which vector DB to use by default: Chroma local vs a light sqlite-backed vector store. Chroma recommended for API parity but allow pluggable options.

### 3.3 Risks & mitigations
- **Risk**: Running heavier models on 8GB will be slow or OOM.
  - *Mitigation*: Default to small quantized models; make model selection explicit in config and include a performance test (generate a 64‑token response) on model test.
- **Risk**: Quoted text removal fails and pollutes similarity search.
  - *Mitigation*: Implement robust quoted block heuristics + store `cleaned_text` and a fingerprint hash to detect repeated quoted blocks
- **Risk**: Corrupted job state when Docker shuts down nightly.
  - *Mitigation*: Use transactional DB updates for job state. On startup, re-enqueue `in_progress` jobs older than X minutes.

---

## 4 — Plan creation (milestones & timeline suggestions)

> Note: timelines below are example estimates for a single developer working part-time. Adjust for your team.

### Milestone A — Foundations (1–2 weeks)
- Create repository skeleton with Spec Kit and GitHub Spec Kit metadata
- Setup Docker Compose with containers: backend, postgres, optional redis (or use DB-backed job table), and minimal front-end
- Implement DB schema migrations

### Milestone B — Mail sync & storage (2–3 weeks)
- Implement Gmail OAuth setup & test connection
- Implement `Sync incoming` that fetches messages (strip HTML) and stores them in DB, with quoted-text removal
- Add manual re-sync and incremental sync logic

### Milestone C — Search & Embeddings (1–2 weeks)
- Add Chroma integration and embedding pipeline
- Implement job runner that creates embeddings for new messages
- Implement simple similarity API to find top K similar messages

### Milestone D — LLM integration & draft generation (2–3 weeks)
- Implement LLM adapter for Ollama API (default)
- Implement small prompt template and draft creation workflow
- Add manual `Generate draft` and automatic draft suggestion for new incoming messages

### Milestone E — UI & review flow (2–3 weeks)
- Build 3-column responsive UI, thread list and message view
- Draft editor, Save, Re-generate, Mark Reviewed, Sync Drafts to Gmail

### Milestone F — Testing & polish (1–2 weeks)
- Add connection tests in config page
- Add job recovery and resilience logic
- UX polish, smaller dependency reductions, documentation

---

## 5 — Plan validation (QA & acceptance criteria)

### Acceptance tests
- **Sync incoming**: Given a Gmail account with messages in the last 90 days, clicking `Sync incoming` stores messages in DB; repeated runs only store changed/new messages.
- **Quoted removal**: For an email thread with quoted replies, the stored `cleaned_text` should contain only the current user's message and not the repeated quoted history.
- **Similarity**: For a new incoming 'visit request' message, at least one relevant historical reply should be returned by similarity search (manual assessment required).
- **Draft generation**: Draft output must include next event date and location when appropriate and must not be auto-sent.
- **Sync Drafts**: After syncing a reviewed draft, a Draft object appears in the Gmail Drafts folder (not sent). The local record saved `synced_to_gmail_draft_id`.
- **Restart tolerance**: Start a long-running embedding job, forcibly stop Docker, and ensure on restart the job either resumes or is re-queued without data loss.

### Test matrix
- Device: Raspberry Pi 5 (8GB) — run through full flow with small quantized model in Ollama and with llama.cpp fallback.
- Model: small Ollama model; verify CPU RAM usage and time/throughput for a 128-token generation
- Network: Test OAuth flows behind NAT / local network

---

## 6 — Task breakdown (epics → stories → tasks)

### Epic 1 — Repo & infra setup
- Story 1.1: Repo skeleton & Spec Kit files
  - Task: Create README, LICENSE, Spec Kit placeholders
  - Task: Setup GitHub CLI integration guide
- Story 1.2: Docker Compose & Volumes
  - Task: Compose file with service definitions (backend, postgres, chroma optional)
  - Task: Persistent volumes for Postgres, chroma, and app config

### Epic 2 — Database & models
- Story 2.1: DB schema
  - Task: Implement migrations (alembic or plain SQL)
  - Task: Data models for threads/messages/drafts/sync_log
- Story 2.2: Job table for background processing
  - Task: Job enqueue/dequeue schema and worker logic

### Epic 3 — Gmail connector
- Story 3.1: OAuth flow & connectivity tests
  - Task: Implement OAuth and token refresh; secure token storage in Docker volume
  - Task: Implement connection test endpoint and UI widget
- Story 3.2: Sync incoming
  - Task: Fetch messages in lookback window and persist
  - Task: Implement incremental sync by message id and changed flag
  - Task: Implement quoted text removal heuristics and tests

### Epic 4 — Search & Embeddings
- Story 4.1: Chroma integration & adapter
  - Task: Add Chroma client, collection management
  - Task: Embedding adapter to LLM / Ollama or fallback
- Story 4.2: Similarity API
  - Task: API endpoint to return top K similar messages with scores

### Epic 5 — LLM & draft generation
- Story 5.1: LLM adapter for Ollama and llama.cpp
  - Task: Implement abstraction and model config UI
  - Task: Implement model test endpoint (generate short sample)
- Story 5.2: Prompt templates & generation pipeline
  - Task: Implement prompt builder (insert event metadata, similar replies)
  - Task: Save generated draft to DB

### Epic 6 — UI
- Story 6.1: 3-column layout & thread list
  - Task: Thread list APIs, search and filters
  - Task: Mark thread as answered/unanswered visual style
- Story 6.2: Message & draft editor
  - Task: Editor with re-generate & save
  - Task: Sync Drafts button and UI state

### Epic 7 — Reliability & ops
- Story 7.1: Job recovery and re-queue
  - Task: On startup requeue stale `in_progress` jobs
- Story 7.2: Config tests & detailed errors
  - Task: Implement connection test responses with human-friendly errors

---

## 7 — Example prompt template (starter)

```
System: You are an assistant for a Repair Cafe volunteer helping craft friendly, concise email replies that help visitors plan to attend an upcoming Repair Cafe event. Be polite, brief (3-8 sentences), provide the next event date and location when relevant, list any special offerings (e.g. bike repairs), and instruct the visitor on what to bring and how to register or confirm. Keep tone friendly and local.

Context: Next event: {event_date}, Location: {event_location}, SpecialOfferings: {offerings_text}

Visitor message:
{cleaned_visitor_text}

Relevant past replies (examples):
{example_1}
{example_2}

Task: Produce a draft reply tailored to the visitor message. Do not include private volunteer notes. End with: "If you'd like to confirm your visit, reply to this mail and we'll reserve a slot for you."
```

---

## 8 — Deployment & ops notes
- Persist Postgres and Chroma volumes to independent Docker volumes.
- Provide a `backup` container or script that can export DB nightly before Docker shutdown; consider simply copying volumes to the SSD snapshot as part of the existing backup process.
- On Pi, prefer CPU-efficient quantized models or rely on Ollama for easier model management. Provide instructions in README to install Ollama on ARM and to load recommended compact models.

---

## 9 — Next steps & checklist to start implementation
- Confirm default LLM model choice for the app and whether to include pre-downloaded model files in repo or rely on operator to fetch
- Choose vector DB default (Chroma vs sqlite-based)
- Create initial repo with Spec Kit and Docker Compose
- Implement core sync flow (Gmail fetch → store → embed → retrieve similar → draft generator)

---

_End of Spec Kit drafts. Copy these sections into your GitHub Spec Kit files (CONSTITUTION.md, SPECIFICATION.md, CLARIFICATIONS.md, PLAN.md, VALIDATION.md, TASKS.md) and iterate._


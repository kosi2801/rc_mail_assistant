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

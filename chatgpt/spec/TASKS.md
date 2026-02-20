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

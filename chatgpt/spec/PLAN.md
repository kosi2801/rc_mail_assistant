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

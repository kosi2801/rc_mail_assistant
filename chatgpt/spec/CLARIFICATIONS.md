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

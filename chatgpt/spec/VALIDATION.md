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

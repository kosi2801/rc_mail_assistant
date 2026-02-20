## 8 — Deployment & ops notes
- Persist Postgres and Chroma volumes to independent Docker volumes.
- Provide a `backup` container or script that can export DB nightly before Docker shutdown; consider simply copying volumes to the SSD snapshot as part of the existing backup process.
- On Pi, prefer CPU-efficient quantized models or rely on Ollama for easier model management. Provide instructions in README to install Ollama on ARM and to load recommended compact models.

# AXIMA Knowledge Assistant

A local **AI assistant (RAG)** over internal company documentation. It answers employee questions from policies, IT procedures, infrastructure and the IP plan — **all data stays on the local server, nothing is sent to the cloud** (ISO 27001 / NIS2). Every answer cites its source, and if it doesn't know, it says so instead of making things up.

> 🇨🇿 Česká verze: [README.md](README.md)

---

## What it does

You ask in natural language (e.g. *"how do I restore a server from backup?"*) → the assistant finds relevant passages in the internal documents, builds a context, lets the local language model generate an answer, and **shows which documents it drew from**.

## Architecture

- **AI backend:** [Ollama](https://ollama.com) (port 11434) — `nomic-embed-text` (768D embeddings) + `llama3.1` (generation).
- **Vector DB:** [Qdrant](https://qdrant.tech) (port 6333), collection `axima_docs`, 768D, cosine distance.
- **Ingest:** `watchdog_service.py` watches `incoming/`, atomic-moves to `docs/` (to avoid SMB locks), reads DOCX/XLSX/PDF, chunks (1000/200) and upserts into Qdrant.
- **API:** `api.py` (FastAPI, port 8000) — `POST /ask`, `GET /api/version`, serves the web UI.
- **CLI:** `ask_ai.py` — query from the terminal.
- **Web UI:** `web/index.html` — homepage with Assistant / Settings / Documentation / Management report tabs (per the AXIMA UI standard: dark+light, print in light, CS+EN, service footer with commit hash).

## Files

| File | Purpose |
|---|---|
| `watchdog_service.py` | Ingest: folder watching, document reading, chunking, embedding, upsert to Qdrant |
| `api.py` | FastAPI backend (`/ask`, `/api/version`), serves `web/` |
| `ask_ai.py` | CLI query client |
| `web/index.html` | Homepage / UI (single self-contained file, no framework) |
| `dokumentace.md` | Technical documentation (Czech) |
| `docs/BUILD.md` | **Build manual — build the whole system from scratch** ([EN](docs/BUILD.en.md)) |
| `docs/HANDOFF.md` | Current project state and decisions |
| `docs/OPONENTURA.md` | Defense material (decisions, risks, NFRs, capacity, DR, TCO) — Czech |
| `docs/JAK-FUNGUJE-UCENI.md` | Non-technical explainer "how the model knows our data" ([EN](docs/JAK-FUNGUJE-UCENI.en.md)) |
| `requirements.txt` | Python dependencies |

## Quick start

Full from-scratch steps are in **[docs/BUILD.en.md](docs/BUILD.en.md)**. In short:

```bash
# 1) Qdrant (Docker)
docker run -d -p 6333:6333 -v $(pwd)/qdrant_storage:/qdrant/storage qdrant/qdrant

# 2) Ollama + models
ollama pull nomic-embed-text
ollama pull llama3.1

# 3) Python environment
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 4) Ingest + API
python3 watchdog_service.py     # terminal 1
python3 api.py                  # terminal 2 → http://SERVER:8000
```

## Web UI — functionality

`web/index.html` is served by `api.py` at `/` (single self-contained file, no framework, **AXIMA logo** in the header). Tabs:

- **Assistant** — chat against `POST /ask`; sample mode when the backend is down.
- **Settings** — manage **watched paths** (add/remove, subfolders, extensions, active) + **Scan status** (idle/running, last/next scan, "Scan now", per-path document/block counts and freshness) + model/temperature/block count. *Paths are managed by the operator without IT.*
- **Documentation** — full documentation **inside the app** (side menu + articles: About, How it works, How to ask, Paths & scanning, Security) in corporate design, **no git/filesystem links**.
- **Management report** — non-technical overview + **printable scope overview** (with the **AXIMA logo** in the print header). Printing is always in light mode.
- **CS/EN** switch, **dark/light**, footer with **live clock + commit hash + health** (`GET /api/version` contract).

> Data components (paths, scan, scope) run on **sample data** and are ready to be wired to the backend (`/api/settings`, `/api/scope`, `/api/scan`).

## Roadmap (re-prioritised after peer review)

1. **Core verification** — reconciliation cycle over SMB (mtime/size **+ ACL**, hash only changed files) + Linux → SQL19 connectivity.
2. **Access control (MVP, deployment prerequisite)** — AD/Entra authentication, per-document ACL indexing, results filtered by identity. Without it, RAG flattens NTFS permissions = a security regression. **ACL freshness:** the scan also tracks the security descriptor (a permission change doesn't alter mtime), with authorization by the user's transitive group membership.
3. **Stale-vector fix + document versioning** — delete blocks by source before upsert, `on_deleted`, relative path, Qdrant payload index.
4. **Test set + model benchmark** — embedding (nomic vs multilingual-e5 / BGE-m3, for Czech) and generative (incl. quantisation).
5. **Parsing** — OCR and structure-aware table handling (XLSX/PDF).
6. **Hybrid search** — Qdrant **dense + sparse** vectors + RRF/rerank (native in Qdrant for speed, not SQL FTS).
7. **Speed** — answer streaming, model/GPU choice.
8. **Operations** — monitoring, DR, systemd, audit with PII masking, feedback loop.
9. **Separate phase:** live data from Dynamics 365 BC via text-to-SQL (own risk profile).

**SQL Server 2019** serves as sync-state manifest, audit (with PII masking) and later a live data source — **not** as a vector DB or search engine. **Editable paths in Settings** (operator, no IT), stored in SQL, applied by the reconciliation scan; removal deletes from the base.

Decision rationale, risks, NFRs, capacity, DR and TCO: **[docs/OPONENTURA.md](docs/OPONENTURA.md)** (Czech). Live status: [docs/HANDOFF.md](docs/HANDOFF.md).

## Security

Company documents (`*.docx`, `*.pdf`, `*.xlsx`, …) and the `incoming/` folder are gitignored to prevent leaking data (documentation under `docs/` is versioned). Connection credentials belong in `.env` (see `.env.example`), **never in Git**.

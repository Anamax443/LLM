# AXIMA Knowledge Assistant

A local **AI assistant (RAG)** over internal company documentation. It answers employee questions from policies, IT procedures, infrastructure and the IP plan — **all data stays on the local server, nothing is sent to the cloud** (ISO 27001 / NIS2). Every answer cites its source, and if it doesn't know, it says so instead of making things up.

> 🇨🇿 Česká verze: [README.md](README.md)

---

## What it does

You ask in natural language (e.g. *"how do I restore a server from backup?"*) → the assistant finds relevant passages in the internal documents, builds a context, lets the local language model generate an answer, and **shows which documents it drew from**. Access is gated by **Microsoft Entra ID (SSO)** sign-in.

## Architecture

```
Monitored paths        ┌──────────────────────────────────────────────────┐
(local + \\server)     │  watchdog_service.py  (reconciliation ingest)    │
   │                   │  periodic scan → reads .docx/.pdf → chunks →     │
   ▼                   │  embeds → upsert / delete blocks in Qdrant       │
smbclient (Kerberos)   └───────────────────┬──────────────────────────────┘
local os.walk                              ▼
                              Ollama bge-m3 (1024D)  →  Qdrant (axima_docs)

  User ─(Entra ID SSO)─┐
                       ▼
  web/index.html ──POST /ask──►  api.py (FastAPI)  ──►  Qdrant (search)
  (4 tabs, sign-in)                                └─►  Ollama mistral-nemo (generation)
                      ◄── answer + sources (SSE stream) ──
```

- **AI backend:** [Ollama](https://ollama.com) (port 11434) — `bge-m3` (1024D embeddings) + `mistral-nemo` (answer generation).
- **Vector DB:** [Qdrant](https://qdrant.tech) (port 6333), collection `axima_docs`, 1024D, cosine distance.
- **Ingest:** `watchdog_service.py` runs as a periodic **reconciliation scan** of monitored paths (local and UNC `\\server\share` via user-space `smbclient` + Kerberos). It diffs against `reconciliation_manifest.json` (mtime/size), re-indexes changed files, **deletes blocks for removed files** and **old blocks before re-indexing** (no version mixing). Currently `.docx` and `.pdf` are ingested; chunk 1000/200, each block is prefixed with its source name. Interval `RECONCILIATION_INTERVAL_SEC` (default 30 s dev / 900 s recommended for prod).
- **API:** `api.py` (FastAPI, port 8000):
  - `POST /ask` — query, **streamed (SSE)** answer; *requires sign-in*.
  - `GET /api/version` — commit/branch/build for the UI service line.
  - `GET /config` — model/limit/temperature for the UI; *requires sign-in*.
  - `POST /api/verify` — real path-availability check (UNC via user-space `smbclient`, local `os.path.isdir`).
  - `GET /api/monitored_paths` / `POST /api/set_monitored_paths` — read/store monitored paths (`monitored_paths.json`).
  - `POST /api/extract` — text from attachments (PDF via `pypdf`, DOCX via `python-docx`, text fallback); *requires sign-in*.
  - `GET /api/auth/login` · `/api/auth/callback` · `/api/auth/me` · `/api/auth/logout` — sign-in via **Microsoft Entra ID**.
  - Serves the web UI (`web/`) at the root.
  - On startup it checks Qdrant and Ollama availability (health check).
- **CLI:** `ask_ai.py` — query from the terminal.
- **Web UI:** `web/index.html` — homepage with Assistant / Settings / Documentation / Management report tabs (per the AXIMA UI standard: dark+light, print in light, CS+EN, **service line in the header** — health, model, commit, clock, GitHub link). Sign-in overlay (SSO). Paths are loaded/saved via the backend.

## Files

| File | Purpose |
|---|---|
| `watchdog_service.py` | Reconciliation ingest: periodic scan of monitored paths (local + UNC/SMB), reads `.docx`/`.pdf`, chunking, embedding, upsert/delete in Qdrant with source context |
| `api.py` | FastAPI backend (`/ask`, `/config`, `/api/version`, `/api/verify`, `/api/extract`, `/api/monitored_paths`, Entra ID SSO), serves `web/` |
| `ask_ai.py` | CLI query client |
| `flush_qdrant.py` | Service util — drops the `axima_docs` collection (clean re-index from scratch) |
| `web/index.html` | Homepage / UI (single self-contained file, no framework) |
| `axima-web.service` | Sample systemd unit for running the API + web UI in production |
| `dokumentace.md` | Technical documentation (Czech) |
| `docs/BUILD.md` | **Build manual — build the whole system from scratch** ([EN](docs/BUILD.en.md)) |
| `docs/LINUX_SETUP_GUIDE.md` | Linux setup for user-space SMB (gMSA + Kerberos, keytab) |
| `docs/SPOJENI_FILE_SERVERU.md` | Architecture design for Windows File Server ↔ Linux (user-space SMB) — Czech |
| `docs/HANDOFF.md` | Current project state and decisions |
| `docs/OPONENTURA.md` | Defense material (decisions, risks, NFRs, capacity, DR, TCO) — Czech |
| `docs/JAK-FUNGUJE-UCENI.md` | Non-technical explainer "how the model knows our data" ([EN](docs/JAK-FUNGUJE-UCENI.en.md)) |
| `requirements.txt` · `.env.example` | Python dependencies and a config template |

## Quick start

Full from-scratch steps are in **[docs/BUILD.en.md](docs/BUILD.en.md)**. In short:

```bash
# 1) Qdrant (Docker)
docker run -d -p 6333:6333 -v $(pwd)/qdrant_storage:/qdrant/storage qdrant/qdrant

# 2) Ollama + models
ollama pull bge-m3           # embedding, 1024D
ollama pull mistral-nemo     # answer generation

# 3) Python environment
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 4) Configuration — Entra ID sign-in is mandatory
cp .env.example .env         # fill in ENTRA_TENANT_ID / CLIENT_ID / CLIENT_SECRET / SESSION_SECRET

# 5) Ingest (reconciliation scan) + API
python3 watchdog_service.py     # terminal 1
python3 api.py                  # terminal 2 → http://SERVER:8000
```

> Without valid `ENTRA_*` credentials the API still starts, but `/ask` and other protected endpoints return `401` (users cannot sign in).

## Web UI — features

`web/index.html` is served by `api.py` at `/` (single file, no framework, **AXIMA logo** in the header). After sign-in (Entra ID SSO) the tabs are:

- **Assistant** — **streamed chat** with history and Markdown (`POST /ask`); you can **attach files or paste a screenshot (Ctrl+V)** — the content is turned into text (`POST /api/extract`: PDF/DOCX/text + **image/screenshot OCR** via `pytesseract`, Czech+English) and added to the context. Generation can be **stopped**; if the backend is unavailable, a sample mode with a generic error message is shown.
- **Settings** — manage **monitored paths** (add/remove, subfolders, extensions, active) **loaded from the backend** (`GET /api/monitored_paths`) and **saved to the backend** (`POST /api/set_monitored_paths`), a **Verify path availability** button + **terminal** (real check `POST /api/verify` via user-space SMB; until verified the status is "unverified", never fabricated), **Scan status**, model/temperature/block count and "show in header" toggles. *Paths are managed by the operator with no IT involvement.*
- **Documentation** — full documentation **inside the app** (side menu + articles: About, How it works, How to ask, Paths and scanning, Security) in the corporate design, **with no links to git or files**.
- **Management report** — a non-technical overview + a **printable knowledge-base scope** (with the **AXIMA logo** in the print header). Print is always in light mode.
- **CS/EN** switch, **dark/light**; **service line in the header** (health, **model** 🧠, commit, live clock, **GitHub** icon) — model and GitHub can be optionally hidden in Settings. `GET /api/version` contract.

## Roadmap (re-prioritised after peer review)

1. **Core verification** — reconciliation cycle over SMB (mtime/size **+ ACL**, hash only changed files) + Linux → SQL19 connectivity.
2. **Access control (MVP, deployment prerequisite)** — Entra ID authentication **is done**; still missing per-document ACL indexing and filtering results by the user's identity. Without it, RAG flattens NTFS permissions = a security regression. **ACL freshness:** the scan also tracks the security descriptor (a permission change doesn't alter mtime), with authorization by the user's transitive group membership.
3. **Document versioning** — identity = full relative path, Qdrant payload index on `source`.
4. **Test set + model benchmark** — embedding (`bge-m3` vs multilingual-e5, for Czech) and generative (incl. quantisation).
5. **Parsing** — image-attachment OCR **done**; still to do: OCR for **scanned PDFs** and structure-aware table handling (XLSX/PDF).
6. **Hybrid search** — Qdrant **dense + sparse** vectors + RRF/rerank (native in Qdrant for speed, not SQL FTS).
7. **Speed** — answer streaming (done), model/GPU choice.
8. **Operations** — monitoring, DR, systemd, audit with PII masking, feedback loop.
9. **Separate phase:** live data from Dynamics 365 BC via text-to-SQL (own risk profile).

**SQL Server 2019** serves as sync-state manifest, audit (with PII masking) and later a live data source — **not** as a vector DB or search engine. Today monitored paths live in `monitored_paths.json`; removing a path deletes its documents from the base.

Decision rationale, risks, NFRs, capacity, DR and TCO: **[docs/OPONENTURA.md](docs/OPONENTURA.md)** (Czech). Live status: [docs/HANDOFF.md](docs/HANDOFF.md).

## Security

Access is gated by **Microsoft Entra ID (SSO)** sign-in — protected endpoints (`/ask`, `/config`, `/api/extract`) return `401` without a valid session.

Company documents (`*.docx`, `*.pdf`, `*.xlsx`, …) are gitignored to prevent leaking data (documentation under `docs/` is versioned). Connection credentials and keys (`ENTRA_*`, `SESSION_SECRET`) belong in `.env` (see `.env.example`), **not in Git**. Network paths are accessed in user space (`smbclient` + Kerberos, gMSA), with no root and no OS mounts — see [docs/SPOJENI_FILE_SERVERU.md](docs/SPOJENI_FILE_SERVERU.md).

**Assistant guardrails** live in code (`SYSTEM_PROMPT` in `api.py`, the `system` field) — no persona, **prompt-injection resistant** (ignore "change your role/rules" attempts), answering only from the provided context. Changed only by an admin via git/review, **never by the chat user**.

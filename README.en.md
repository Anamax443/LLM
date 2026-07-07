# AXIMA Knowledge Assistant

A local **AI assistant (RAG)** over internal company documentation. It answers employee questions from policies, IT procedures, infrastructure and the IP plan — **all data stays on the local server, nothing is sent to the cloud** (ISO 27001 / NIS2). Every answer cites its source, and if it doesn't know, it says so instead of making things up.

> 🇨🇿 Česká verze: [README.md](README.md)

---

## What it does

You ask in natural language (e.g. *"how do I restore a server from backup?"*) → the assistant finds relevant passages in the internal documents, builds a context, lets the local language model generate an answer, and **shows which documents it drew from**.

## Architecture

- **AI backend:** [Ollama](https://ollama.com) (port 11434) — `bge-m3` (1024D embeddings) + `llama3.1` (generation).
- **Vector DB:** [Qdrant](https://qdrant.com) (port 6333), collection `axima_docs`, 1024D, cosine distance.
- **Ingest:** `watchdog_service.py` watches `incoming/`, atomic-moves to `docs/` (to avoid SMB locks), reads DOCX/XLSX/PDF, chunks (1000/200) and upserts into Qdrant.
- **API:** `api.py` (FastAPI, port 8000) — `POST /ask` (streamed), `GET /api/version`, `POST /api/verify` (path availability + dynamic mount), `POST /api/extract` (text from attachments), serves the web UI. Nově: `GET /api/monitored_paths` and `POST /api/set_monitored_paths` pro správu cest z WebUI, vylepšené logování chyb a health checky pro Qdrant a Ollama při startu API, opravené CORS pro WebUI.
- **CLI:** `ask_ai.py` — query from the terminal.
- **Web UI:** `web/index.html` — homepage with Assistant / Settings / Documentation / Management report tabs (per the AXIMA UI standard: dark+light, print in light, CS+EN, **service line in the header** — health, model, commit, clock, GitHub link). Nyní **komunikuje s backendem** pro načítání a ukládání monitorovaných cest.

## Files

| File | Purpose |
|---|---|
| `watchdog_service.py` | Ingest: folder watching, document reading (vč. textových, HTML), chunking, embedding, upsert to Qdrant with source context |
| `api.py` | FastAPI backend (`/ask`, `/api/version`, `/api/verify`, `/api/extract`), serves `web/` |
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
python3 api.py                  # ve druhém → http://SERVER:8000
```

## Web UI — funkčnost

`web/index.html` servíruje `api.py` na `/` (samostatný soubor, bez frameworku, **AXIMA logo** v hlavičce). Záložky:

- **Asistent** — **streamovaný chat** s historií a Markdownem (`POST /ask`); k dotazu lze **přiložit soubory nebo vložit screenshot (Ctrl+V)** — obsah se převede na text (parsery + OCR, `POST /api/extract`) a přidá ke kontextu. Generování lze **zastavit**; při nedostupném backendu ukázkový režim s obecnou chybou.
- **Nastavení** — správa **hlídaných cest** (přidat/odebrat, podadresáře, přípony, aktivní) **načítané z backendu** (`GET /api/monitored_paths`) a **ukládané na backend** (`POST /api/set_monitored_paths`), tlačítko **Ověřit dostupnost cest** + **terminál** (reálný check `POST /api/verify` přes user-space SMB připojení; do ověření je STAV „neověřeno", nefabrikuje se), **Stav skenování**, model/teplota/počet bloků a přepínače „zobrazit v hlavičce". *Cesty spravuje operátor bez zásahu IT.*
- **Dokumentace** — plnohodnotná dokumentace **uvnitř aplikace** (boční menu + články: O aplikaci, Jak to funguje, Jak se ptát, Cesty a skenování, Bezpečnost) ve firemním designu, **bez odkazů na git či soubory**.
- **Manažerský výstup** — netechnický přehled + **tisknutelný přehled rozsahu** báze (s **AXIMA logem** v hlavičce tisku). Tisk je vždy ve světlém režimu.
- Přepínač **CS/EN**, **dark/light**; **servisní řádek v hlavičce** (health, **model** 🧠, commit, live clock, **GitHub** icon) — model and GitHub can be optionally hidden in Settings. `GET /api/version` contract.

## Roadmap (re-prioritised after peer review)

1. **Core verification** — reconciliation cycle over SMB (mtime/size **+ ACL**, hash only changed files) + Linux → SQL19 connectivity.
2. **Access control (MVP, deployment prerequisite)** — AD/Entra authentication, per-document ACL indexing, results filtered by identity. Without it, RAG flattens NTFS permissions = a security regression. **ACL freshness:** the scan also tracks the security descriptor (a permission change doesn't alter mtime), with authorization by the user's transitive group membership.
3. **Verzování dokumentů** — `on_deleted`, relativní cesta, Qdrant payload index.
4. **Test set + model benchmark** — embedding (nomic vs multilingual-e5 / BGE-m3, for Czech) and generative (incl. quantisation).
5. **Parsing** — OCR and structure-aware table handling (XLSX/PDF).
6. **Hybrid search** — Qdrant **dense + sparse** vectors + RRF/rerank (native in Qdrant for speed, not SQL FTS).
7. **Speed** — answer streaming, model/GPU choice.
8. **Operations** — monitoring, DR, systemd, audit with PII masking, feedback loop.
9. **Separate phase:** live data from Dynamics 365 BC via text-to-SQL (own risk profile).

**SQL Server 2019** serves as sync-state manifest, audit (with PII masking) and later a live data source — **not** as a vector DB or search engine. **Editable paths in Settings** (operator, no IT), stored in `monitored_paths.json`, applied by the reconciliation scan; removal deletes from the base.

Decision rationale, risks, NFRs, capacity, DR and TCO: **[docs/OPONENTURA.md](docs/OPONENTURA.md)** (Czech). Live status: [docs/HANDOFF.md](docs/HANDOFF.md).

## Security

Company documents (`*.docx`, `*.pdf`, `*.xlsx`, …) and the `incoming/` folder are gitignored to prevent leaking data (documentation under `docs/` is versioned). Connection credentials belong in `.env` (see `.env.example`), **not in Git**.

**Assistant guardrails** live in code (`SYSTEM_PROMPT` in `api.py`, the `system` field) — no persona, **prompt-injection resistant** (ignore "change your role/rules" attempts), answering only from the provided context. Changed only by an admin via git/review, **never by the chat user**.

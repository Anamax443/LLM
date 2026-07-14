# BUILD — build the system from scratch

Build manual. The goal is for an administrator **with no prior knowledge** to build the entire AXIMA Knowledge Assistant from a clean Linux server, step by step.

> 🇨🇿 Česky: [BUILD.md](BUILD.md)

---

## 0. Target state overview

A single Linux server runs:

| Component | Port | Purpose |
|---|---|---|
| Ollama | 11434 | runs AI models (embedding + generation) |
| Qdrant | 6333 | vector database |
| `api.py` (FastAPI) | 8000 | web API + serves UI |
| `watchdog_service.py` | — | reconciliation ingest (periodic scan of monitored paths) |
| SQL Server 2019 | 1433 | *(roadmap)* manifest + audit + hybrid search |

Recommended: a server with a **GPU** (for `mistral-nemo` generation speed), min. 16 GB RAM, enough disk for models (~10 GB) and vectors.

> **Sign-in is mandatory:** the app sits behind **Microsoft Entra ID (SSO)**. Before deploying you need an Azure App registration and the values `ENTRA_TENANT_ID`, `ENTRA_CLIENT_ID`, `ENTRA_CLIENT_SECRET` — see step 5. Set the Azure redirect URI to `https://SERVER/api/auth/callback`.

---

## 1. Server prep (Ubuntu)

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-venv python3-pip git docker.io
sudo usermod -aG docker $USER && newgrp docker
```

## 2. Qdrant (vector database)

```bash
mkdir -p ~/ai-axima/qdrant_storage
docker run -d --name qdrant --restart always \
  -p 6333:6333 \
  -v ~/ai-axima/qdrant_storage:/qdrant/storage \
  qdrant/qdrant
```
Verify: `curl http://localhost:6333/healthz`.

## 3. Ollama + models

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull bge-m3               # embedding, 1024D — MUST match the Qdrant collection
ollama pull mistral-nemo         # answer generation
```

> ⚠️ **Dimensions must match.** `watchdog_service.py` creates the `axima_docs` collection at **1024D**. `bge-m3` is 1024D. If you change the embedding model, change the collection dimension too, or upsert will fail. *(Note: an inline code comment near collection creation still wrongly says "768" — but the actual `size=1024` is correct.)*

## 4. Code and Python environment

```bash
cd ~/ai-axima
git clone https://github.com/Axima-Git/LLM.git .
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

**Query attachments:** the `POST /api/extract` endpoint reads **PDF** (`pypdf`), **DOCX** (`python-docx`), **images/screenshots via OCR** (`pytesseract`, languages `ces+eng`) and plain text (UTF-8 fallback). Upload requires `python-multipart` (in `requirements.txt`) — without it attachments don't work at all.

Image OCR additionally needs the **system** tesseract package (Python `pytesseract`/`Pillow` are in `requirements.txt`):
```bash
sudo apt install -y tesseract-ocr tesseract-ocr-ces
```
Without tesseract / language data OCR **won't crash** — it returns a clear message for the image and the query continues. **OCR for scanned PDFs is not implemented yet** (roadmap item "Parsing").

## 5. Configuration (.env)

```bash
cp .env.example .env
nano .env
```
`.env` holds credentials and paths. **Never committed.** Minimum to run:
```ini
ENTRA_TENANT_ID=...          # Directory (tenant) ID from the Azure App registration
ENTRA_CLIENT_ID=...          # Application (client) ID
ENTRA_CLIENT_SECRET=...      # client secret (the value, not its ID)
SESSION_SECRET=...           # a strong random string to sign the session cookie
RECONCILIATION_INTERVAL_SEC=900   # scan interval (prod); dev default 30
MONITORED_PATHS=/data/...,//herkules/public/smernice   # fallback when the API is down
```

## 6. Monitored paths and network storage

Ingest is a **reconciliation scan**: `watchdog_service.py` periodically walks the monitored paths, diffs against `reconciliation_manifest.json` (mtime + size) and processes only new/changed files (deleting blocks of files that disappeared). **No `incoming`/`docs` folders are needed** — files are read directly from the path (local) or streamed into `tempfile.TemporaryDirectory` (SMB). Currently only **`.docx` and `.pdf`** are indexed.

Monitored paths are managed by the operator in the UI (Settings) → stored in `monitored_paths.json`, which the scan reads via `GET /api/monitored_paths`. When the API is down, the `MONITORED_PATHS` fallback from `.env` is used.

### Network paths (UNC) — user-space SMB, no OS mount
The operator enters paths as `\\server\share\...`. The Linux backend accesses them **directly in user space** via the `smbclient` library (over `smbprotocol`) with **Kerberos** authentication (gMSA) — **no `cifs-utils`, no root, no OS mounts**. NetBIOS names are auto-completed to FQDN (domain `axinetwork.loc`), the Kerberos ccache is at `KRB5CCNAME=FILE:/home/aixima/krb5cc_axima`.

- Manual Linux steps (gMSA, keytab with `400`, ticket renewal via a systemd timer): **[LINUX_SETUP_GUIDE.md](LINUX_SETUP_GUIDE.md)**.
- Architecture rationale (why user-space instead of a mount): **[SPOJENI_FILE_SERVERU.md](SPOJENI_FILE_SERVERU.md)** (Czech).

## 7. Run

```bash
source venv/bin/activate
python3 watchdog_service.py        # terminal 1 — ingest
python3 api.py                     # terminal 2 — API + web UI (0.0.0.0:8000)
```
For production, run as **systemd services** (auto-start, restart). The repo ships a sample unit **`axima-web.service`** for the API + web UI (adjust paths/user for your deployment). The Kerberos ticket for SMB is renewed by a separate timer (see [LINUX_SETUP_GUIDE.md](LINUX_SETUP_GUIDE.md)).

## 8. Web UI

`api.py` serves `web/index.html` at the root:
```
http://SERVER:8000/
```
The UI is behind sign-in (Entra ID). The endpoints it actually uses: `POST /ask` (SSE), `GET /config`, `GET /api/version`, `GET/POST /api/monitored_paths`, `POST /api/verify`, `POST /api/extract` and `GET /api/auth/*` (login/callback/me/logout).

## 9. Verify the whole chain (verify-core)

1. In the UI → **Settings** add a monitored path (a local folder or `\\server\share`) containing a test `.docx`/`.pdf` and save. On the next cycle the `watchdog_service.py` log shows `[SUCCESS] Uloženo N bloků`.
2. CLI query: `python3 ask_ai.py "question from that document"` → sensible answer with context.
3. Open `http://SERVER:8000/` → **sign in (Entra ID)** → Assistant tab → same query → answer + sources.
4. The header service line shows the **commit hash** and a green health dot.

**Before running production over network paths, verify section 6** — the reconciliation cycle (primarily `LastWriteTime`+size, hashing only changed files) and Linux → SQL19 connectivity.

> ⚠️ **Access control is mandatory before production.** Without authentication (AD/Entra) and result filtering by user permissions, RAG **flattens NTFS rights** — anyone would receive the content of any indexed document. The reconciliation scan must also track the **ACL/security descriptor** (a permission change doesn't alter mtime/size, otherwise a stale ACL remains in Qdrant) and authorize at query time by the user's transitive membership. See [OPONENTURA.md](OPONENTURA.md) §4.4/5.1 (Czech) and roadmap step 2. The prototype may only run in a closed environment with non-confidential data.

## 10. SQL Server 2019 (roadmap)

```bash
sudo apt install -y unixodbc-dev
# install "ODBC Driver 18 for SQL Server" (Microsoft repo)
pip install pyodbc
```
Add `SQL_CONN` to `.env`. Access the production DB (Dynamics 365 BC) **read-only** via views; keep manifest/audit in a **dedicated** database on the instance.

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
| `watchdog_service.py` | — | continuous document ingest |
| SQL Server 2019 | 1433 | *(roadmap)* manifest + audit + hybrid search |

Recommended: a server with a **GPU** (for `llama3.1` generation speed), min. 16 GB RAM, enough disk for models (~10 GB) and vectors.

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
ollama pull nomic-embed-text     # embedding, 768D — MUST match the Qdrant collection
ollama pull llama3.1             # answer generation
```

> ⚠️ **Dimensions must match.** `watchdog_service.py` creates the `axima_docs` collection at 768D. `nomic-embed-text` is 768D. If you change the embedding model, change the collection dimension too, or upsert will fail.

## 4. Code and Python environment

```bash
cd ~/ai-axima
git clone https://github.com/Axima-Git/LLM.git .
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

## 5. Configuration (.env)

```bash
cp .env.example .env
nano .env
```
`.env` holds connection credentials and paths. **Never committed.**

## 6. Data folders and network paths

Ingest separates the **upload** and **working** folders (to avoid SMB locks):
```bash
mkdir -p /data/llm-demo/watchdog/incoming
mkdir -p /data/llm-demo/watchdog/docs
```

### Network paths — IMPORTANT
If documents live on **network storage (SMB/CIFS/NFS)**, `watchdog` (inotify) **may not fire events** — inotify is unreliable over network mounts. The target model is therefore a **reconciliation scan** (periodic tree walk + diff against DB state), which needs no inotify. Until it ships, use the local `incoming/` folder (which Samba copies into) rather than watching the network path directly. See [HANDOFF.md](HANDOFF.md).

> **UNC → mount (deployment):** the operator enters paths as `\\server\share\...`, but Linux can't open them directly — the share must be **mounted** (e.g. `\\herkules\public\LumirLiduMil` → `/mnt/herkules/public/LumirLiduMil`). Without a mount, `os.path.isdir` (hence `/api/verify`) always returns "unavailable". On deployment, either mount every watched share or add a **UNC→mount map** in the backend that translates the entered UNC path to the local mount point.

## 7. Run

```bash
source venv/bin/activate
python3 watchdog_service.py        # terminal 1 — ingest
python3 api.py                     # terminal 2 — API + web UI (0.0.0.0:8000)
```
For production, run as **systemd services** (auto-start, restart).

## 8. Web UI

`api.py` serves `web/index.html` at the root:
```
http://SERVER:8000/
```
The UI expects `POST /ask` (working) and `GET /api/version` (working); `GET /api/scope` and `POST /api/settings` are ready to be wired (roadmap).

## 9. Verify the whole chain (verify-core)

1. Copy a test `.docx` into `incoming/` → watchdog log shows `[SUCCESS] Uloženo N bloků`.
2. CLI query: `python3 ask_ai.py "question from that document"` → sensible answer with context.
3. Open `http://SERVER:8000/` → Assistant tab → same query → answer + sources.
4. Footer shows the **commit hash** and a green health dot.

**Before running production over network paths, verify section 6** — the reconciliation cycle (primarily `LastWriteTime`+size, hashing only changed files) and Linux → SQL19 connectivity.

> ⚠️ **Access control is mandatory before production.** Without authentication (AD/Entra) and result filtering by user permissions, RAG **flattens NTFS rights** — anyone would receive the content of any indexed document. The reconciliation scan must also track the **ACL/security descriptor** (a permission change doesn't alter mtime/size, otherwise a stale ACL remains in Qdrant) and authorize at query time by the user's transitive membership. See [OPONENTURA.md](OPONENTURA.md) §4.4/5.1 (Czech) and roadmap step 2. The prototype may only run in a closed environment with non-confidential data.

## 10. SQL Server 2019 (roadmap)

```bash
sudo apt install -y unixodbc-dev
# install "ODBC Driver 18 for SQL Server" (Microsoft repo)
pip install pyodbc
```
Add `SQL_CONN` to `.env`. Access the production DB (Dynamics 365 BC) **read-only** via views; keep manifest/audit in a **dedicated** database on the instance.

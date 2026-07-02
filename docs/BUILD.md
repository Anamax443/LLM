# BUILD — postavení systému od nuly

Výrobní návod. Cílem je, aby administrátor **bez předchozí znalosti** postavil celý AXIMA Znalostní Asistent od čistého Linux serveru. Napsáno krok za krokem.

> 🇬🇧 English: [BUILD.en.md](BUILD.en.md)

---

## 0. Přehled cílového stavu

Na jednom Linux serveru poběží:

| Komponenta | Port | Účel |
|---|---|---|
| Ollama | 11434 | běh AI modelů (embedding + generování) |
| Qdrant | 6333 | vektorová databáze |
| `api.py` (FastAPI) | 8000 | web API + servírování UI |
| `watchdog_service.py` | — | průběžný ingest dokumentů |
| SQL Server 2019 | 1433 | *(roadmapa)* manifest + audit + hybridní hledání |

Doporučení: server s **GPU** (kvůli rychlosti generování `llama3.1`), min. 16 GB RAM, dostatek disku na modely (~10 GB) a vektory.

---

## 1. Příprava serveru (Ubuntu)

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-venv python3-pip git docker.io
sudo usermod -aG docker $USER && newgrp docker
```

## 2. Qdrant (vektorová databáze)

```bash
mkdir -p ~/ai-axima/qdrant_storage
docker run -d --name qdrant --restart always \
  -p 6333:6333 \
  -v ~/ai-axima/qdrant_storage:/qdrant/storage \
  qdrant/qdrant
```
Ověření: `curl http://localhost:6333/healthz` → `healthz check passed`.

## 3. Ollama + modely

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull nomic-embed-text     # embedding, 768D — MUSÍ sedět s Qdrant kolekcí
ollama pull llama3.1             # generování odpovědí
```
Ověření: `curl http://localhost:11434/api/tags` vypíše oba modely.

> ⚠️ **Dimenze musí sedět.** `watchdog_service.py` vytváří kolekci `axima_docs` s 768D. `nomic-embed-text` má 768D. Když změníte embedding model, upravte i dimenzi kolekce (jinak upsert selže).

## 4. Kód a Python prostředí

```bash
cd ~/ai-axima
git clone https://github.com/Axima-Git/LLM.git .
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

## 5. Konfigurace (.env)

Zkopírujte vzor a upravte:
```bash
cp .env.example .env
nano .env
```
`.env` drží připojovací údaje a cesty (viz `.env.example`). **Nikdy se necommituje.**

## 6. Datové složky a síťové cesty

Ingest odděluje **nahrávací** a **pracovní** složku (kvůli SMB zámkům):
```bash
mkdir -p /data/llm-demo/watchdog/incoming
mkdir -p /data/llm-demo/watchdog/docs
```
- **`incoming/`** — sem se kopírují dokumenty (např. přes Sambu z Windows).
- **`docs/`** — pracovní adresář, kam se soubory přesouvají atomic-move.

### Síťové cesty — DŮLEŽITÉ
Pokud dokumenty leží na **síťovém úložišti (SMB/CIFS/NFS)**, `watchdog` (inotify) **nemusí generovat události** — inotify nefunguje spolehlivě přes síťové mounty. Cílový model je proto **reconciliation sken** (periodické projití stromu + porovnání se stavem v DB), který inotify nepotřebuje. Do doby jeho nasazení používejte lokální `incoming/` (kam Samba kopíruje), ne přímé hlídání síťové cesty. Viz [HANDOFF.md](HANDOFF.md).

> **UNC → mount (deployment):** operátor zadává cesty ve tvaru `\\server\share\...`, ale Linux je sám neotevře — share musí být **namountovaný** (např. `\\herkules\public\LumirLiduMil` → `/mnt/herkules/public/LumirLiduMil`). Bez mountu vrátí `os.path.isdir` (a tedy `/api/verify`) vždy „nedostupná". Při nasazení buď mountovat všechny sledované share, nebo doplnit v backendu **mapu UNC→mount**, která zadanou UNC cestu přeloží na lokální mount point.

## 7. Spuštění

```bash
source venv/bin/activate
python3 watchdog_service.py        # terminál 1 — ingest
python3 api.py                     # terminál 2 — API + web UI (0.0.0.0:8000)
```
Pro produkci nastavte jako **systemd služby** (auto-start, restart). Vzorové unit soubory přidejte do `deploy/` (roadmapa).

## 8. Web UI

`api.py` servíruje `web/index.html` na kořeni:
```
http://SERVER:8000/
```
UI čeká endpointy `POST /ask` (funkční) a `GET /api/version` (funkční); `GET /api/scope` a `POST /api/settings` jsou připravené na napojení (roadmapa).

## 9. Ověření celého řetězce (verify-core)

1. Zkopírujte testovací `.docx` do `incoming/` → v logu watchdogu se objeví `[SUCCESS] Uloženo N bloků`.
2. Dotaz z CLI: `python3 ask_ai.py "otázka z toho dokumentu"` → smysluplná odpověď s kontextem.
3. Otevřete `http://SERVER:8000/` → záložka Asistent → stejný dotaz → odpověď + zdroje.
4. Patička ukazuje **commit hash** a zelený health.

**Než se spustí ostrý provoz nad síťovými cestami, ověřte bod „Síťové cesty" (6)** — reconciliation cyklus (primárně `LastWriteTime`+velikost, hash jen u změněných souborů) a konektivitu Linux → SQL19.

> ⚠️ **Před produkčním nasazením je povinné řízení přístupu.** Bez autentizace (AD/Entra) a filtru výsledků podle oprávnění uživatele RAG **zplošťuje NTFS práva** — každý by dostal obsah libovolného naindexovaného dokumentu. Reconciliation přitom musí sledovat i **ACL/security-descriptor** (změna práv nemění mtime/velikost, jinak zůstane v Qdrantu stará ACL) a autorizovat za běhu dle tranzitivního členství uživatele. Viz [OPONENTURA.md](OPONENTURA.md) kap. 4.4/5.1 a roadmapa krok 2. Prototyp lze provozovat jen v uzavřeném prostředí s neutajovanými daty.

## 10. SQL Server 2019 (roadmapa)

Až se zapojí manifest/audit/hybridní hledání:
```bash
sudo apt install -y unixodbc-dev
# nainstalovat "ODBC Driver 18 for SQL Server" (Microsoft repo)
pip install pyodbc
```
Do `.env` doplnit `SQL_CONN`. K produkční DB (Dynamics 365 BC) přistupovat **read-only** přes views; manifest/audit ve **vlastní** databázi na instanci.

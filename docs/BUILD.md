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
| `watchdog_service.py` | — | reconciliation ingest (periodický sken hlídaných cest) |
| SQL Server 2019 | 1433 | *(roadmapa)* manifest + audit + hybridní hledání |

Doporučení: server s **GPU** (kvůli rychlosti generování `mistral-nemo`), min. 16 GB RAM, dostatek disku na modely (~10 GB) a vektory.

> **Přihlášení je povinné:** aplikace je za **Microsoft Entra ID (SSO)**. Před nasazením potřebujete v Azuru registraci aplikace (App registration) a hodnoty `ENTRA_TENANT_ID`, `ENTRA_CLIENT_ID`, `ENTRA_CLIENT_SECRET` — viz krok 5. Redirect URI v Azuru nastavte na `https://SERVER/api/auth/callback`.

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
ollama pull bge-m3               # embedding, 1024D — MUSÍ sedět s Qdrant kolekcí
ollama pull mistral-nemo         # generování odpovědí
```
Ověření: `curl http://localhost:11434/api/tags` vypíše oba modely.

> ⚠️ **Dimenze musí sedět.** `watchdog_service.py` vytváří kolekci `axima_docs` s **1024D**. `bge-m3` má 1024D. Když změníte embedding model, upravte i dimenzi kolekce (jinak upsert selže). *(Pozn.: inline komentář u vytvoření kolekce v kódu ještě chybně říká „768" — ale reálná hodnota `size=1024` je správná.)*

## 4. Kód a Python prostředí

```bash
cd ~/ai-axima
git clone https://github.com/Axima-Git/LLM.git .
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

**Přílohy k dotazu:** endpoint `POST /api/extract` čte **PDF** (`pypdf`), **DOCX** (`python-docx`), **obrázky/screenshoty přes OCR** (`pytesseract`, jazyky `ces+eng`) a prostý text (UTF-8 fallback). Upload vyžaduje `python-multipart` (v `requirements.txt`) — bez něj přílohy nefungují vůbec.

Pro OCR obrázků je navíc nutný **systémový** balík tesseractu (Python `pytesseract`/`Pillow` jsou v `requirements.txt`):
```bash
sudo apt install -y tesseract-ocr tesseract-ocr-ces
```
Bez tesseractu / jazykových dat OCR **nespadne** — u obrázku vrátí srozumitelnou hlášku a dotaz pokračuje. **OCR skenovaných PDF zatím není** (položka roadmapy „Parsing").

## 5. Konfigurace (.env)

Zkopírujte vzor a upravte:
```bash
cp .env.example .env
nano .env
```
`.env` drží připojovací údaje a cesty (viz `.env.example`). **Nikdy se necommituje.** Minimum pro provoz:
```ini
ENTRA_TENANT_ID=...          # Directory (tenant) ID z Azure App registration
ENTRA_CLIENT_ID=...          # Application (client) ID
ENTRA_CLIENT_SECRET=...      # client secret (hodnota, ne ID)
SESSION_SECRET=...           # náhodný silný řetězec pro podpis session cookie
RECONCILIATION_INTERVAL_SEC=900   # interval skenu (prod), dev default 30
MONITORED_PATHS=/data/...,//herkules/public/smernice   # fallback, když neběží API
```

## 6. Hlídané cesty a síťové úložiště

Ingest je **reconciliation sken**: `watchdog_service.py` v pravidelném intervalu projde hlídané cesty, porovná stav se souborem `reconciliation_manifest.json` (mtime + velikost) a zpracuje jen nové/změněné soubory (a smaže bloky těch, co zmizely). **Žádné složky `incoming`/`docs` už nejsou potřeba** — soubory se čtou přímo z cesty (lokálně) nebo se stahují do `tempfile.TemporaryDirectory` (SMB). Aktuálně se indexují jen **`.docx` a `.pdf`**.

Hlídané cesty spravuje operátor v UI (Nastavení) → uloží se do `monitored_paths.json`, odkud je sken čte přes `GET /api/monitored_paths`. Když API neběží, použije se fallback `MONITORED_PATHS` z `.env`.

### Síťové cesty (UNC) — user-space SMB, žádný OS mount
Operátor zadává cesty ve tvaru `\\server\share\...`. Linux backend k nim přistupuje **přímo v uživatelském prostoru** přes knihovnu `smbclient` (nad `smbprotocol`) s **Kerberos** autentizací (gMSA) — **bez `cifs-utils`, bez root a bez OS mountů**. NetBIOS jména se automaticky doplňují na FQDN (doména `axinetwork.loc`), Kerberos ccache je v `KRB5CCNAME=FILE:/home/aixima/krb5cc_axima`.

- Manuální kroky na Linuxu (gMSA, keytab s právy `400`, obnova lístku přes systemd timer): **[LINUX_SETUP_GUIDE.md](LINUX_SETUP_GUIDE.md)**.
- Architektonický návrh a zdůvodnění (proč user-space místo mountu): **[SPOJENI_FILE_SERVERU.md](SPOJENI_FILE_SERVERU.md)**.

## 7. Spuštění

```bash
source venv/bin/activate
python3 watchdog_service.py        # terminál 1 — ingest
python3 api.py                     # terminál 2 — API + web UI (0.0.0.0:8000)
```
Pro produkci nastavte jako **systemd služby** (auto-start, restart). V repu je vzorová unit **`axima-web.service`** pro API + web UI (upravte cesty/uživatele podle svého nasazení). Kerberos lístek pro SMB obnovuje samostatný timer (viz [LINUX_SETUP_GUIDE.md](LINUX_SETUP_GUIDE.md)).

## 8. Web UI

`api.py` servíruje `web/index.html` na kořeni:
```
http://SERVER:8000/
```
UI je za přihlášením (Entra ID). Reálné endpointy, které používá: `POST /ask` (SSE), `GET /config`, `GET /api/version`, `GET/POST /api/monitored_paths`, `POST /api/verify`, `POST /api/extract` a `GET /api/auth/*` (login/callback/me/logout).

## 9. Ověření celého řetězce (verify-core)

1. V UI → **Nastavení** přidejte hlídanou cestu (lokální složku nebo `\\server\share`) s testovacím `.docx`/`.pdf` a uložte. V logu `watchdog_service.py` se v dalším cyklu objeví `[SUCCESS] Uloženo N bloků`.
2. Dotaz z CLI: `python3 ask_ai.py "otázka z toho dokumentu"` → smysluplná odpověď s kontextem.
3. Otevřete `http://SERVER:8000/` → **přihlaste se (Entra ID)** → záložka Asistent → stejný dotaz → odpověď + zdroje.
4. Servisní řádek v hlavičce ukazuje **commit hash** a zelený health.

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

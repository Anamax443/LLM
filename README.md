# AXIMA Znalostní Asistent

Lokální **AI asistent (RAG)** nad interní firemní dokumentací. Odpovídá na dotazy zaměstnanců na základě směrnic, IT postupů, infrastruktury a IP plánu — **veškerá data zůstávají na lokálním serveru, nic se neodesílá do cloudu** (ISO 27001 / NIS2). U každé odpovědi uvádí zdroj a pokud odpověď nezná, řekne to a nevymýšlí si.

> 🇬🇧 English version: [README.en.md](README.en.md)

---

## Co to dělá

Zeptáte se přirozeným jazykem (např. *„jak obnovit server ze zálohy?"*) → asistent najde v interních dokumentech relevantní pasáže, sestaví z nich kontext, nechá lokální jazykový model vygenerovat odpověď a **ukáže, ze kterých dokumentů čerpal**.

## Architektura

```
                     ┌─────────────────────────────────────────────┐
Síťové cesty (dynamicky mountované)             │  watchdog_service.py  (ingest / datová pumpa)│
  (\\fileserver\..)                       │  čte DOCX/XLSX/PDF → chunkuje → embeduje      │
        │            └───────────────┬─────────────────────────────┘
        ▼                            ▼
  incoming/ → docs/            Ollama (embeddings)          Qdrant
  (atomic move kvůli SMB)      nomic-embed-text (768D)  →   kolekce axima_docs
                                                             (vektory)
  Uživatel ─┐
            ▼
  web/index.html  ──POST /ask──►  api.py (FastAPI)  ──►  Qdrant (hledání)
  (homepage,                                          └─► Ollama llama3.1 (generování)
   4 záložky)     ◄──odpověď + zdroje──
```

- **AI backend:** [Ollama](https://ollama.com) (port 11434) — `bge-m3` (1024D embeddingy) + `llama3.1` (generování).
- **Vektorová DB:** [Qdrant](https://qdrant.tech) (port 6333), kolekce `axima_docs`, 1024D, kosinová vzdálenost.
- **Ingest:** `watchdog_service.py` sleduje `incoming/`, atomic-move do `docs/` (kvůli SMB zámkům), čte DOCX/XLSX/PDF, chunkuje (1000/200) a upsertuje do Qdrantu.
- **API:** `api.py` (FastAPI, port 8000) — `POST /ask` (streamovaně), `GET /api/version`, `POST /api/verify` (dostupnost cest + dynamic mount), `POST /api/extract` (text z příloh), servíruje web UI. Nově: `GET /api/monitored_paths` a `POST /api/set_monitored_paths` pro správu cest z WebUI, vylepšené logování chyb a health checky pro Qdrant a Ollama při startu API, opravené CORS pro WebUI.
- **CLI:** `ask_ai.py` — dotaz z terminálu.
- **Web UI:** `web/index.html` — homepage se záložkami Asistent / Nastavení / Dokumentace / Manažerský výstup (dle AXIMA UI standardu: dark+light, tisk light, CZ+EN, **servisní řádek v hlavičce** — health, model, commit, hodiny, GitHub odkaz). Nyní **komunikuje s backendem** pro načítání a ukládání monitorovaných cest.

## Soubory

| Soubor | Účel |
|---|---|
| `watchdog_service.py` | Ingest: sledování složky, čtení dokumentů (vč. textových, HTML), chunkování, vektorizace, upsert do Qdrantu s kontextem zdrojového dokumentu |
| `api.py` | FastAPI backend (`/ask`, `/api/version`, `/api/verify`, `/api/extract`), servírování `web/` |
| `ask_ai.py` | CLI klient pro dotazování |
| `web/index.html` | Homepage / UI (samostatný soubor, bez frameworku) |
| `dokumentace.md` | Technická dokumentace (architektura, provoz, známé problémy a řešení, průvodci nastavením) |
| `docs/BUILD.md` | **Výrobní návod — postavení celého systému od nuly** |
| `docs/HANDOFF.md` | Aktuální stav projektu a přijatá rozhodnutí |
| `docs/OPONENTURA.md` | Obhajovací podklad (rozhodnutí, rizika, NFR, kapacita, DR, TCO) |
| `docs/JAK-FUNGUJE-UCENI.md` | Netechnické vysvětlení „jak model umí naše data" (RAG vs fine-tuning) |
| `requirements.txt` | Python závislosti |

## Rychlý start

Kompletní postup od čistého serveru je v **[docs/BUILD.md](docs/BUILD.md)**. Ve zkratce:

```bash
# 1) Qdrant (Docker)
docker run -d -p 6333:6333 -v $(pwd)/qdrant_storage:/qdrant/storage qdrant/qdrant

# 2) Ollama + modely
ollama pull nomic-embed-text
ollama pull llama3.1

# 3) Python prostředí
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 4) Ingest (naslouchání složce) + API
python3 watchdog_service.py     # v jednom terminálu
python3 api.py                  # ve druhém → http://SERVER:8000
```

## Web UI — funkčnost

`web/index.html` servíruje `api.py` na `/` (samostatný soubor, bez frameworku, **AXIMA logo** v hlavičce). Záložky:

- **Asistent** — **streamovaný chat** s historií a Markdownem (`POST /ask`); k dotazu lze **přiložit soubory nebo vložit screenshot (Ctrl+V)** — obsah se převede na text (parsery + OCR, `POST /api/extract`) a přidá ke kontextu. Generování lze **zastavit**; při nedostupném backendu ukázkový režim s obecnou chybovou hláškou.
- **Nastavení** — správa **hlídaných cest** (přidat/odebrat, podadresáře, přípony, aktivní) **načítané z backendu** (`GET /api/monitored_paths`) a **ukládané na backend** (`POST /api/set_monitored_paths`), tlačítko **Ověřit dostupnost cest** + **terminál** (reálný check `POST /api/verify` přes user-space SMB připojení; do ověření je STAV „neověřeno", nefabrikuje se), **Stav skenování**, model/teplota/počet bloků a přepínače „zobrazit v hlavičce". *Cesty spravuje operátor bez zásahu IT.*
- **Dokumentace** — plnohodnotná dokumentace **uvnitř aplikace** (boční menu + články: O aplikaci, Jak to funguje, Jak se ptát, Cesty a skenování, Bezpečnost) ve firemním designu, **bez odkazů na git či soubory**.
- **Manažerský výstup** — netechnický přehled + **tisknutelný přehled rozsahu** báze (s **AXIMA logem** v hlavičce tisku). Tisk je vždy ve světlém režimu.
- Přepínač **CS/EN**, **dark/light**; **servisní řádek v hlavičce** (health, **model** 🧠, commit, živé hodiny, **GitHub** ikona) — model a GitHub lze volitelně skrýt v Nastavení. Kontrakt `GET /api/version`.

## Roadmapa (reprioritizováno po oponentuře)

1. **Ověření jádra** — reconciliation cyklus na SMB (mtime/size **+ ACL**, hash jen změněných) + konektivita Linux → SQL19.
2. **Řízení přístupu (MVP, podmínka nasazení)** — AD/Entra autentizace, indexace ACL u dokumentu, filtr výsledků dle identity. Bez toho RAG zplošťuje NTFS oprávnění = bezpečnostní regrese. **Čerstvost ACL:** sken sleduje i security-descriptor (změna práv nemění mtime), autorizace dle tranzitivního členství uživatele.
3. **Verzování dokumentů** — `on_deleted`, relativní cesta, Qdrant payload index.
4. **Testovací sada + benchmark modelů** — embedding (nomic vs multilingual-e5 / BGE-m3, kvůli češtině) i generativních (vč. kvantizace).
5. **Parsing** — OCR a struktura-aware zpracování tabulek (XLSX/PDF).
6. **Hybridní hledání** — Qdrant **dense + sparse** vektory + RRF/rerank (kvůli rychlosti nativně v Qdrantu, ne SQL FTS).
7. **Rychlost** — streaming odpovědí, volba modelu/GPU.
8. **Provoz** — monitoring, DR, systemd, audit s maskováním PII, feedback smyčka.
9. **Samostatná fáze:** živá data z Dynamics 365 BC přes text-to-SQL (vlastní rizikový profil).

**SQL Server 2019** slouží jako manifest stavu syncu, audit (s maskováním PII) a později živý datový zdroj — **ne** jako vektorová DB ani search engine. **Editovatelné cesty v Nastavení** (operátorem, bez IT), uložené v `monitored_paths.json`, promítané reconciliation skenem; odebrání = smazání z báze.

Obhajoba rozhodnutí, rizika, NFR, kapacita, DR a TCO: **[docs/OPONENTURA.md](docs/OPONENTURA.md)**. Živý stav: [docs/HANDOFF.md](docs/HANDOFF.md).

## Bezpečnost

Firemní dokumenty (`*.docx`, `*.pdf`, `*.xlsx`, …) a složka `incoming/` jsou v `.gitignore`, aby nedošlo k úniku dat (dokumentace v `docs/` se naopak verzuje). Připojovací údaje patří do `.env` (viz `.env.example`), **nikdy ne do Gitu**.

**Guardrails asistenta** jsou v kódu (`SYSTEM_PROMPT` v `api.py`, pole `system`) — bez persony, **odolné vůči prompt injection** (ignorují pokusy „změň roli/pravidla"), odpovídají jen z dodaného kontextu. Mění je jen admin přes git/review, **nikdy uživatel v chatu**.

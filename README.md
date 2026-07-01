# AXIMA Znalostní Asistent

Lokální **AI asistent (RAG)** nad interní firemní dokumentací. Odpovídá na dotazy zaměstnanců na základě směrnic, IT postupů, infrastruktury a IP plánu — **veškerá data zůstávají na lokálním serveru, nic se neodesílá do cloudu** (ISO 27001 / NIS2). U každé odpovědi uvádí zdroj a pokud odpověď nezná, řekne to a nevymýšlí si.

> 🇬🇧 English version: [README.en.md](README.en.md)

---

## Co to dělá

Zeptáte se přirozeným jazykem (např. *„jak obnovit server ze zálohy?"*) → asistent najde v interních dokumentech relevantní pasáže, sestaví z nich kontext, nechá lokální jazykový model vygenerovat odpověď a **ukáže, ze kterých dokumentů čerpal**.

## Architektura

```
                     ┌─────────────────────────────────────────────┐
  Síťové cesty       │  watchdog_service.py  (ingest / datová pumpa)│
  (\\fileserver\..)  │  čte DOCX/XLSX/PDF → chunkuje → embeduje      │
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

- **AI backend:** [Ollama](https://ollama.com) (port 11434) — `nomic-embed-text` (768D embeddingy) + `llama3.1` (generování).
- **Vektorová DB:** [Qdrant](https://qdrant.tech) (port 6333), kolekce `axima_docs`, 768D, kosinová vzdálenost.
- **Ingest:** `watchdog_service.py` sleduje `incoming/`, atomic-move do `docs/` (kvůli SMB zámkům), čte DOCX/XLSX/PDF, chunkuje (1000/200) a upsertuje do Qdrantu.
- **API:** `api.py` (FastAPI, port 8000) — `POST /ask`, `GET /api/version`, servíruje web UI.
- **CLI:** `ask_ai.py` — dotaz z terminálu.
- **Web UI:** `web/index.html` — homepage se záložkami Asistent / Nastavení / Dokumentace / Manažerský výstup (dle AXIMA UI standardu: dark+light, tisk light, CZ+EN, servisní patička s commit hashem).

## Soubory

| Soubor | Účel |
|---|---|
| `watchdog_service.py` | Ingest: sledování složky, čtení dokumentů, chunkování, vektorizace, upsert do Qdrantu |
| `api.py` | FastAPI backend (`/ask`, `/api/version`), servírování `web/` |
| `ask_ai.py` | CLI klient pro dotazování |
| `web/index.html` | Homepage / UI (samostatný soubor, bez frameworku) |
| `dokumentace.md` | Technická dokumentace (architektura, provoz, known issues) |
| `docs/BUILD.md` | **Výrobní návod — postavení celého systému od nuly** |
| `docs/HANDOFF.md` | Aktuální stav projektu a přijatá rozhodnutí |
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

`web/index.html` servíruje `api.py` na `/`. Vlastnosti:

- **Asistent** — chat proti `POST /ask`; při nedostupném backendu ukázkový režim.
- **Nastavení** — správa hlídaných cest (přidat/odebrat, podadresáře, přípony, aktivní), model, teplota, počet bloků. *Cesty jsou editovatelné operátorem — bez zásahu IT.*
- **Dokumentace** — rozcestník (README, BUILD, technická dokumentace, HANDOFF), tisknutelný.
- **Manažerský výstup** — netechnický přehled + **tisknutelný přehled rozsahu** (na jakou oblast dokumentů se asistent vztahuje). Tisk je vždy ve světlém režimu.
- Přepínač **CS/EN**, **dark/light**, patička s **živými hodinami + commit hashem + health** (kontrakt `GET /api/version`).

> Datové komponenty (cesty, rozsah) běží na **vzorových datech** a jsou připravené na napojení na backend (`/api/settings`, `/api/scope`).

## Roadmapa (rozhodnuto)

- **Reconciliation ingest** místo čistého inotify (kvůli síťovým cestám — inotify na SMB/CIFS nefunguje spolehlivě).
- **SQL Server 2019** jako: manifest stavu syncu, audit dotazů/odpovědí (dokladovatelnost), později živý datový zdroj (Dynamics 365 BC) přes text-to-SQL.
- **Hybridní hledání** = Qdrant (sémantika) + SQL Full-Text (přesné termíny: IP, kódy, názvy).
- **Editovatelné cesty v Nastavení**, uložené v SQL, promítané reconciliation skenem; odebrání cesty = smazání z báze; každá změna do auditu.
- **Streaming odpovědí** + volba modelu/GPU pro rychlost.

Detaily a stav viz [docs/HANDOFF.md](docs/HANDOFF.md).

## Bezpečnost

Složky `docs/` a `incoming/` a všechny dokumenty (`*.docx`, `*.pdf`, `*.xlsx`, …) jsou v `.gitignore`, aby nedošlo k úniku firemních dat. Připojovací údaje patří do `.env` (viz `.env.example`), **nikdy ne do Gitu**.

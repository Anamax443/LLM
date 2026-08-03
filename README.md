# AXIMA Znalostní Asistent

Lokální **AI asistent (RAG)** nad interní firemní dokumentací. Odpovídá na dotazy zaměstnanců na základě směrnic, IT postupů, infrastruktury a IP plánu — **veškerá data zůstávají na lokálním serveru, nic se neodesílá do cloudu** (ISO 27001 / NIS2). U každé odpovědi uvádí zdroj a pokud odpověď nezná, řekne to a nevymýšlí si.

> 🇬🇧 English version: [README.en.md](README.en.md)

---

## Co to dělá

Zeptáte se přirozeným jazykem (např. *„jak obnovit server ze zálohy?"*) → asistent najde v interních dokumentech relevantní pasáže, sestaví z nich kontext, nechá lokální jazykový model vygenerovat odpověď a **ukáže, ze kterých dokumentů čerpal**. Přístup je chráněný přihlášením přes **Microsoft Entra ID (SSO)**.

## Architektura

```
Hlídané cesty          ┌──────────────────────────────────────────────────┐
(lokální + \\server)   │  watchdog_service.py  (reconciliation ingest)    │
   │                   │  periodický sken → čte .docx/.pdf → chunkuje →   │
   ▼                   │  embedduje → upsert / maže bloky v Qdrantu       │
smbclient (Kerberos)   └───────────────────┬──────────────────────────────┘
lokální os.walk                            ▼
                              Ollama bge-m3 (1024D)  →  Qdrant (axima_docs)

  Uživatel ─(Entra ID SSO)─┐
                           ▼
  web/index.html ──POST /ask──►  api.py (FastAPI)  ──►  Qdrant (hledání)
  (4 záložky, přihlášení)                          └─►  Ollama mistral-nemo (generování)
                          ◄── odpověď + zdroje (SSE stream) ──
```

- **AI backend:** [Ollama](https://ollama.com) (port 11434) — `bge-m3` (1024D embeddingy) + `qwen2.5:14b` (generování odpovědí, trvale načteno v paměti pomocí `keep_alive: -1` pro okamžitou odezvu).
- **Vektorová DB:** [Qdrant](https://qdrant.tech) (port 6333), kolekce `axima_docs`, 1024D, kosinová vzdálenost.
- **Ingest:** `watchdog_service.py` běží jako periodický **reconciliation sken** hlídaných cest (lokálních i UNC `\\server\share` přes user-space `smbclient` + Kerberos). Porovnává stav se souborem `reconciliation_manifest.json` (mtime/velikost), doindexuje změněné, **smaže bloky u smazaných souborů** i **staré bloky před re-indexem** (žádné míchání verzí). Aktuálně se indexují soubory **`.docx` a `.pdf`**; chunk 1000/200, ke každému bloku se přidává název zdroje. Interval `RECONCILIATION_INTERVAL_SEC` (default 30 s dev / doporučeno 900 s prod).
- **API:** `api.py` (FastAPI, port 8000):
  - `POST /ask` — dotaz, odpověď **streamovaně (SSE)**; *vyžaduje přihlášení*.
  - `GET /api/version` — commit/branch/build pro servisní řádek UI.
  - `GET /config` — model/limit/teplota pro UI; *vyžaduje přihlášení*.
  - `POST /api/verify` — reálné ověření dostupnosti cest (UNC přes user-space `smbclient`, lokální `os.path.isdir`).
  - `GET /api/monitored_paths` / `POST /api/set_monitored_paths` — čtení/uložení hlídaných cest (`monitored_paths.json`).
  - `POST /api/extract` — text z příloh (PDF přes `pypdf`, DOCX přes `python-docx`, textový fallback); *vyžaduje přihlášení*.
  - `GET /api/auth/login` · `/api/auth/callback` · `/api/auth/me` · `/api/auth/logout` — přihlášení přes **Microsoft Entra ID**.
  - Servíruje web UI (`web/`) na kořeni.
  - Při startu kontroluje dostupnost Qdrant a Ollama (health check).
- **CLI:** `ask_ai.py` — dotaz z terminálu.
- **Web UI:** `web/index.html` — homepage se záložkami Asistent / Nastavení / Dokumentace / Manažerský výstup (dle AXIMA UI standardu: dark+light, tisk light, CS+EN, **servisní řádek v hlavičce** — health, model, commit, hodiny, GitHub odkaz). Přihlašovací overlay (SSO). Cesty načítá/ukládá přes backend.

## Soubory

| Soubor | Účel |
|---|---|
| `watchdog_service.py` | Reconciliation ingest: periodický sken hlídaných cest (lokální + UNC/SMB), čtení `.docx`/`.pdf`, chunkování, vektorizace, upsert/mazání v Qdrantu s kontextem zdroje |
| `api.py` | FastAPI backend (`/ask`, `/config`, `/api/version`, `/api/verify`, `/api/extract`, `/api/monitored_paths`, Entra ID SSO), servírování `web/` |
| `ask_ai.py` | CLI klient pro dotazování |
| `flush_qdrant.py` | Servisní util — smaže kolekci `axima_docs` (čistý re-index od nuly) |
| `web/index.html` | Homepage / UI (samostatný soubor, bez frameworku) |
| `axima-web.service` | Vzorová systemd unit pro produkční běh API + web UI |
| `dokumentace.md` | Technická dokumentace (architektura, provoz, známé problémy a řešení) |
| `docs/BUILD.md` | **Výrobní návod — postavení celého systému od nuly** ([EN](docs/BUILD.en.md)) |
| `docs/LINUX_SETUP_GUIDE.md` | Nastavení Linuxu pro user-space SMB (gMSA + Kerberos, keytab) |
| `docs/SPOJENI_FILE_SERVERU.md` | Architektonický návrh propojení Windows File Serveru a Linuxu (User-Space SMB) |
| `docs/HANDOFF.md` | Aktuální stav projektu a přijatá rozhodnutí |
| `docs/OPONENTURA.md` | Obhajovací podklad (rozhodnutí, rizika, NFR, kapacita, DR, TCO) |
| `docs/JAK-FUNGUJE-UCENI.md` | Netechnické vysvětlení „jak model umí naše data" (RAG vs fine-tuning) |
| `requirements.txt` · `.env.example` | Python závislosti a vzor konfigurace |

## Rychlý start

Kompletní postup od čistého serveru je v **[docs/BUILD.md](docs/BUILD.md)**. Ve zkratce:

```bash
# 1) Qdrant (Docker)
docker run -d -p 6333:6333 -v $(pwd)/qdrant_storage:/qdrant/storage qdrant/qdrant

# 2) Ollama + modely
ollama pull bge-m3           # embedding, 1024D
ollama pull qwen2.5:14b      # generování odpovědí (vyžaduje GPU s dostatkem VRAM, např. RTX 5060 Ti)

# 3) Python prostředí
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 4) Konfigurace — přihlášení přes Entra ID je povinné
cp .env.example .env         # doplňte ENTRA_TENANT_ID / CLIENT_ID / CLIENT_SECRET / SESSION_SECRET

# 5) Ingest (reconciliation sken) + API
python3 watchdog_service.py     # v jednom terminálu
python3 api.py                  # ve druhém → http://SERVER:8000
```

> Bez platných `ENTRA_*` údajů API poběží, ale `/ask` a další chráněné endpointy vrátí `401` (uživatel se nepřihlásí).

## Web UI — funkčnost

`web/index.html` servíruje `api.py` na `/` (samostatný soubor, bez frameworku, **AXIMA logo** v hlavičce). Po přihlášení (Entra ID SSO) záložky:

- **Asistent** — **streamovaný chat** s historií a Markdownem (`POST /ask`); k dotazu lze **přiložit soubory nebo vložit screenshot (Ctrl+V)** — obsah se převede na text (`POST /api/extract`: PDF/DOCX/text + **OCR obrázků/screenshotů** přes `pytesseract`, čeština+angličtina) a přidá ke kontextu. Generování lze **zastavit**; při nedostupném backendu ukázkový režim s obecnou chybovou hláškou.
- **Nastavení** — správa **hlídaných cest** (přidat/odebrat, podadresáře, přípony, aktivní) **načítané z backendu** (`GET /api/monitored_paths`) a **ukládané na backend** (`POST /api/set_monitored_paths`), tlačítko **Ověřit dostupnost cest** + **terminál** (reálný check `POST /api/verify` přes user-space SMB; do ověření je STAV „neověřeno", nefabrikuje se), **Stav skenování**, model/teplota/počet bloků a přepínače „zobrazit v hlavičce". *Cesty spravuje operátor bez zásahu IT.*
- **Dokumentace** — plnohodnotná dokumentace **uvnitř aplikace** (boční menu + články: O aplikaci, Jak to funguje, Jak se ptát, Cesty a skenování, Bezpečnost) ve firemním designu, **bez odkazů na git či soubory**.
- **Manažerský výstup** — netechnický přehled + **tisknutelný přehled rozsahu** báze (s **AXIMA logem** v hlavičce tisku). Tisk je vždy ve světlém režimu.
- Přepínač **CS/EN**, **dark/light**; **servisní řádek v hlavičce** (health, **model** 🧠, commit, živé hodiny, **GitHub** ikona) — model a GitHub lze volitelně skrýt v Nastavení. Kontrakt `GET /api/version`.

## Roadmapa (reprioritizováno po oponentuře)

1. **Ověření jádra** — reconciliation cyklus na SMB (mtime/size **+ ACL**, hash jen změněných) + konektivita Linux → SQL19.
2. **Řízení přístupu (MVP, podmínka nasazení)** — Entra ID autentizace **je hotová**; zbývá indexace ACL u dokumentu a filtr výsledků dle identity uživatele. Bez toho RAG zplošťuje NTFS oprávnění = bezpečnostní regrese. **Čerstvost ACL:** sken sleduje i security-descriptor (změna práv nemění mtime), autorizace dle tranzitivního členství uživatele.
3. **Verzování dokumentů** — identita = plná relativní cesta, Qdrant payload index na `source`.
4. **Testovací sada + benchmark modelů** — embedding (`bge-m3` vs multilingual-e5, kvůli češtině) i generativních (vč. kvantizace).
5. **Parsing** — OCR **obrázkových příloh hotovo**; zbývá OCR **skenovaných PDF** a struktura-aware zpracování tabulek (XLSX/PDF).
6. **Hybridní hledání** — Qdrant **dense + sparse** vektory + RRF/rerank (kvůli rychlosti nativně v Qdrantu, ne SQL FTS).
7. **Rychlost** — streaming odpovědí (hotovo), volba modelu/GPU.
8. **Provoz** — monitoring, DR, systemd, audit s maskováním PII, feedback smyčka.
9. **Samostatná fáze:** živá data z Dynamics 365 BC přes text-to-SQL (vlastní rizikový profil).

**SQL Server 2019** slouží jako manifest stavu syncu, audit (s maskováním PII) a později živý datový zdroj — **ne** jako vektorová DB ani search engine. Dnes jsou hlídané cesty v `monitored_paths.json`; odebrání cesty = smazání jejích dokumentů z báze.

Obhajoba rozhodnutí, rizika, NFR, kapacita, DR a TCO: **[docs/OPONENTURA.md](docs/OPONENTURA.md)**. Živý stav: [docs/HANDOFF.md](docs/HANDOFF.md).

## Bezpečnost

Přístup je chráněný přihlášením přes **Microsoft Entra ID (SSO)** — chráněné endpointy (`/ask`, `/config`, `/api/extract`) bez platné session vrací `401`.

Firemní dokumenty (`*.docx`, `*.pdf`, `*.xlsx`, …) jsou v `.gitignore`, aby nedošlo k úniku dat (dokumentace v `docs/` se naopak verzuje). Připojovací údaje a klíče (`ENTRA_*`, `SESSION_SECRET`) patří do `.env` (viz `.env.example`), **nikdy ne do Gitu**. Přístup k síťovým cestám je v uživatelském prostoru (`smbclient` + Kerberos, gMSA), bez root a bez OS mountů — viz [docs/SPOJENI_FILE_SERVERU.md](docs/SPOJENI_FILE_SERVERU.md).

**Guardrails asistenta** jsou v kódu (`SYSTEM_PROMPT` v `api.py`, pole `system`) — bez persony, **odolné vůči prompt injection** (ignorují pokusy „změň roli/pravidla"), odpovídají jen z dodaného kontextu. Mění je jen admin přes git/review, **nikdy uživatel v chatu**.

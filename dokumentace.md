# Lokální RAG Watchdog Service - Technická Dokumentace

## 1. Architektura
Projekt slouží k automatizovanému načítání, vektorizaci a dotazování interních firemních dokumentů (bez odesílání dat do cloudu, připraveno pro ISO27001). Přístup k asistentovi je chráněný přihlášením přes **Microsoft Entra ID (SSO)**.
- **Vstupní bod:** Sledované cesty jsou konfigurovány v UI a načítány z FastAPI (`GET /api/monitored_paths`, uloženo v `monitored_paths.json`). Podporuje lokální složky i UNC cesty (`\\server\share`) přes User-Space SMB s Kerberos autentizací.
- **Ingest (reconciliation sken):** `watchdog_service.py` **není** klasický inotify watcher — je to periodická smyčka (`reconciliation_scan()`, interval `RECONCILIATION_INTERVAL_SEC`). V každém cyklu projde hlídané cesty (lokálně `os.walk`, UNC přes `smbclient.walk` + Kerberos), porovná se souborem `reconciliation_manifest.json` (mtime + velikost) a zpracuje jen nové/změněné. SMB soubory se stahují do `tempfile.TemporaryDirectory` (automatický úklid). Text se rozseká `RecursiveCharacterTextSplitter` (1000/200), ke každému bloku se přidává prefix s názvem zdroje. Před re-indexem se mažou staré bloky daného zdroje a bloky souborů, které z disku zmizely. **Aktuálně se skenují jen soubory `.docx` a `.pdf`** (funkce `extract_text` umí i další textové formáty, ale sken je filtruje na tyto dvě přípony).
- **Přílohy k dotazu:** endpoint `POST /api/extract` převede přiložené soubory na text — PDF přes `pypdf`, DOCX přes `python-docx`, **obrázky/screenshoty přes OCR** (`pytesseract`, jazyky `ces+eng`), textový fallback pro ostatní. OCR má graceful fallback: když na serveru chybí `tesseract-ocr`/jazyková data, vrátí u obrázku hlášku a dotaz nespadne. **OCR skenovaných PDF a struktura-aware zpracování tabulek zůstávají v roadmapě** (viz [OPONENTURA.md](docs/OPONENTURA.md) krok „Parsing").
- **AI Backend:** Databáze Qdrant (port 6333, kolekce `axima_docs`, vektor 1024D, kosinová vzdálenost). Modely běží přes Ollamu (port 11434). Model `bge-m3` pro vektorizaci textu (1024D) a **`qwen2.5:14b`** pro generování odpovědí (temperature 0.6). Model je pro okamžitou odezvu trvale načten do VRAM pomocí `keep_alive: -1`.

### Endpointy API (`api.py`)
| Endpoint | Metoda | Přihlášení | Účel |
|---|---|---|---|
| `/ask` | POST | ano | dotaz, odpověď streamovaně (SSE) |
| `/config` | GET | ano | model/limit/teplota pro UI |
| `/api/extract` | POST | ano | text z příloh (PDF/DOCX/text) |
| `/api/version` | GET | ne | commit/branch/build pro servisní řádek |
| `/api/verify` | POST | ne | ověření dostupnosti cest (UNC přes smbclient) |
| `/api/monitored_paths` · `/api/set_monitored_paths` | GET · POST | ne | čtení/uložení hlídaných cest |
| `/api/auth/login` · `/callback` · `/me` · `/logout` | GET | — | přihlášení přes Microsoft Entra ID |

## 2. Instalace a Provoz
Systém běží uvnitř Python virtual environment (`venv`).
1. Aktivace prostředí: `source /data/llm-demo/watchdog/venv/bin/activate`
2. Spuštění datové pumpy (naslouchání): `python3 watchdog_service.py`
3. Dotazování z terminálu: `python3 ask_ai.py "Znění dotazu"`

## 3. Known Issues & Řešení
- **CORS Chyba 405 (Method Not Allowed):** Původní nastavení `CORSMiddleware` v `api.py` s `allow_origins="*"` a `allow_credentials=True` bylo v rozporu se specifikací, což vedlo k odmítání pre-flight `OPTIONS` požadavků. Opraveno nastavením `allow_credentials=False`.
- **Neúplná podpora textových formátů:** Skript `extract_text` v `watchdog_service.py` a endpoint `api/extract` v `api.py` původně nepodporovaly širokou škálu textových formátů (.txt, .ps1, .html atd.), což vedlo k tichému ignorování obsahu. Rozšířena podpora pro tyto formáty. Nově přidána podpora pro DOCX soubory.
- **Falešná detekce smazaných souborů:** Rozdílné formáty lomítek (zpětná vs. dopředná) v cestách vedly k chybným porovnáním a mazání nově indexovaných souborů z Qdrantu. Vyřešeno normalizací všech cest na dopředná lomítka.
- **Chybné mazání Qdrant bodů:** Kód pro mazání starých vektorů v `index_file` používal zastaralou nebo nesprávnou syntaxi, což způsobovalo validační chyby. Opraveno použitím `qdrant_client.http.models.Filter`.
- **Tiché selhání SMB skenování:** V případě problémů s Kerberos autentizací nebo nedostupností SMB cesty skript tiše ignoroval chyby. Nyní je implementováno agresivní logování a ošetření výjimek.
- **SMB Lock kolize (historické, model `incoming`/`docs`):** Původní watchdog v Linuxu spouštěl zpracování dříve, než Windows přes Sambu dokončily kopírování. Řešilo se oddělením složek `incoming`/`docs`. **Tento model je nahrazen reconciliation skenem** (soubory se čtou přímo z hlídané cesty / stahují do `tempfile.TemporaryDirectory`), složky `incoming`/`docs` už nejsou potřeba.
- **Qdrant API Breaking Change:** Novější verze `qdrant-client` (>1.11.x) trvale odstranily metodu `search`. Je nutné striktně používat `query_points`.
- **Chybná striktní RAG blokáda u příloh:** Původní logika blokovala odpovědi, pokud Qdrant nic nenašel, i když byl přítomen text přílohy. Opraveno tak, aby dotaz pokračoval k LLM, pokud existuje příloha (i bez Qdrant výsledků).
- **Chyba iterace historie v API:** Opraven `AttributeError` při iteraci historie konverzace v `/ask` endpointu, kdy byly Pydantic modely mylně považovány za slovníky. Nyní se k atributům přistupuje přímo (např. `msg.role`).
- **Zpoždění odpovědí (Cold Start):** U velkých modelů trvalo generování první odpovědi přes 10 vteřin kvůli přesunu 9GB dat z disku do GPU (v případě neshody ovladačů NVIDIA po updatu systému asistent padal do CPU módu). Řešení: do API přidán parametr `keep_alive: -1` pro trvalé usazení modelu v paměti a po aktualizacích linuxu je nutné restartovat server.
- **CI/CD Blokáda:** Github Actions / Watchdog padal na příkazu `sudo systemctl restart axima-api` kvůli chybějícímu heslu. Řešením bylo vytvoření souboru `/etc/sudoers.d/aixima_cicd` s pravidlem umožňujícím uživateli `aixima` restart služby bez zadání hesla.

## 4. Verzování a GitHub
Projekt je spravován přes Git. 
**DŮLEŽITÉ BEZPEČNOSTNÍ UPOZORNĚNÍ:** Firemní dokumenty (`*.docx`, `*.pdf`, `*.xlsx`, …) jsou úmyslně ignorovány v `.gitignore`, aby nedošlo k úniku interních firemních dat (ISO27001). Rovněž se **necommituje `.env`** (obsahuje `ENTRA_*`, `SESSION_SECRET`). Adresář `docs/` s dokumentací projektu se naopak verzuje.

## 5. Související dokumentace
- **[README.md](README.md)** / [README.en.md](README.en.md) — přehled projektu.
- **[docs/BUILD.md](docs/BUILD.md)** / [BUILD.en.md](docs/BUILD.en.md) — výrobní návod, postavení od nuly.
- **[docs/HANDOFF.md](docs/HANDOFF.md)** — aktuální stav, přijatá rozhodnutí, známé bugy a další kroky (vč. přechodu na reconciliation ingest, SQL Server 2019 a hybridního hledání).
- **[docs/OPONENTURA.md](docs/OPONENTURA.md)** — obhajovací podklad: rozhodnutí + alternativy, rizika, NFR, kapacitní plán, DR, threat model, TCO a reakce na oponenturu.
- **[docs/JAK-FUNGUJE-UCENI.md](docs/JAK-FUNGUJE-UCENI.md)** / [EN](docs/JAK-FUNGUJE-UCENI.en.md) — netechnické vysvětlení, jak se model „učí" on-premise.
- **[docs/SPOJENI_FILE_SERVERU.md](docs/SPOJENI_FILE_SERVERU.md)** — architektonický návrh propojení Windows File Serveru a Linuxu v uživatelském prostoru (User-Space SMB) s podporou gMSA a Kerbera.
- **[docs/LINUX_SETUP_GUIDE.md](docs/LINUX_SETUP_GUIDE.md)** — manuální kroky na Linux serveru pro user-space SMB (gMSA účet, Kerberos, keytab s právy `400`, obnova lístku přes systemd timer).

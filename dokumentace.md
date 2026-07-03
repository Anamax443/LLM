# Lokální RAG Watchdog Service - Technická Dokumentace

## 1. Architektura
Projekt slouží k automatizovanému načítání, vektorizaci a dotazování interních firemních dokumentů (bez odesílání dat do cloudu, připraveno pro ISO27001).
- **Vstupní bod:** Sledované cesty jsou konfigurovány v UI a načítány z FastAPI (`GET /api/monitored_paths`). Podporuje lokální složky i UNC cesty (`\\server\share`) přes User-Space SMB s Kerberos autentizací.
- **Zpracování:** Soubory (DOCX, XLSX, PDF, TXT, PS1, HTML, a další textové formáty) jsou skrze "Atomic Move" (jen u lokálních) nebo stažením do `tempfile.TemporaryDirectory` (u SMB) přečteny a rozsekány na textové bloky pomocí `RecursiveCharacterTextSplitter`. K textu bloku se automaticky přidává prefix s názvem zdrojového dokumentu pro lepší kontextualizaci.
- **AI Backend:** Databáze Qdrant (port 6333, kolekce `axima_docs`, vektor 768D). Modely běží přes Ollamu (port 11434). Model `nomic-embed-text` pro vektorizaci textu a `llama3.1` (8B) pro generování odpovědí.

## 2. Instalace a Provoz
Systém běží uvnitř Python virtual environment (`venv`).
1. Aktivace prostředí: `source /data/llm-demo/watchdog/venv/bin/activate`
2. Spuštění datové pumpy (naslouchání): `python3 watchdog_service.py`
3. Dotazování z terminálu: `python3 ask_ai.py "Znění dotazu"`

## 3. Known Issues & Řešení
- **CORS Chyba 405 (Method Not Allowed):** Původní nastavení `CORSMiddleware` v `api.py` s `allow_origins="*"` a `allow_credentials=True` bylo v rozporu se specifikací, což vedlo k odmítání pre-flight `OPTIONS` požadavků. Opraveno nastavením `allow_credentials=False`.
- **Neúplná podpora textových formátů:** Skript `extract_text` v `watchdog_service.py` a endpoint `api/extract` v `api.py` původně nepodporovaly širokou škálu textových formátů (.txt, .ps1, .html atd.), což vedlo k tichému ignorování obsahu. Rozšířena podpora pro tyto formáty.
- **Falešná detekce smazaných souborů:** Rozdílné formáty lomítek (zpětná vs. dopředná) v cestách vedly k chybným porovnáním a mazání nově indexovaných souborů z Qdrantu. Vyřešeno normalizací všech cest na dopředná lomítka.
- **Chybné mazání Qdrant bodů:** Kód pro mazání starých vektorů v `index_file` používal zastaralou nebo nesprávnou syntaxi, což způsobovalo validační chyby. Opraveno použitím `qdrant_client.http.models.Filter`.
- **Tiché selhání SMB skenování:** V případě problémů s Kerberos autentizací nebo nedostupností SMB cesty skript tiše ignoroval chyby. Nyní je implementováno agresivní logování a ošetření výjimek.
- **SMB Lock kolize:** Watchdog v Linuxu spouštěl skripty dříve, než Windows přes Sambu dokončily kopírování souboru. Vyřešeno oddělením nahrávací složky `incoming` od pracovního adresáře `docs`.
- **Qdrant API Breaking Change:** Novější verze `qdrant-client` (>1.11.x) trvale odstranily metodu `search`. Je nutné striktně používat `query_points`.

## 4. Verzování a GitHub
Projekt je spravován přes Git. 
**DŮLEŽITÉ BEZPEČNOSTNÍ UPOZORNĚNÍ:** Složky `docs/` a `incoming/` jsou úmyslně ignorovány v `.gitignore`, aby nedošlo k úniku interních firemních dat (ISO27001). Po naklonování repozitáře na nový server je nutné tyto složky vytvořit ručně a nastavit jim správná oprávnění pro Sambu.

## 5. Související dokumentace
- **[README.md](README.md)** / [README.en.md](README.en.md) — přehled projektu.
- **[docs/BUILD.md](docs/BUILD.md)** / [BUILD.en.md](docs/BUILD.en.md) — výrobní návod, postavení od nuly.
- **[docs/HANDOFF.md](docs/HANDOFF.md)** — aktuální stav, přijatá rozhodnutí, známé bugy a další kroky (vč. přechodu na reconciliation ingest, SQL Server 2019 a hybridního hledání).
- **[docs/OPONENTURA.md](docs/OPONENTURA.md)** — obhajovací podklad: rozhodnutí + alternativy, rizika, NFR, kapacitní plán, DR, threat model, TCO a reakce na oponenturu.
- **[docs/JAK-FUNGUJE-UCENI.md](docs/JAK-FUNGUJE-UCENI.md)** / [EN](docs/JAK-FUNGUJE-UCENI.en.md) — netechnické vysvětlení, jak se model „učí" on-premise.
- **[docs/SPOJENI_FILE_SERVERU.md](docs/SPOJENI_FILE_SERVERU.md)** — architektonický návrh propojení Windows File Serveru a Linuxu v uživatelském prostoru (User-Space SMB) s podporou gMSA a Kerbera.

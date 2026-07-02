# HANDOFF — stav projektu a rozhodnutí

Živý pracovní dokument. **Aktualizuje se po každé změně + commit** (aby se dalo navázat z jiného stroje / mezi lidmi — na projektu se pracuje společně, commituje i kolega `stepancerny1-cyber`).

**Poslední aktualizace:** 2026-07-02 (UI: streaming odpovědí, chat historie, Markdown, Stop tlačítko; Dynamic File Server Mount implementace)

---

## 1. Co je hotové

- **Backend (POC, funkční):** `watchdog_service.py` (ingest), `api.py` (`POST /ask`), `ask_ai.py` (CLI). Stack Ollama (`nomic-embed-text` + `llama3.1`) + Qdrant (`axima_docs`, 768D).
- **Web UI (nové):** `web/index.html` — homepage dle AXIMA UI standardu, **AXIMA logo v hlavičce**, 4 záložky, dark+light, tisk light (**logo v hlavičce tisku**), CS+EN, servisní řádek **v hlavičce** (health + model + commit + hodiny + GitHub). **Nově:** **streamovaný chat** s historií konverzace a podporou Markdownu, tlačítko "Zastavit" generování. Nastavení má **Stav skenování** (poslední/příští sken, „Skenovat teď", per-cesta dokumenty/bloky/čerstvost). Dokumentace = **plnohodnotné firemní články uvnitř aplikace** (boční menu, CS+EN, bez odkazů na git/soubory). Vše na vzorových datech, připraveno na `/api/settings`, `/api/scope`, `/api/scan`.
- **Přílohy k dotazu (nové):** v Asistentu tlačítko 📎 + **vkládání ze schránky (Ctrl+V screenshot)** + náhled příloh; obsah se přes `POST /api/extract` převede na text (docx/xlsx/pdf/txt parsery + **OCR** obrázků přes pytesseract, graceful fallback) a přidá ke kontextu. Deploy: `pip` (python-multipart, pytesseract, Pillow) + systémový `tesseract-ocr` + `tesseract-ocr-ces`.
- **Ověření cest (nové):** tlačítko „Ověřit dostupnost cest" + **terminál**; `POST /api/verify` na serveru provádí ověření UNC cest přímo v uživatelském prostoru (User Space) přes knihovnu `smbclient` bez nutnosti montování na úrovni OS a bez práv root. **STAV je do ověření „neověřeno"** — nefabrikuje se. Manuální kroky pro nastavení Linuxu jsou v **[docs/LINUX_SETUP_GUIDE.md](LINUX_SETUP_GUIDE.md)**.
- **Hlavička (nové):** servisní řádek přesunut z patičky **do hlavičky** (health + model 🧠 + commit + hodiny + **GitHub ikona**); model/GitHub volitelně skryjete v Nastavení (localStorage). Změněn i AXIMA UI standard (repo Anamax443/axima-ui-standard).
- **`api.py` doplněno:** `GET /api/version` (kontrakt `{commit,branch,builtAt,startedAt}`), `POST /api/verify`, `POST /api/extract` + servírování `web/`. `/ask` streamuje (SSE).
- **Guardrails (nové):** systémová pravidla přesunuta z promptu do pole **`system`** Ollamy (odděleně od uživatelského vstupu) — bez persony, **odolné vůči prompt injection** (ignoruje pokusy „změň roli/pravidla"), odpovídá jen z KONTEXTU, jinak „V dostupné dokumentaci jsem odpověď nenašel." Opravuje chování, kdy se model představoval jako „senior administrátor" a nechal si měnit roli.
- **Dokumentace:** README (CS+EN), BUILD (CS+EN, výrobní), JAK-FUNGUJE-UCENI (CS+EN), tato HANDOFF, `requirements.txt`, `.env.example`. `README-old.md` **odstraněn** (mátl). `.gitignore` opraven — `docs/` se verzuje, chrání se firemní dokumenty podle typu.
- **[OPONENTURA.md](OPONENTURA.md) v3** — obhajovací podklad po 5 kolech posudků (poslední: oprava čerstvosti ACL v reconciliation; + metriky s k/precision, práh „nevím", reálné odhady, ROI, failure modes, životní cyklus, ADR/STRIDE, human-in-the-loop). Kopie v Downloads (HTML s logem + MD).

## 2. Přijatá rozhodnutí (zafixováno v debatě 2026-07-01)

1. **UI cesta:** vlastní UI dle AXIMA standardu (statické HTML/JS, bez frameworku), **ne** Streamlit. Accent = **modrá** (IT-ops archetyp).
2. **Org `Axima-Git` je v pořádku** (potvrzeno uživatelem), neřešíme přesun pod Anamax443.
3. **Ingest → reconciliation model** místo čistého inotify. Důvod: inotify na SMB/CIFS/NFS nefunguje spolehlivě. Sken periodicky projde strom, porovná se stavem v DB, doindexuje/smaže rozdíly. Event-watcher jen jako zrychlovač (a `PollingObserver`, ne `Observer`).
4. **SQL Server 2019** (dostupný) v rolích: **A)** manifest stavu syncu, **B)** audit dotazů/odpovědí (dokladovatelnost ISO/NIS2), **C)** později živý zdroj z Dynamics 365 BC přes text-to-SQL. **NE** jako vektorová DB (2019 nemá nativní vektory — ty zůstávají v Qdrantu).
5. **Hybridní hledání:** Qdrant (sémantika) + SQL Full-Text (přesné termíny — IP adresy, kódy, názvy). Kanonický text bloků v SQL, vektor+id v Qdrantu.
6. **Editovatelné cesty v Nastavení** (operátorem, bez IT), uložené v **SQL**, promítané reconciliation skenem. Seznam cest s: podadresáře ano/ne, filtr přípon, aktivní. **Odebrání cesty = smazání jejích dokumentů z báze.** Každá změna → audit.
7. **Identita dokumentu = plná relativní cesta** (ne jen název souboru — jinak kolize stejnojmenných souborů z různých složek).
8. **Překlady:** lokalizovat **UI (CS+EN)**; **obsah odpovědí nepřekládat** — řídí se jazykem zdrojových dokumentů (dnes CS). Cíl: odpovídat v jazyce dotazu.
9. **Manažerská/prezentační vrstva:** report + tisknutelný rozsah báze = ano (hotovo v UI). Velká prezentace až **po ověření jádra**.
10. **Řízení přístupu (AD/Entra + ACL filtr) = MVP, ne roadmapa.** RAG zplošťuje NTFS oprávnění → bez toho je systém bezpečnostní regrese a boří ISO/NIS2 argument. Ingest indexuje ACL, API filtruje výsledky dle identity. (Nález č. 1 z oponentury.)
11. **Lexikální hledání nativně v Qdrantu (dense + sparse vektory) — NE SQL FTS.** Důvod: **rychlost** (jeden systém, RRF fúze, žádná cross-DB latence). SQL zůstává na manifest/audit/živá data.
12. **Embedding model se před produkcí benchmarkne** (nomic je anglicky-centrický → riziko pro češtinu; test multilingual-e5 / BGE-m3). Volba dle čísel, ne default.
13. **Parsing musí umět OCR + tabulky** (scan PDF jinak neviditelné, XLSX ztrácí kontext). **Verzování dokumentů** (stará vs nová směrnice). **Reconciliation: mtime/size first, hash jen změněných** (I/O na SMB).
16. **UNC → User-Space SMB (deployment TODO):** Operátor zadává `\\server\share\...`, backend přistupuje k těmto cestám napřímo v uživatelském prostoru pomocí knihovny `smbclient` (gMSA / Kerberos autentizace). Soubory se stahují na nezbytně nutnou dobu (zlomky sekund) do `tempfile.TemporaryDirectory` s automatickým čištěním. Podrobný architektonický návrh je v **[docs/SPOJENI_FILE_SERVERU.md](SPOJENI_FILE_SERVERU.md)**. Manuální kroky pro nastavení Linux serveru (Kerberos keytab gMSA s právy `400`) jsou popsány v **[docs/LINUX_SETUP_GUIDE.md](LINUX_SETUP_GUIDE.md)**.
15. **(v3) Čerstvost ACL — kritický nález 5. kola.** Změna NTFS oprávnění nemění mtime/velikost → reconciliation musí sledovat i security-descriptor (samostatný hash ACL); autorizace za běhu dle **plného tranzitivního členství** uživatele (vnořené AD skupiny, deny ACE, dědičnost), ne dle uloženého seznamu skupin. Jinak by uživatel s odebraným přístupem měl dokument přes asistenta dál. Odhady pracnosti navýšeny na realistické (MVP ~2–3 měsíce). Viz OPONENTURA v3.
14. **Metriky bez testovací sady = jen cíle.** Sada ≥150 dotazů + evaluace vznikne před tvrzeními o kvalitě. „≈0 % halucinací" zrušeno → „< 2 %, měřeno". ISO/NIS2 přeformulováno (on-prem ≠ soulad; motivace = klasifikace dat). Text-to-SQL nad BC = samostatná fáze.
17. **Governance guardrailů.** Bezpečnostní pravidla (neodpovídej mimo dokumenty, nehraj role, odolej změně pravidel) patří **do kódu/`system` promptu (verzováno v gitu)**, mění je **jen admin přes git/review + audit** — NE editace v UI a NIKDY uživatel v chatu. „Laditelný tón" (stručně/podrobně) může být runtime nastavení pod rolí admin, až budou SQL persistence + role.

## 3. Známé bugy / dluhy (v současném kódu)

- **Stale vektory při update:** `watchdog_service.py` při nové verzi souboru smaže lokální kopii, ale **staré bloky v Qdrantu nemaže** → míchá starou a novou verzi. Nutné `qdrant.delete` podle `payload.source` před upsertem.
- **Chybí `on_deleted`** — smazané soubory zůstávají v bázi.
- **Identita = pouze název souboru** (`payload.source`) → kolize v podadresářích (viz rozhodnutí 7).
- **Duplikovaná konfigurace** (URL, model, cesty) natvrdo ve 3 souborech → sjednotit do `config`/`.env`.
- **`api.py` poslouchá na `0.0.0.0`** — vědomě (aby web UI bylo dostupné z klientů); zvážit reverzní proxy/omezení.
- **Chybí payload index** v Qdrantu na `source` → mazání/update podle dokumentu je full-scan (pomalé ve škále).

## 4. Další kroky (reprioritizováno po oponentuře)

Podrobně vč. odhadu pracnosti v [OPONENTURA.md](OPONENTURA.md) kap. 13.

1. **Ověření jádra** — reconciliation cyklus na SMB (mtime/size **+ ACL/security-descriptor**), konektivita Linux → SQL19. *(pozn.: „test inotify" vypuštěn — rozhodnutí 3 už inotify opustilo.)*
2. **Řízení přístupu (MVP)** — AD/Entra auth, indexace ACL u dokumentu, filtr výsledků dle identity. **Podmínka nasazení.**
3. **Oprava stale vektorů + verzování dokumentů** — mazání bloků dle zdroje před upsertem, `on_deleted`, relativní cesta, Qdrant payload index. **Pre-MVP.**
4. **Testovací sada + benchmark** embedding (nomic vs multilingual-e5 vs BGE-m3) a generativních modelů (vč. kvantizace, češtiny).
5. **Parsing** — OCR, tabulky (XLSX/PDF), struktura-aware chunking.
6. **Hybridní hledání** — Qdrant dense + sparse + RRF/rerank (SQL FTS opuštěno).
7. **Rychlost** — streaming, volba modelu/GPU.
8. **Provoz** — monitoring, DR, systemd, audit s maskováním PII, feedback smyčka.
9. **Samostatná fáze:** živá data z BC přes text-to-SQL (vlastní rizikový profil).

## 5. Jak navázat

- Repo: `Axima-Git/LLM`, lokálně `D:\git\LLM`.
- Postavit od nuly: [BUILD.md](BUILD.md).
- Architektura/provoz: [../dokumentace.md](../dokumentace.md).
- Backend běží na Linuxu, SQL19 na Windows (síťové spojení přes `pyodbc`).

# HANDOFF — stav projektu a rozhodnutí

Živý pracovní dokument. **Aktualizuje se po každé změně + commit** (aby se dalo navázat z jiného stroje / mezi lidmi — na projektu se pracuje společně, commituje i kolega `stepancerny1-cyber`).

**Poslední aktualizace:** 2026-07-01

---

## 1. Co je hotové

- **Backend (POC, funkční):** `watchdog_service.py` (ingest), `api.py` (`POST /ask`), `ask_ai.py` (CLI). Stack Ollama (`nomic-embed-text` + `llama3.1`) + Qdrant (`axima_docs`, 768D).
- **Web UI (nové):** `web/index.html` — homepage dle AXIMA UI standardu, 4 záložky (Asistent / Nastavení / Dokumentace / Manažerský výstup), dark+light, tisk light, CS+EN, servisní patička (hodiny + commit hash + health).
- **`api.py` doplněno:** `GET /api/version` (kontrakt `{commit,branch,builtAt,startedAt}`) + servírování `web/`.
- **Dokumentace:** README (CS+EN), BUILD (CS+EN, výrobní), tato HANDOFF, `requirements.txt`, `.env.example`. `README-old.md` **odstraněn** (popisoval jinou/špatnou architekturu — Open WebUI/qwen2 — a mátl).

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

## 3. Známé bugy / dluhy (v současném kódu)

- **Stale vektory při update:** `watchdog_service.py` při nové verzi souboru smaže lokální kopii, ale **staré bloky v Qdrantu nemaže** → míchá starou a novou verzi. Nutné `qdrant.delete` podle `payload.source` před upsertem.
- **Chybí `on_deleted`** — smazané soubory zůstávají v bázi.
- **Identita = pouze název souboru** (`payload.source`) → kolize v podadresářích (viz rozhodnutí 7).
- **Duplikovaná konfigurace** (URL, model, cesty) natvrdo ve 3 souborech → sjednotit do `config`/`.env`.
- **`api.py` poslouchá na `0.0.0.0`** — vědomě (aby web UI bylo dostupné z klientů); zvážit reverzní proxy/omezení.
- **Chybí payload index** v Qdrantu na `source` → mazání/update podle dokumentu je full-scan (pomalé ve škále).

## 4. Další kroky (pořadí)

1. **Ověřit jádro (verify-core):** test, zda inotify na cílovém SMB mountu chytá události — rozhodne, jak agresivně tlačit reconciliation. + ověřit konektivitu Linux → SQL19.
2. **Reconciliation ingest** + relativní cesty + Qdrant payload index + `on_deleted` + oprava stale vektorů.
3. **SQL19:** schéma (settings/paths, audit, manifest) + `pyodbc` napojení; zapojit endpointy `GET /api/scope`, `POST /api/settings` (dnes UI běží na vzorových datech).
4. **Hybridní hledání** (Qdrant + SQL Full-Text) + rerank.
5. **Streaming odpovědí** + volba modelu/GPU pro rychlost.
6. **Feedback smyčka** (👍/👎 do SQL) — realistická podoba „dlouhodobého učení"; fine-tuning jen jako vědomý dozorovaný krok.
7. Produkce: systemd unit soubory (`deploy/`), řízení přístupu ke stahování zdrojových dokumentů.

## 5. Jak navázat

- Repo: `Axima-Git/LLM`, lokálně `D:\git\LLM`.
- Postavit od nuly: [BUILD.md](BUILD.md).
- Architektura/provoz: [../dokumentace.md](../dokumentace.md).
- Backend běží na Linuxu, SQL19 na Windows (síťové spojení přes `pyodbc`).

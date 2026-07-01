# Podklad pro oponenturu — AXIMA Znalostní Asistent

**Projekt:** Lokální AI asistent (RAG) nad interní firemní dokumentací
**Repozitář:** Axima-Git/LLM · **Stav:** funkční prototyp + UI, roadmapa do produkce
**Verze podkladu:** 3.0 (2026-07-01) — po pátém kole nezávislých oponentur

> Účel: poskytnout hodnoticí komisi úplný technický i manažerský obraz projektu, obhájit rozhodnutí, otevřeně pojmenovat rizika a omezení a předjímat kritické otázky. Verze 2.0 reaguje na nezávislé posudky — opravuje přehnaná tvrzení, přeřazuje priority a doplňuje dosud chybějící kapitoly. Sekce, u kterých s posudky nesouhlasím, jsou uvedeny v kap. 14.

---

## 0. Co se změnilo ve verzích

**Verze 3.0 (5. kolo posudků):**
- **Oprava kritického nálezu:** změna NTFS ACL nemění mtime/velikost → reconciliation musí sledovat i ACL/security-descriptor; autorizace za běhu dle tranzitivního členství (4.4, 5.1).
- Retrieval metrika s explicitním **k** + precision@k/NDCG (2.3); **práh pro „nevím"** a ochrana dat u LLM-judge (8).
- **Reálné odhady pracnosti** (dřívější byly optimistické) + Definice hotového (13); **ROI** (10.1).
- Doplněno: failure modes + životní cyklus dat (9.5–9.6), zamítnuté alternativy / proč FastAPI (4.10), human-in-the-loop pro důvěrné (5.5); opatrnější závěr.

**Verze 2.0 (4 nezávislé posudky):** Hlavní změny:
- **Řízení přístupu** přesunuto z „roadmapa krok 7" na **MVP (krok 2)** — bez něj systém zavádí bezpečnostní regresi (viz 5.1).
- Odstraněn nesplnitelný cíl „≈0 % halucinací"; zavedena měřitelná metrika a evaluační metodika (2.3, 8).
- Přeformulován vztah k ISO/NIS2: on-premise **není** sám o sobě soulad (5).
- Doplněny chybějící kapitoly: **NFR, kapacitní plán, výkon/benchmarky, provoz (monitoring, DR, CI/CD, verzování embeddingů), TCO, threat model**.
- Přehodnocena architektura hybridního hledání (Qdrant-nativní sparse vektory jako doporučený směr, 4.5).
- Doplněno **verzování dokumentů**, ošetření **stale vektorů** jako pre-MVP priorita, parsing tabulek a OCR (4.9).
- Přidána sekce **„Reakce na oponenturu"** (14) — co přijímáme a co odmítáme.

---

## 1. Manažerské shrnutí

Zaměstnanci tráví čas hledáním informací v roztříštěné firemní dokumentaci (směrnice, IT postupy, infrastruktura, IP plán) na síťových discích. Řešení je **lokální AI asistent (RAG)**, který na dotaz v přirozeném jazyce najde relevantní pasáže v interních dokumentech a vygeneruje odpověď **s citací zdroje**.

Data i modely běží na firemním serveru. Motivací **není** to, že by cloud byl zakázán (Azure OpenAI má EU rezidenci i certifikace), ale **firemní klasifikace dat** — dokumenty tříd „interní" a „důvěrné" (infrastruktura, IP plán) nemají opouštět firemní perimetr. Řešení stojí na open-source komponentách a využívá již vlastněný SQL Server 2019.

**Upřímné ohraničení:** aktuální stav je prototyp, který ověřil koncept. Do produkce vede prioritizovaná roadmapa, jejíž první dva kroky (ověření jádra, řízení přístupu) jsou podmínkou jakéhokoli ostrého nasazení.

---

## 2. Zadání a cíle

### 2.1 Problém
Znalosti roztříštěné napříč složkami, formáty a lidmi; hledání pomalé a závislé na jednotlivcích; odchod znalého člověka = ztráta know-how.

### 2.2 Cílový stav
Model **pracuje s našimi soubory a informacemi v nich** (přes RAG — dokumenty jako kontext, s citací), báze je automaticky udržované zrcadlo dokumentů, s výhledem na živá data (Dynamics 365 BC) jako samostatnou fázi.

### 2.3 Měřitelná kritéria úspěchu (revidováno)
| Kritérium | Cíl | Měření |
|---|---|---|
| Retrieval — správný zdroj v **top-k** (k = počet chunků reálně předaných modelu, ~3–5) | ≥ 85 % | testovací sada ≥ 150 dotazů, ground truth |
| Přesnost retrievalu — **precision@k / NDCG@k** | sledovat | tatáž sada — chrání před zavádějícími zdroji |
| Kvalita odpovědi (věcně správná) | ≥ 80 % | ruční hodnocení odborníkem + LLM-as-judge |
| Míra halucinace | **< 2 %** (ne nula — viz 14) | anotace na testovací sadě |
| Doba do první části odpovědi | < 3 s (streaming, GPU) | měření na cílovém HW |
| Aktuálnost báze | ≤ 15 min od změny | telemetrie skenu |

> **Zásadní podmínka:** testovací sada zatím **neexistuje** a musí vzniknout **před** vyhodnocováním kvality (kap. 8). Do té doby jsou čísla cíle, ne tvrzení.

---

## 3. Architektura řešení

```
Síťové cesty (\\fileserver\...)                Uživatel (autentizovaný)
        │  (reconciliation: mtime/size → hash jen změněných)
        ▼                                          │ dotaz + identita
  Ingest (watchdog_service)                        ▼
  parsing (OCR, tabulky) → chunk         Web UI / CLI ── POST /ask ──► API (FastAPI)
  → embedding (Ollama)                                                   │
  + ACL dokumentu                                    ┌───────────────────┤
        ▼                                            ▼   filtr dle identity/ACL
     Qdrant  ◄── hybridní hledání (RRF/rerank) ──► Qdrant (dense + sparse vektory)
  (dense 768D + sparse)                                    │
                                                           ▼
  SQL Server 2019                                  Ollama (LLM) → odpověď + zdroje
  (manifest, audit s maskováním; živá data BC = fáze 2)
```

**Komponenty (open-source, lokálně):** Ollama (embedding + generování), Qdrant (vektory dense + sparse), FastAPI (API + UI), SQL Server 2019 (stav, audit, později živá data — již vlastněno).

---

## 4. Klíčová rozhodnutí a jejich obhajoba

### 4.1 On-premise vs cloud
**Rozhodnutí:** lokální. **Důvod:** firemní klasifikace dat (perimetr), náklady bez per-seat, **nízký (ne nulový) vendor lock-in** — závislost na Ollamě/Qdrantu/formátu embeddingů existuje, ale komponenty jsou vyměnitelné a formáty otevřené. **Kompromis:** vlastní provoz; kvalita open modelu < špičkové cloudové (kap. 12).

### 4.2 RAG vs fine-tuning
**Rozhodnutí:** RAG. **Důvod:** data se mění denně (RAG přeindexuje, fine-tuning by trénoval znovu), RAG **cituje zdroj** (audit), fine-tuning na neověřených datech degraduje. „Naučit model na našich datech" = dát mu je jako kontext, ne přepsat váhy. „Dlouhodobé učení" = aktuálnost báze + feedback; fine-tuning jen jako vědomý dozorovaný krok, samostatný projekt.

### 4.3 Qdrant vs pgvector vs vektory v SQL 2019
**Rozhodnutí:** Qdrant. **Důvod:** SQL Server 2019 **nemá nativní vektory** (až 2025); Qdrant je specializovaný a snadno nasaditelný. SQL19 slouží tomu, v čem je silný (relace, audit, manifest).

### 4.4 Ingest: reconciliation
**Rozhodnutí:** reconciliation sken (ne inotify). **Důvod:** inotify na SMB/CIFS nespolehlivý; sken je samoopravný, zvládá podadresáře a mazání. **Optimalizace (nově):** cyklus se **primárně opírá o `LastWriteTime` + velikost**; hash počítá **jen u změněných** souborů — jinak by hashování tisíců souborů přes SMB každých 15 min zahltilo síť i diskové pole. (Pozn.: dřívější formulace „testovat inotify" byla vnitřně rozporná a je odstraněna — krok 1 roadmapy ověřuje reconciliation cyklus a konektivitu, ne inotify.)

> **Pozor — ACL vs mtime/size (nález 5. kola):** změna NTFS oprávnění **nemění mtime ani velikost** souboru → mtime/size sken by ji nezachytil a v Qdrantu by zůstala **stará ACL** (uživatel s odebraným přístupem by ho přes asistenta stále měl). Proto reconciliation sleduje **i security-descriptor / ACL** (samostatný hash oprávnění, nezávisle na obsahu). A protože seznam „skupin s přístupem" neunese vnořené AD skupiny, deny ACE ani dědičnost, autorizace se dělá **za běhu proti plnému tranzitivnímu členství uživatele** (s hlídáním čerstvosti cache), ne jen dle uloženého seznamu skupin.

### 4.5 Hybridní hledání (přehodnoceno)
**Rozhodnutí:** dense + lexikální, **doporučeně nativně v Qdrantu** (dense + sparse vektory, podpora od 1.11), s fúzí **RRF** a případně cross-encoder rerankerem na top-k. **Důvod:** embeddingy jsou slabé na přesné tokeny (IP adresy, kódy) — lexikální větev je nutná; ale fúzovat přes dvě různé DB (Qdrant API + T-SQL) je latentně neohrabané. SQL Full-Text zůstává **záložní variantou** — rozhodnutí Qdrant-sparse vs SQL-FTS padne **po benchmarku** na české sadě. **Korekce tvrzení:** neplatí „poráží každou metodu samostatně"; správně „očekáváme vyšší přesnost, ověřenou měřením" — naivní fúze bez RRF/rerankeru může i degradovat.

### 4.6 Identita dokumentu = plná relativní cesta
Nutné kvůli kolizi stejnojmenných souborů v podadresářích a pro korektní update/mazání.

### 4.7 Vlastní UI dle AXIMA standardu
Soulad s firemním UI standardem, plná kontrola nad výstupy a řízením přístupu ke stahování; Streamlit/Open WebUI nesplňují.

### 4.8 SQL Server 2019 — role
**A** manifest syncu, **B** audit (s maskováním PII — viz 5.2), **C** živá data z BC přes text-to-SQL **jako samostatná fáze s vlastním rizikovým profilem** (viz 12), ne odrážka.

### 4.9 Embedding model a parsing dokumentů (nově doplněno)
- **Embedding model:** dnešní `nomic-embed-text` je anglicky-centrický → **riziko pro sémantické hledání v češtině**. Volba není obhájena měřením. Před produkcí **benchmarknout multilingvální modely** (`multilingual-e5-large`, `BGE-m3`) na české testovací sadě a rozhodnout podle čísel. (Změna embedding modelu = **re-embedding celého korpusu** — viz provoz 9.4.)
- **Parsing:** naivní „čtení → chunk" je pro naše dokumenty nedostatečné. **XLSX** (IP plán) rozsekaný na plochý text ztrácí vazbu řádek/sloupec; **scanned PDF** bez OCR jsou pro systém neviditelné; **tabulky v PDF** se rozpadnou. Nutné **struktura-aware parsing (OCR, tabulky)** — determinuje přesnost víc než volba LLM.
- **Verzování dokumentů:** dedup podle hashe nechytí *verze* téže směrnice → stará i nová se naindexují a asistent může citovat neplatnou. Nutné evidovat verzi (cesta + hash + časová značka) a preferovat poslední; při konfliktu obsahu to signalizovat.

### 4.10 Zamítnuté alternativy (stručné ADR) a „proč FastAPI"
- **Vektorová DB:** Qdrant zvolen před **Milvus/Weaviate** (těžší provoz), **pgvector** (další DB server navíc) a **Elasticsearch** (silný na lexiku, slabší na čistou vektorovou škálu + další stack). Rozhodnutí = specializace + snadné nasazení.
- **API — FastAPI:** async, automatické OpenAPI, Python ekosystém (sdílí jazyk s ingestem/embeddingem), triviální nasazení; alternativy (Flask sync, Node) bez přínosu.
- Threat model (5.3) vychází z metodiky **STRIDE**; plná matice alternativ je vedena mimo tento podklad.

---

## 5. Bezpečnost a soulad (ISO 27001 / NIS2 / GDPR)

> On-premise **není** sám o sobě soulad. ISO/NIS2 vyžadují procesy, řízení přístupu, řízení rizik, klasifikaci, logování a obnovu. Následující opatření k tomu směřují; certifikaci nenahrazují.

### 5.1 Řízení přístupu — kritická podmínka (nález č. 1)
RAG **zplošťuje NTFS oprávnění**: naindexováním dokumentů do Qdrantu bez autentizace by kdokoli s přístupem na endpoint získal obsah *libovolného* dokumentu — i toho, na který na disku nemá práva. To je **regrese** oproti dnešnímu stavu a v přímém rozporu s principem minimálních oprávnění (ISO Annex A.5.15, A.8.3) i s hlavním argumentem projektu.

**Řešení (do MVP, krok 2 roadmapy):**
- Autentizace přes **Active Directory / Microsoft Entra ID** (SSO), krátce platné tokeny.
- Ingest indexuje u každého dokumentu i jeho **ACL** (skupiny s přístupem).
- API **filtruje výsledky Qdrantu podle identity a členství uživatele** — vrátí jen to, na co má práva.
- Role: `viewer` / `operator` (správa cest) / `admin`.

**Čerstvost oprávnění = bezpečnost, ne výkon:** ACL se přeindexovává i při změně práv (ne jen obsahu — viz 4.4) a rozhodnutí padá **za běhu** dle tranzitivního členství uživatele. Zastaralá ACL cache = bezpečnostní chyba, ne jen nekonzistence.

### 5.2 Audit bez vzniku „shadow data store"
Audit (kdo, kdy, dotaz, odpověď, zdroje) je nutný pro dohledatelnost. Riziko: dotaz může obsahovat osobní údaj → vzniká nové úložiště citlivých dat. **Opatření:** maskování/detekce PII (rodná čísla, e-maily) před zápisem, **retenční politika** a řízený přístup k auditu, výmaz z auditu jako součást GDPR procesu.

### 5.3 Threat model (nově)
| Hrozba | Opatření |
|---|---|
| **Prompt injection** k exfiltraci cizích dokumentů | filtr dle ACL (5.1) — model nikdy nedostane do kontextu dokument mimo oprávnění uživatele |
| **Data poisoning** (podvržený dokument v hlídané cestě) | řízení, kdo smí do hlídaných cest zapisovat; audit změn cest |
| **Únik přes stahování zdroje** | verifikace oprávnění u každého stažení + log každého přístupu k dokumentu |
| **Kompromitace audit DB** | maskování PII, retence, oddělený přístup |

### 5.4 GDPR
Data lokálně; právo na výmaz = smazání dokumentu → reconciliation odstraní vektory i záznamy **i z auditu** (5.2).

### 5.5 Citlivé dotazy a odpovědnost (human-in-the-loop)
- U dokumentů třídy **důvěrné** (IP plán, infrastruktura): notifikace správci pro audit a/nebo upozornění „důvěrné — ověřte s nadřízeným".
- „Odpovědnost na uživateli" (viz 15) **nestačí jako věta v UI** — patří do **podmínek použití** (právní review) a je nutné **logovat potvrzení**, že uživatel upozornění viděl.

---

## 6. Nefunkční požadavky (NFR)

| Kategorie | Požadavek |
|---|---|
| Výkon | odezva < 3 s do první části odpovědi (streaming, GPU); rozpočet zahrnuje embed dotazu + hledání + RRF + rerank + prefill → **rerank proto podmíněný** |
| Dostupnost | cíl 99 % v pracovní době; degradace do „ukázkového režimu" při výpadku. *Napětí: jeden server + bus factor 1 vs 99 % — přiznáno, mitigace HA/zaškolení na roadmapě.* |
| Škálovatelnost | 1 000 → 100 000 dokumentů bez změny architektury |
| Bezpečnost | autentizace, autorizace dle ACL, audit, maskování PII |
| Provozovatelnost | přidání/odebrání cesty operátorem bez IT; monitoring; automatický restart |
| Přenositelnost | postavení od nuly dle `docs/BUILD.md` |
| Auditovatelnost | dohledatelnost odpovědí a přístupů |

---

## 7. Kapacitní plán (odhad, k ověření měřením)

| Objem | Chunků (~10/dok) | Vektory (768D, ~3 KB) | Poznámka |
|---|---|---|---|
| 1 000 dok | ~10 000 | ~30 MB | triviální |
| 10 000 dok | ~100 000 | ~300 MB | pohodlně v RAM |
| 100 000 dok | ~1 000 000 | ~3 GB | stále zvládnutelné na jednom serveru |

Vektorová databáze **není** úzké hrdlo. Úzké hrdlo je **generování na GPU** (viz 8, 10). Payload (text bloků) + SQL manifest/audit řádově v jednotkách GB. Doporučení: **Qdrant payload index na `source`** pro efektivní update/mazání ve škále. (Pozn.: při volbě 1024D modelu — e5-large/BGE-m3 — vzroste objem vektorů o ~⅓; stále jednotky GB.)

---

## 8. Výkon, benchmarky a evaluační metodika

**Metodika (musí vzniknout před produkcí):**
1. **Testovací sada** ≥ 150 dotazů napříč doménami (IT postupy, směrnice, infrastruktura, zálohy), s anotovanou správnou odpovědí a správným zdrojem.
2. **Metriky:** retrieval (správný zdroj v top-k), věcná správnost (ruční + LLM-as-judge), míra halucinace, latence.
3. **Srovnání modelů:** min. 3 embedding modely (nomic vs multilingual-e5 vs BGE-m3) a 2–3 generativní (llama3.1 8B vs Qwen2.5 vs Mistral), včetně **kvantizace 4-bit** (rychlost vs kvalita).
4. **Publikace výsledků** jako součást dokumentace + ukázky, kde model selhává (řízení očekávání uživatelů zvyklých na ChatGPT).
5. **Spouštěč „nevím" (grounding gate):** když jsou všechna top-k skóre pod prahem, model negeneruje a odpoví „na tohle nemám podklad". Práh je parametr laděný na testovací sadě — bez něj „nevím" prakticky nenastane a halucinace se drží hůř.
6. **LLM-as-judge s ochranou dat:** soudce doplnit **ruční kontrolou odborníka na ~20 % vzorku** (kalibrace shody; LLM má sklon nadhodnotit vlastní styl). Pokud judge = cloudový model, **evaluační sada nesmí obsahovat důvěrná data** — jinak porušuje princip lokálnosti; jinak judge on-prem.

> Proč 150 dotazů: kompromis mezi pracností ruční anotace a statistickou vypovídací hodnotou pro pilot.

**Výkonové cíle k doložení:** latence retrievalu (Qdrant) v ms, propustnost generování (tok/s) na cílové GPU, doba kompletní reindexace korpusu.

---

## 9. Provoz (nově)

### 9.1 Monitoring
Health endpoint (běží), metriky latence/chybovosti/čerstvosti báze, alerting na nedostupnost komponent a na zastaralý sken.

### 9.2 Disaster Recovery
- **RPO:** noční snapshot Qdrantu + záloha SQL dle firemní politiky (cíl ≤ 24 h).
- **RTO:** cíl ≤ 4 h.
- **Silná stránka:** znalostní báze je **plně rekonstruovatelná z file-shares** re-ingestem — dokumenty jsou zdroj pravdy, ztráta Qdrantu neznamená ztrátu dat.

### 9.3 CI/CD a nasazení
systemd služby (auto-start/restart), verzované nasazení, `GET /api/version` s commit hashem (živá kontrola verze v patičce UI).

### 9.4 Verzování embeddingů a upgrade modelu
Změna embedding modelu nebo dimenze = **re-embedding celého korpusu** → plánovaná provozní událost (paralelní kolekce, přepnutí po ověření, rollback ponecháním staré kolekce). Verze embedding modelu se eviduje u kolekce. **Řádový odhad:** re-embedding ~100k dokumentů na jedné L4 = **hodiny až ~1 den** GPU dávky → switchover plánovat mimo špičku.

### 9.5 Chování při výpadku (failure modes)
| Výpadek | Co uvidí uživatel |
|---|---|
| Ollama/GPU nedostupné | jasná chyba „asistent dočasně nedostupný", ne prázdno |
| Qdrant nedostupný | „nelze prohledat bázi" + health červená |
| SQL nedostupný | asistent odpovídá, ale bez auditu/nastavení (degradace) |
| Parsing/OCR selže u souboru | soubor přeskočen + zaznamenán, sken pokračuje |
| Zastaralý sken | badge „zastaralá" u dotčených cest (Nastavení) |

### 9.6 Životní cyklus dokumentu
vznik → cesta → detekce skenem → parse → chunk → embedding → Qdrant + text/ACL v SQL → dotazy (audit) → změna/smazání → reconciliation odstraní vektory → retence auditu dle politiky.

---

## 10. Náklady (TCO, 3 roky — odhad k doplnění)

| Položka | Náklad |
|---|---|
| AI software (Ollama, Qdrant, FastAPI, modely) | 0 Kč (open-source) |
| SQL Server 2019 | 0 Kč navíc (vlastněno) |
| **GPU server** (pilot: NVIDIA L4 / RTX 4090, 24 GB VRAM; škála: L40S) | jednorázově ~150–300 tis. Kč (dle karty) |
| Elektřina, chlazení, zálohy, patch mgmt | průběžně |
| **Lidská práce** (dokončení dle roadmapy + údržba ~0,25–0,5 FTE/rok) | **dominantní položka** |

> „0 Kč za software" **neznamená** nulové TCO. U on-prem řešení je typicky **největší položkou lidský čas**, ne hardware. Férové srovnání s Azure OpenAI (EU rezidence) musí zahrnout provoz i údržbu — rozhoduje **klasifikace dat**, ne jen cena.

### 10.1 ROI (řádový odhad, k doplnění z pilotu)
Hledání informace ~5 min × ~20× týdně × 120 lidí → řádově **tisíce hodin ročně**. Při úspoře i jen 30 % se návratnost jednorázové HW investice + práce pohybuje v **měsících**, ne letech. Přesná čísla doplní reálná frekvence dotazů z pilotu.

---

## 11. Rizika a mitigace (revidováno)

| Riziko | Dopad | Pravděp. | Mitigace |
|---|---|---|---|
| **Chybějící řízení přístupu (zploštění ACL)** | **Vysoký** | **Vysoká** | **AD/Entra + ACL filtr do MVP (5.1)** |
| Stale vektory při update | Vysoký | Vysoká | mazání bloků dle zdroje před upsertem — **pre-MVP** |
| Slabé české embeddingy (nomic) | Vysoký | Střední | benchmark multilingválních modelů (4.9, 8) |
| Ztráta kontextu tabulek / neviditelná scan PDF | Vysoký | Střední | struktura-aware parsing + OCR (4.9) |
| Halucinace | Střední | Střední | grounding, citace, „nevím", feedback, rerank |
| Zastaralá/konfliktní verze směrnice | Střední | Střední | verzování dokumentů (4.9) |
| I/O zátěž reconciliation na SMB | Střední | Střední | mtime/size first, hash jen změněných (4.4) |
| Nízký výkon (CPU / slabá GPU) | Střední | Střední | GPU, streaming, kvantizace |
| Audit jako GDPR úložiště | Střední | Střední | maskování PII, retence (5.2) |
| Výpadek serveru | Střední | Nízká | DR (9.2); báze rekonstruovatelná |
| **Bus factor = 1** | Střední | Střední | dokumentace (BUILD/HANDOFF), zaškolení druhého správce |

---

## 12. Omezení a slabá místa (otevřeně)

- Kvalita open modelu (8B) < špičkové cloudové; čeština nutná ověřit.
- Prototyp má dluhy (stale vektory, chybí `on_deleted`, identita názvem, duplikovaná konfigurace, chybí payload index) — evidováno v `HANDOFF.md`, na roadmapě dopředu.
- **Řízení přístupu dnes chybí** — do produkce nepřípustné (5.1).
- Testovací sada, benchmark a měření na cílovém HW zatím neexistují (8).
- **Text-to-SQL nad BC** je jiná třída rizika (tiše špatná agregace vzatá jako fakt) → **samostatná fáze**, ne součást tohoto MVP.
- **Bus factor = 1:** projekt řeší „ztrátu know-how", ale sám je zatím závislý na jednom správci — mitigace dokumentací a zaškolením.

---

## 13. Roadmapa do produkce (reprioritizováno + odhad pracnosti)

| # | Krok | Odhad (reálný rozsah) |
|---|---|---|
| 1 | **Ověření jádra** — reconciliation cyklus na SMB (mtime/size + ACL), konektivita Linux→SQL19 | 3–5 |
| 2 | **Řízení přístupu (MVP)** — AD/Entra auth, indexace + čerstvost ACL, filtr dle tranzitivního členství, pentest | 20–30 |
| 3 | **Oprava stale vektorů + verzování dokumentů** (mazání dle zdroje, `on_deleted`, rel. cesta, payload index) | 5–8 |
| 4 | **Testovací sada + benchmark** (vč. ruční anotace ≥150 dotazů, čeština, kvantizace) | 10–15 |
| 5 | **Parsing** — OCR, tabulky (XLSX→JSON/Markdown řádky), struktura-aware chunking | 15–20 |
| 6 | **Hybridní hledání** — Qdrant sparse + RRF/rerank | 8–12 |
| 7 | **Rychlost** — streaming, volba modelu/GPU | 3–5 |
| 8 | **Provoz** — monitoring, DR, systemd, audit s maskováním, feedback smyčka | 8–12 |
| 9 | **(Samostatná fáze)** živá data z BC přes text-to-SQL (řízené šablony, ne volný text-to-SQL) | vlastní projekt |

> **Odhady navýšeny na realistické rozsahy** (dřívějších „46 dnů" bylo optimistické — ACL, testovací sada a parsing jsou reálně řádově týdny; MVP do produkce ~2–3 měsíce). Každý krok má **Definici hotového** (např. krok 2: login + ACL filtr + audit + penetrační test + review).

---

## 14. Reakce na oponenturu — co přijímáme a co ne

**Přijímáme (zapracováno výše):** priorita řízení přístupu; odstranění „0 % halucinací"; přeformulování ISO/NIS2; testovací sada a metodika; TCO s lidskou prací a konkrétní GPU; parsing (OCR/tabulky); benchmark embedding modelu; RRF/rerank a přehodnocení hybrid architektury; mtime/size v reconciliation; verzování dokumentů; audit jako GDPR úložiště; oprava rozporu inotify; text-to-SQL jako samostatná fáze; NFR/kapacita/DR/monitoring/threat model/bus factor. **(v3)** čerstvost ACL v reconciliation; explicitní k + precision@k/NDCG; práh pro „nevím"; ochrana dat u LLM-judge; reálné odhady + Definice hotového; ROI; failure modes + životní cyklus dat; ADR/STRIDE + proč FastAPI; human-in-the-loop pro důvěrné; právní ukotvení odpovědnosti.

**Odmítáme / korigujeme:**
- **„Generovat odpověď offline, pak streamovat" (proti halucinaci)** — **odmítáme.** Ruší to smysl streamingu (vnímaná latence) a lokální RAG odpověď stejně nelze ověřovat token po tokenu. Správná mitigace je grounding + citace, ne zdržení výstupu.
- **Redis cache / Kubernetes / load balancer jako povinnost** — **korigujeme na podmíněné.** Pro interní nástroj se stovkami uživatelů a nízkou konkurencí je to over-engineering; zavést až při reálném růstu konkurence.
- **„Nulový vendor lock-in"** — **korigujeme na „nízký, ne nulový".**

---

## 15. Předjímané otázky komise (s číselnou/konkrétní odpovědí)

**Q: Kdo se dostane k obsahu naindexovaného IP plánu, když k souboru nemá NTFS práva?**
A: Po zavedení řízení přístupu (krok 2) **nikdo** — ingest indexuje ACL, API filtruje výsledky podle identity uživatele; do kontextu modelu se dostane jen to, na co má práva. Dnes je odpověď „kdokoli", proto je to podmínka nasazení.

**Q: Jaké číslo dá váš embedding model na české sadě oproti multilingválnímu?**
A: Zatím neměřeno — proto je v roadmapě krok 4 (benchmark nomic vs multilingual-e5 vs BGE-m3). Volbu potvrdíme čísly, ne defaultem.

**Q: Kolik hodin práce a Kč HW do produkce, a TCO za 3 roky proti Azure OpenAI EU?**
A: HW ~150–300 tis. Kč jednorázově (GPU), práce dle roadmapy (~46 člověkodnů + ~0,25–0,5 FTE/rok údržba). Rozhodujícím faktorem proti cloudu je klasifikace dat, ne cena.

**Q: Jak řešíte protichůdné verze směrnice?**
A: Verzování (cesta+hash+čas), preference poslední verze, signalizace konfliktu (krok 3).

**Q: Jak zpracujete tabulky v XLSX/PDF a naskenované PDF?**
A: Struktura-aware parsing + OCR (krok 5); bez toho jsou scan PDF neviditelné a tabulky ztrácejí kontext — proto samostatný krok.

**Q: Jak poznáte regresi po změně modelu?**
A: Znovuvyhodnocením na testovací sadě (krok 4) — bez ní změnu modelu neděláme.

**Q: Co když asistent dá špatnou odpověď a uživatel podle ní rozhodne?**
A: Systém vždy cituje zdroje; odpovědnost zůstává na uživateli — ukotveno v **podmínkách použití** (právní review) a logováno potvrzení, že uživatel upozornění viděl (viz 5.5). Halucinace měříme a ohraničujeme, negarantujeme nulu.

---

## 16. Závěr

Projekt **navrhuje architekturu, která po implementaci plánovaných bezpečnostních a provozních opatření může splňovat** požadavky na bezpečné a udržitelné provozování v prostředí AXIMA. Verze 3.0 opravuje i poslední kritický nález (čerstvost ACL v reconciliation) a zpřesňuje evaluaci, odhady a provozní scénáře. Doporučené pokračování: realizovat roadmapu v novém pořadí, s **řízením přístupu (vč. čerstvosti ACL) a opravou stale vektorů před prvním nasazením** a s **testovací sadou a benchmarkem** jako podmínkou tvrzení o kvalitě.

---

*Anglická verze na vyžádání. Živý technický stav: [HANDOFF.md](HANDOFF.md). Postavení od nuly: [BUILD.md](BUILD.md).*

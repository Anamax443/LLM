# Jak asistent „umí" naše data

Vysvětlení pro netechnické publikum (vedení, uživatelé) i jako podklad k obhajobě. Odpovídá na otázku, kterou dostane každý: *„Jak ten model naučíte na našich datech?"*

> 🇬🇧 English: [JAK-FUNGUJE-UCENI.en.md](JAK-FUNGUJE-UCENI.en.md)

---

## Krátká odpověď

Model se **nepřetrénovává**. Místo toho mu naše dokumenty průběžně dáváme k dispozici tak, aby s nimi při každé odpovědi pracoval jako by je znal, a **vždy uvedl zdroj**. Této metodě se říká **RAG** (retrieval-augmented generation). Znalost tedy nežije „schovaná v modelu", ale v prohledávatelné bázi, kterou držíme jako **živé zrcadlo firemních souborů**.

## Přirovnání

Jazykový model (`llama3.1`) je jako **chytrý nový kolega**: skvěle umí česky a umí uvažovat, ale **naše dokumenty nikdy neviděl**.

- „Naučit ho" **neznamená** poslat ho na dlouhé školení, aby si všechno zapamatoval natrvalo — to je *fine-tuning*: drahé, pomalé a rychle zastará.
- „Naučit ho" u nás **znamená** dát mu před každou odpovědí **nalistované správné stránky** z naší dokumentace a říct: *„Odpověz jen z tohohle a napiš, odkud to máš."*
- A hlavně: jeho **příručku držíme pořád aktuální**. To průběžné doplňování je to skutečné „učení".

---

## Jak to probíhá — dvě fáze

### Fáze 1: Plnění báze (běží automaticky na pozadí)

Tohle je jádro „učení na datech":

1. **Sledování složek** — systém hlídá určené síťové cesty a pozná, co přibylo, změnilo se nebo zmizelo.
2. **Přečtení + parsing** — z DOCX/XLSX/PDF vytáhne text (u naskenovaných PDF přes OCR, u tabulek zachová vazbu řádek/sloupec).
3. **Rozsekání na bloky** — dokument rozdělí na menší překrývající se úseky, aby se dal najít i konkrétní odstavec, ne jen celý soubor.
4. **Převod na „význam" (embedding)** — každý blok se převede na vektor (seznam čísel zachycující *význam* textu). Podobný význam → blízké vektory.
5. **Uložení** — vektor + původní text + odkaz na zdroj (+ do budoucna oprávnění) se uloží do vektorové databáze.

**Důsledek:** když přidáte nový dokument, do pár minut je součástí znalostní báze — **bez trénování a bez zásahu IT**.

### Fáze 2: Odpověď na dotaz (když se někdo zeptá)

1. Otázka se **taky převede na vektor**.
2. Systém najde v bázi **nejpodobnější bloky** (významově i podle přesných výrazů — např. IP adres či kódů).
3. Tyto bloky vloží modelu jako **kontext** spolu s pokynem *„odpovídej jen z tohoto, cituj zdroj, a když tam odpověď není, řekni to"*.
4. Model vygeneruje odpověď **z dodaného kontextu** a přiloží zdroje.

Model tedy „ví" o našich datech proto, že mu je v ten okamžik podstrčíme — ne proto, že by je měl natrvalo v paměti.

```
PLNĚNÍ BÁZE (průběžně)              DOTAZ (v reálném čase)
soubory → text → bloky →            otázka → vektor →
vektory → databáze                  najít podobné bloky →
                                    kontext + pravidla → model →
                                    odpověď + zdroje
```

---

## Co je na tom „dlouhodobé učení"

Dvě věci, obě **bez přetrénování modelu**:

- **Aktuálnost báze** — automatické zrcadlení souborů: nový/změněný/smazaný dokument se promítne do báze. Systém se tak „učí" každou změnou dokumentace sám.
- **Zpětná vazba** — hodnocení odpovědí (👍/👎) sbíráme a používáme ke zlepšení toho, *co a jak systém hledá*, případně k označení dokumentů k revizi.

---

## A skutečné doučování modelu (fine-tuning)?

Jen jako **vědomý, samostatný krok** — nikdy ne automaticky. Mělo by smysl třeba pro firemní **styl a tón** odpovědí. Pro **fakta z dokumentů se nehodí**, protože:
- fakta se mění rychleji, než by šlo model trénovat,
- ztratila by se **dohledatelnost zdroje** (audit),
- trénování na neověřených datech kvalitu **zhoršuje**.

Proto: **fakta = RAG**, fine-tuning až později a jen pod dozorem.

---

## Nejčastější námitky

- *„Když se nepřetrénovává, jak to, že zná naše věci?"* — Protože je při každé odpovědi **prohledá a přečte** z aktuální báze. Je to jako kolega s dokonalým vyhledáváním v našich složkách.
- *„Co když si vymyslí?"* — Odpovídá jen z dodaného kontextu, cituje zdroj a má povoleno říct „nevím". Míru chyb měříme a ohraničujeme (ne však na nulu — to žádný model nezaručí).
- *„Uvidí zaměstnanec i to, na co nemá právo?"* — Nesmí. Proto je **řízení přístupu** (napojení na Active Directory a filtr podle oprávnění) podmínkou nasazení, ne pozdější doplněk.

Podrobnosti: [OPONENTURA.md](OPONENTURA.md) (rozhodnutí a rizika), [README.md](../README.md) (přehled), [BUILD.md](BUILD.md) (postavení systému).

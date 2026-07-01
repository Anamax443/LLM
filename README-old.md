Kompletní průvodce nasazením AI Agenta (Axima) - Verze 1.0

Tento dokument slouží jako absolutní Krok za krokem manuál pro nasazení lokálního AI asistenta (RAG) pro práci s firemní dokumentací. Je napsán tak, aby systém dokázal zprovoznit i administrátor bez předchozí hluboké znalosti kontejnerizace.

Systém je navržen s ohledem na bezpečnost (ISO 27001 / NIS2) – veškerá data zůstávají na lokálním serveru a služba není vystavena do firemní sítě.

FÁZE 1: Příprava Linux serveru (Instalace Dockeru)
Předpoklad: Máte čistý Ubuntu Server a jste připojeni přes SSH.

Aktualizace systému:
V terminálu spusťte následující příkaz pro stažení nejnovějších aktualizací:
sudo apt update && sudo apt upgrade -y

Instalace Dockeru a Docker Compose:
Tyto nástroje slouží k běhu izolovaných kontejnerů (aplikací).
sudo apt install docker.io docker-compose -y

Nastavení práv (abyste nemuseli psát 'sudo'):
Přidejte svého uživatele do skupiny docker a aplikujte změny (po tomto kroku se doporučuje odhlásit a znovu přihlásit k SSH, případně spustit druhý příkaz):
sudo usermod -aG docker $USER
newgrp docker

FÁZE 2: Vytvoření struktury projektu
Nyní vytvoříme složku pro projekt a konfigurační soubory.

Vytvoření hlavní složky (vložte postupně tyto dva příkazy):
mkdir ~/ai-axima
cd ~/ai-axima

Vytvoření souboru docker-compose.yml:
Tento soubor definuje celou architekturu (Backend i Frontend). Otevřete editor:
nano docker-compose.yml

Do editoru vložte tento kód (přesně včetně mezer a odsazení):

services:
ollama_backend:
image: ollama/ollama:latest
container_name: ollama_backend
volumes:
- ./data/ollama:/root/.ollama
restart: always

open_webui_frontend:
image: ghcr.io/open-webui/open-webui:main
container_name: open_webui_frontend
ports:
- "127.0.0.1:8080:8080"
volumes:
- ./data/open-webui:/app/backend/data
environment:
- OLLAMA_BASE_URL=http://ollama_backend:11434
depends_on:
- ollama_backend
restart: always

Uložení v Nano editoru: Zmáčkněte Ctrl+O, potvrďte klávesou Enter a ukončete přes Ctrl+X.

Vytvoření bezpečnostního štítu pro Git (.gitignore):
Abychom omylem neodeslali gigabyty firemních dat a AI modelů na GitHub, vytvoříme ignorovací soubor.
Spusťte editor:
nano .gitignore

Vložte tento text:

Ignorovat databáze, vektorové indexy a LLM modely
/data/

Ignorovat konfigurace VSCode prostředí
.vscode/
.vscode-server/

Ignorovat systémové soubory OS
.DS_Store
*.log

Uložte přes Ctrl+O, potvrďte Enter a ukončete přes Ctrl+X.

FÁZE 3: Spuštění systému a stažení AI modelu

Start kontejnerů:
Ujistěte se, že jste ve složce ~/ai-axima a spusťte:
docker compose up -d

Systém stáhne potřebné obrazy z internetu a nastartuje služby na pozadí.

Stažení chytrého modelu (Qwen2):
Frontend už běží, ale AI zatím nemá mozek. Přikážeme backendu, aby stáhl model optimalizovaný pro češtinu a fakticitu:
docker exec ollama_backend ollama pull qwen2

Počkejte na dokončení stahování (v terminálu se po chvíli zobrazí hláška success).

FÁZE 4: Zabezpečený přístup uživatele (VSCode)
Služba z bezpečnostních důvodů běží pouze na vnitřním portu serveru. Uživatelé k ní přistupují přes bezpečný SSH tunel.

Příprava na klientském PC:

Nainstalujte editor Visual Studio Code (VSCode).

V levém panelu Extensions (Rozšíření) vyhledejte a nainstalujte Remote - SSH (od Microsoftu).

Vytvoření tunelu:

Ve VSCode klikněte vlevo dole na zelenou ikonu >< a zvolte Connect to Host...

Zadejte uživatele a IP adresu serveru (např. ssh jmeno@10.8.5.141).

Jakmile jste připojeni, otevřete spodní panel (terminál) a překlikněte na záložku Ports (Porty).

Klikněte na Forward a Port a napište 8080.

Přihlášení:

Otevřete na svém PC webový prohlížeč.

Zadejte adresu: http://localhost:8080

Vytvořte si první administrátorský účet (Sign Up).

FÁZE 5: Nastavení přesnosti AI (Ochrana proti halucinacím)
Aby systém fungoval jako striktní firemní asistent a ne jako volnomyšlenkářský chatbot, je nutné nastavit mantinely.

Konfigurace v Open WebUI:

Klikněte na svůj profil (vlevo dole) -> Workspace -> Models.

Vytvořte nový model nebo upravte existující.

Base Model (Základní model): Vyberte qwen2.

Pokročilé parametry (Advanced) -> Temperature: Změňte na 0.1 (Zásadní pro faktickou přesnost).

Systémové instrukce (System Prompt): Zkopírujte a vložte přesně tento text:

Jsi striktně faktický inženýrský asistent firmy Axima. Odpovídáš VÝHRADNĚ česky. Tvojí prioritou je přesnost. Při odpovídání vždy cituj zdroj (např. [dokument.pdf]). Pokud se informace liší, upřednostni soubory s prefixem GLOBAL_. Pokud informace není v kontextu dostupná, odepiš POUZE: Informace není v dokumentaci dostupná. Nikdy si nevymýšlej závěry.

Pravidla pro dokumenty (RAG):

Soubory se nahrávají v sekci Workspace -> Znalosti (Knowledge).

Pro nejdůležitější pravidla sítě (která mají přebít staré PDF soubory) vytvářejte textové soubory .md a pojmenovávejte je s prefixem GLOBAL_ (např. GLOBAL_stav_site.md).

V chatu připojíte dokumenty napsáním znaku #.

FÁZE 6: Zálohování do GitHubu přes VSCode
Tento krok nahraje naši infrastrukturu do Gitu, aniž bychom odeslali citlivá data ze složky /data.

Inicializace:

Ve VSCode (stále připojeni přes SSH na serveru) otevřete vlevo složku projektu (~/ai-axima).

Klikněte na ikonu Source Control (třetí shora, rozvětvený strom).

Klikněte na Initialize Repository.

Commit:

V seznamu Changes uvidíte POUZE tři soubory: docker-compose.yml, README-old.md a .gitignore. (Složka data chybí, což je správně).

Klikněte na ikonu + (Stage All Changes).

Do kolonky Message napište: Initial commit: Kompletní instalace a konfigurace.

Klikněte na Commit.

Publikace (Push):

Klikněte na Publish Branch.

Vyberte Publish to GitHub private repository (Soukromý repozitář).

Postupujte podle pokynů prohlížeče pro autorizaci VSCode s vaším účtem na GitHubu. Hotovo.
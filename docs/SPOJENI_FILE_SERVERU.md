# Architektonický návrh propojení File Serveru a Linux Serveru

Tento dokument detailně navrhuje řešení pro **dynamické a bezpečné připojování (mounting) síťových složek** z Windows File Serveru na Linuxový aplikační server (RAG asistent). Řešení umožňuje operátorovi konfigurovat síťové cesty (UNC formát) přímo ve webovém rozhraní, přičemž Linuxový backend se postará o jejich automatické namountování, ověření dostupnosti a zapojení do periodického skenovacího cyklu (reconciliation sken).

---

## 1. Architektura a tok dat

```
 ┌────────────────────────────────────────────────────────────────────────┐
 │                      Webový prohlížeč (Administrátor)                 │
 └──────────────────────────────────┬─────────────────────────────────────┘
                                    │ 
                                    │ POST /api/settings  (přidání \\server\share\cesta)
                                    ▼
 ┌────────────────────────────────────────────────────────────────────────┐
 │                        FastAPI Backend (api.py)                        │
 └───────┬──────────────────────────┬───────────────────────────────┬─────┘
         │                          │                               │
         │ 1. Uloží cestu do DB     │ 2. Zavolá Mount Manager       │ 3. Spustí sken
         ▼                          ▼                               ▼
 ┌───────────────┐          ┌───────────────┐               ┌───────────────┐
 │ SQL Server 19 │          │ Mount Manager │               │  Reconciler   │
 │ (Konfigurace) │          │ (Python/Sudo) │               │   (Watchdog)  │
 └───────────────┘          └───────┬───────┘               └───────┬───────┘
                                    │                               │
                                    │ mount -t cifs                 │ čte lokální soubory
                                    ▼                               ▼
                     ┌───────────────────────────────┐              │
                     │ Linux Mountpoint (/mnt/...)  ◄───────────────┘
                     └──────────────┬────────────────┘
                                    │
                                    │ SMB2.1/3.0 protokoly
                                    ▼
 ┌────────────────────────────────────────────────────────────────────────┐
 │                    Windows Active Directory File Server                │
 └────────────────────────────────────────────────────────────────────────┘
```

### Hlavní principy řešení:
1. **Jedno rozhraní (Single Source of Truth):** Operátor zadá Windows UNC cestu (např. `\\herkules\public\smernice`) ve webovém prohlížeči. Cesta se uloží do SQL Serveru.
2. **Dynamic Mounting Daemon / Service (Mount Manager):** Linuxový backend zachytí změnu konfigurace, přeloží UNC cestu na lokální cestu (např. `/mnt/herkules/public/smernice`) a zajistí bezpečné namountování přes `mount -t cifs`.
3. **Reconciliation Sken:** Jakmile je složka úspěšně namountována, watchdog (`watchdog_service.py`) k ní přistupuje jako k lokálnímu adresáři a periodicky (např. každých 15 minut) porovnává stav (velikost, `mtime`, hash, ACL) se stavem uloženým v DB.

---

## 2. Technické řešení dynamic mountu na Linuxu

Linux běžně vyžaduje práva `root` pro připojování souborových systémů. Aby mohl backend běžící pod neprivilegovaným uživatelem (např. `rag-user`) dynamicky provádět mount, navrhujeme tři možné přístupy. Doporučujeme **Přístup A (Mount Manager s helper skriptem pod Sudo)**, protože poskytuje plnou programovou kontrolu a okamžitou odezvu v UI bez závislosti na vnějších daemonech typu autofs.

### Přístup A: Programový Mount Manager s delegovaným `sudo` (Doporučeno)

Backend (FastAPI) spouští dedikovaný Python subsystém `MountManager`, který volá bezpečný shell skript nebo příkaz přes `sudo` s přesně vymezeným rozsahem oprávnění v `/etc/sudoers`.

#### 1. Konfigurace sudoers (`/etc/sudoers.d/rag-mount`)
Chrání systém před spuštěním libovolného příkazu. Povoluje pouze specifický montážní helper:
```sudoers
rag-user ALL=(root) NOPASSWD: /usr/local/bin/rag-mount-helper.sh
```

#### 2. Bezpečný Helper Skript (`/usr/local/bin/rag-mount-helper.sh`)
Skript validuje vstupy a bezpečně volá `mount` se správnými parametry pro SMB/CIFS a integrací do Active Directory.
```bash
#!/bin/bash
set -euo pipefail

# Validace vstupů
ACTION=$1      # mount / umount
UNC_PATH=$2    # \\server\share
LOCAL_DIR=$3   # /mnt/server/share

if [[ ! "$LOCAL_DIR" =~ ^/mnt/ ]]; then
    echo "Chyba: Cesta musí začínat na /mnt/" >&2
    exit 1
fi

# Převod zpětných lomítek na dopředná pro Linux cifs helper
SMB_SOURCE=$(echo "$UNC_PATH" | tr '\\' '/')

if [ "$ACTION" = "mount" ]; then
    # Vytvoření adresáře pokud neexistuje
    mkdir -p "$LOCAL_DIR"
    
    # Kontrola, zda již není namountováno
    if mountpoint -q "$LOCAL_DIR"; then
        echo "Již namountováno"
        exit 0
    fi
    
    # Mount s využitím bezpečně uložených přihlašovacích údajů
    # Používáme SMB v3, read-only přístup (RAG asistent data nemění), mapování práv na rag-user
    mount -t cifs "$SMB_SOURCE" "$LOCAL_DIR" \
        -o credentials=/etc/rag/.smbcredentials,ro,nosuid,nodev,noexec,iocharset=utf8,vers=3.0,uid=rag-user,gid=rag-user
        
    echo "Mount úspěšný"

elif [ "$ACTION" = "umount" ]; then
    if mountpoint -q "$LOCAL_DIR"; then
        umount -l "$LOCAL_DIR"
        rmdir "$LOCAL_DIR" || true
        echo "Umount úspěšný"
    else
        echo "Není namountováno"
    fi
fi
```

### Přístup B: Systemd Automount (Alternativa pro statické sdílené disky)
Pokud by se cesty měnily jen zřídka, lze generovat `.mount` a `.automount` soubory do `/etc/systemd/system/`. Systemd se pak postará o připojení disku až v okamžiku, kdy do něj poprvé přistoupí `watchdog_service.py` (on-demand mounting).

---

## 3. Správa přístupových údajů (Credentials)

Připojení k Windows File Serveru v podnikovém prostředí vyžaduje doménový účet (Active Directory). Pro zajištění bezpečnosti nesmí přihlašovací údaje procházet přes UI a nesmí být uloženy v otevřeném textu v DB.

### Řešení: Doménový Service Account
1. V AD se vytvoří dedikovaný servisní účet (např. `svc-rag-reader@domain.local`).
2. Účtu se na File Serveru přidělí striktně **Read-Only** oprávnění (čtení obsahu složek a čtení NTFS ACL).
3. Přihlašovací údaje se bezpečně uloží přímo na Linuxovém serveru do souboru `/etc/rag/.smbcredentials` chráněného právy `chown root:root` a `chmod 600`:
   ```ini
   username=svc-rag-reader
   password=BezpecneHeslo123
   domain=domain.local
   ```
4. Linuxový jádrový CIFS klient použije tyto údaje při sestavování SMB session. RAG asistent tak má garantovaný zabezpečený přístup.

---

## 4. Překlad cest: Windows UNC ↔ Linux Mountpoint

Uživatelé v AXIMA pracují ve Windows a znají cesty jako `\\herkules\public\smernice`. Linuxový backend však potřebuje lokální cestu.

Navrhujeme kanonický mapovací algoritmus (který je již částečně přítomen v `api.py` pod `unc_to_local`):
1. **Normalizace lomítek:** `\\herkules\public\smernice` → `//herkules/public/smernice`
2. **Sestavení lokálního mountpointu:** Pod kořenem `/mnt` (lze konfigurovat přes `.env` jako `UNC_MOUNT_ROOT`) se vytvoří cesta z hostu a názvu sdílené složky:
   - `\\herkules\public\smernice` → `/mnt/herkules/public/smernice`
3. **Rozlišení Share vs Podadresář:** Mount se provádí vždy na úrovni **Share** (`\\herkules\public`). Podadresáře (`smernice`) se již nemountují samostatně, jsou automaticky přístupné uvnitř namountovaného share.
   - *Příklad:*
     - Vstup: `\\herkules\public\it-postupy\pdf`
     - Detekovaný SMB Share: `\\herkules\public` (namountuje se do `/mnt/herkules/public`)
     - Cesta pro sken: `/mnt/herkules/public/it-postupy/pdf`

---

## 5. Implementace v FastAPI Backend (`api.py`)

Zde je konkrétní návrh integrace do API. Endpoint `/api/verify` se rozšíří tak, aby kromě pouhého ověření přítomnosti složky na disku dokázal vyvolat pokus o automatický mount, pokud složka ještě není namountovaná.

### Rozšířený `/api/verify` v `api.py`

```python
# Předpokládá se existence funkcí parse_unc, unc_to_local a ensure_mounted z `api.py`
# Dále, MOUNT_ROOT je definován v api.py

@app.post("/api/verify")
def verify_paths(req: VerifyRequest):
    """Ověří platnost/dostupnost cest ze strany serveru (os.path.isdir).
    Zajišťuje automatické namountování přes cifs a vrací [{path, ok, resolved, error}]."""
    results = []
    for p in req.paths:
        try:
            # Zajistíme dynamic mount na Linuxu (na Windows vrací přímo lokální/UNC cestu)
            local = ensure_mounted(p)
            ok = os.path.isdir(local) and os.access(local, os.R_OK)
            error_msg = None
        except Exception as e:
            local = None
            ok = False
            error_msg = str(e)
            
        results.append({
            "path": p, 
            "ok": ok, 
            "resolved": local,
            "error": error_msg
        })
    return results
```

**Manuální kroky pro nastavení Linux serveru:**
Podrobné kroky pro přípravu Linux serveru (instalace `cifs-utils`, konfigurace `sudoers`, vytvoření `.smbcredentials` a deploy `rag-mount-helper.sh`) jsou popsány v dokumentu **[docs/LINUX_SETUP_GUIDE.md](LINUX_SETUP_GUIDE.md)**. Tyto kroky musí provést administrátor s přístupem k cílovému Linuxovému serveru.

---

## 6. Integrace do Web UI (`web/index.html`)

Webové rozhraní na záložce **Nastavení** již obsahuje seznam cest. Navržené propojení přináší tyto změny do UI:
1. **Ověření a Mount:** Kliknutím na tlačítko „Ověřit dostupnost cest“ odešle UI seznam nakonfigurovaných UNC cest na `/api/verify`. Backend se pokusí o mount. Pokud uspěje, UI změní stav cesty na **Zelený (Aktivní / Ověřeno)**.
2. **Detailní chyby v terminálu Nastavení:** Pokud mount selže (např. neplatné přihlašovací údaje v `/etc/rag/.smbcredentials` nebo nedostupný File Server), vrátí backend podrobnou chybu (např. *Permission Denied*, *Host Unreachable*), kterou UI vypíše do integrovaného diagnostického terminálu na záložce Nastavení. Tím operátor ihned ví, kde je problém.

---

## 7. Bezpečnostní opatření (ISO 27001 / NIS2)

Integrace síťového file serveru s lokálním RAG asistentem představuje bezpečnostní výzvy, které toto řešení striktně adresuje:

1. **Striktní Read-Only přístup:** Mount je realizován s parametrem `ro`. RAG asistent nemůže na File Serveru nic měnit, smazat, ani tam zanést ransomware.
2. **Izolace práv na Linuxu:** Namountovaný share má nastavená Linuxová práva pro vlastníka a skupinu `rag-user:rag-user` a masku, která neumožňuje ostatním lokálním uživatelům na serveru číst tyto soubory (ochrana před lokálním únikem dat).
3. **Indexace a filtrace ACL:** Jak je definováno v oponentuře v3 (rozhodnutí 10 a 15), RAG asistent při skenování souborů načte i jejich **NTFS bezpečnostní deskriptory (ACL)**. Tyto informace (které AD skupiny mají k souboru přístup) se uloží jako payload k vektorům do Qdrantu. Při dotazu uživatele v chatu se zjišťuje jeho tranzitivní členství v AD skupinách a vyhledávací dotaz do Qdrantu se předem vyfiltruje tak, aby uživatel mohl dostat odpovědi pouze z dokumentů, ke kterým má reálně ve Windows přístup.
4. **Zamezení Shell Injection:** Volání externích příkazů je ošetřeno — nepoužívá se `shell=True`, argumenty jsou předávány jako pole a vstupní cesty jsou striktně validovány regulárními výrazy.

---

## 8. Plán nasazení a ověření (Success Criteria)

Kroky pro úspěšné zprovoznění na cílovém prostředí:

1. **Příprava AD účtu:** Vytvoření doménového účtu `svc-rag-reader` a nastavení oprávnění na File Serveru.
2. **Instalace cifs-utils:** Na Linux serveru nainstalovat balík pro podporu SMB (`sudo apt install cifs-utils`).
3. **Uložení credentials:** Vytvoření souboru `/etc/rag/.smbcredentials` a nastavení bezpečné masky (`chmod 600`).
4. **Deploy Sudo helperu:** Nasazení helper skriptu do `/usr/local/bin` a konfigurace `/etc/sudoers.d/rag-mount`.
5. **Ověření z UI:** Přidání testovací UNC cesty ve webovém rozhraní, kliknutí na „Ověřit dostupnost cest“ a ověření, že se složka automaticky připojila pod `/mnt` a její stav zezelenal.

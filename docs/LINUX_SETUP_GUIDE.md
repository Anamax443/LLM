# Průvodce nastavením Linux serveru pro Dynamic File Server Mount

Tento dokument popisuje manuální kroky, které je nutné provést na cílovém Linuxovém serveru, aby bylo možné dynamicky připojovat síťové složky z Windows File Serveru přes webové rozhraní AXIMA RAG asistenta.

---

## 1. Vytvoření servisního účtu Active Directory

Na vašem Windows Domain Controlleru (nebo jiném stroji s RSAT) vytvořte dedikovaný servisní účet pro přístup k souborovým serverům. Tento účet bude použit pro montování SMB/CIFS sdílených složek.

- **Příklad názvu:** `svc-rag-reader`
- **Oprávnění:** Udělte tomuto účtu striktně **Read-Only** oprávnění (čtení obsahu složek a čtení NTFS ACL) na všech sdílených složkách, které má RAG asistent indexovat.

---

## 2. Instalace `cifs-utils` na Linux serveru

Nástroje pro práci se souborovými systémy CIFS (Common Internet File System), které jsou potřeba pro montování Windows sdílených složek.

```bash
sudo apt update
sudo apt install -y cifs-utils
```

---

## 3. Vytvoření adresáře pro credentials a souboru `.smbcredentials`

Vytvořte bezpečný adresář a soubor, kam se uloží přihlašovací údaje k servisnímu účtu AD. Tyto údaje jsou citlivé a musí být chráněny.

```bash
sudo mkdir -p /etc/rag
sudo touch /etc/rag/.smbcredentials
sudo chmod 600 /etc/rag/.smbcredentials
sudo chown root:root /etc/rag/.smbcredentials
```

**Editace souboru `/etc/rag/.smbcredentials`:**
Otevřete soubor v textovém editoru (např. `nano` nebo `vim`) a vložte do něj následující obsah. Nahraďte zástupné hodnoty za skutečné údaje vašeho servisního účtu.

```bash
sudo nano /etc/rag/.smbcredentials
```

Obsah souboru by měl vypadat takto:
```ini
username=svc-rag-reader
password=VaseBezpecneHeslo123
domain=VaseDomena.local
```

---

## 4. Deploy Helper Skriptu `rag-mount-helper.sh`

Zkopírujte připravený helper skript `rag-mount-helper.sh` (který byste měli mít lokálně v repozitáři) do systémové cesty a nastavte mu spustitelná práva.

```bash
sudo cp rag-mount-helper.sh /usr/local/bin/rag-mount-helper.sh
sudo chmod +x /usr/local/bin/rag-mount-helper.sh
```

---

## 5. Konfigurace `sudoers` pro delegování práv

Nastavte `sudoers` tak, aby uživatel, pod kterým běží FastAPI aplikace (např. `rag-user`), mohl spouštět `rag-mount-helper.sh` bez hesla. Tím se umožní dynamické montování z webového rozhraní.

```bash
sudo visudo -f /etc/sudoers.d/rag-mount
```

Do otevřeného souboru vložte následující řádek:
```sudoers
rag-user ALL=(root) NOPASSWD: /usr/local/bin/rag-mount-helper.sh
```

> **DŮLEŽITÉ:** Nahraďte `rag-user` skutečným uživatelským jménem, pod kterým běží vaše FastAPI aplikace. Pokud aplikace běží pod `gunicorn` nebo `systemd` službou, zjistěte jejího systémového uživatele.

---

## 6. Vytvoření kořenového adresáře pro mountpointy

Vytvořte adresář, který bude sloužit jako kořen pro všechny dynamicky připojované sdílené složky.

```bash
sudo mkdir -p /mnt
```

---

## 7. Restart FastAPI aplikace

Po dokončení všech konfigurací restartujte FastAPI aplikaci, aby se načetly nové systémové konfigurace a skripty.

```bash
sudo systemctl restart <nazev_vasi_fastapi_sluzby>
# Příklad: sudo systemctl restart axima-rag-api.service
```

---

## 8. Ověření funkčnosti z Web UI

Po restartu by mělo být možné v webovém rozhraní AXIMA RAG asistenta (záložka **Nastavení**) přidat UNC cestu (`\\server\share\cesta`) a po kliknutí na „Ověřit dostupnost cest“ by se složka měla automaticky připojit pod `/mnt` a její stav by se měl změnit na „Aktivní / Ověřeno“.
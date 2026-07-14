# Průvodce nastavením Linux serveru pro User-Space SMB (gMSA & Kerberos)

Tento dokument popisuje kroky, které je nutné provést na cílovém Linuxovém serveru, aby bylo možné bezpečně přistupovat k síťovým složkám z Windows File Serveru přímo v Python aplikaci (User Space) s využitím Group Managed Service Account (gMSA) a Kerberos ověřování.

> **Naše prostředí (AXIMA) — konkrétní hodnoty pro placeholdery níže:**
> - Kerberos realm: **`AXINETWORK.LOC`** (doména `axinetwork.loc`; kód automaticky doplňuje FQDN k NetBIOS jménům hostitelů)
> - Spouštěcí uživatel aplikace: **`aixima`** (v obecném návodu značen `rag-user`)
> - Kerberos ccache: **`FILE:/home/aixima/krb5cc_axima`** (kód nastavuje přes `KRB5CCNAME`)
> - Systemd služba API+web: **`axima-web.service`** (v obecném návodu značena `axima-rag-api.service`)

---

## 1. Příprava gMSA účtu v Active Directory

Na Windows Domain Controlleru (nebo stroji s RSAT) vytvořte nebo nakonfigurujte gMSA účet:

- **Příklad názvu:** `svc-rag-reader$`
- **Oprávnění:** Udělte tomuto účtu striktně **Read-Only** oprávnění (čtení obsahu složek a čtení NTFS ACL) na sdílených složkách, které má RAG asistent indexovat.
- **Povolení pro Linux hostitele:** Ujistěte se, že počítačový účet Linuxového serveru má oprávnění získat heslo pro tento gMSA účet (`Get-ADServiceAccount`).

---

## 2. Instalace závislostí na Linux serveru

Pro podporu protokolu SMBv3 a Kerberos ověřování nainstalujte potřebné systémové balíky a Python knihovny:

### Systémové balíky
```bash
sudo apt update
sudo apt install -y krb5-user libkrb5-dev devscripts gcc python3-dev
```
Během instalace `krb5-user` budete vyzváni k zadání výchozího Kerberos realmu (např. `VASEDOMENA.LOCAL`).

### Python knihovny v prostředí aplikace
Nainstalujte požadované Python knihovny do virtuálního prostředí vaší FastAPI aplikace:
```bash
pip install smbprotocol smbclient gssapi
```

---

## 3. Konfigurace Kerbera (`/etc/krb5.conf`)

Otevřete konfiguraci Kerbera a ujistěte se, že správně ukazuje na vaše Active Directory doménové řadiče (KDC):

```bash
sudo nano /etc/krb5.conf
```

Příklad konfigurace:
```ini
[libdefaults]
    default_realm = VASEDOMENA.LOCAL
    dns_lookup_realm = false
    dns_lookup_kdc = true

[realms]
    VASEDOMENA.LOCAL = {
        kdc = dc1.vasedomena.local
        kdc = dc2.vasedomena.local
        admin_server = dc1.vasedomena.local
    }

[domain_realm]
    .vasedomena.local = VASEDOMENA.LOCAL
    vasedomena.local = VASEDOMENA.LOCAL
```

---

## 4. Generování a ochrana Kerberos Keytabu (Kritické z hlediska bezpečnosti)

Keytab soubor obsahuje kryptografické klíče gMSA účtu a funguje jako ekvivalent hesla. **Musí být chráněn před neoprávněným čtením.**

### Generování keytabu na AD (přes ktpass) nebo přímo na Linuxu
Na Windows Domain Controlleru vygenerujte keytab soubor pro gMSA účet:
```cmd
ktpass /out svc-rag-reader.keytab /princ svc-rag-reader$@VASEDOMENA.LOCAL /mapuser svc-rag-reader$ /crypto AES256-SHA1 /ptype KRB5_NT_PRINCIPAL -pass +
```
*(Upozornění: gMSA rotuje své heslo automaticky, přepínač `-pass +` vygeneruje náhodné heslo spojené s účtem).*

### Bezpečné umístění a nastavení práv na Linuxu
Přeneste soubor `svc-rag-reader.keytab` na Linux server a umístěte jej do dedikované složky `/etc/rag/`.

**Nastavení striktních přístupových práv (ISO 27001):**
Keytab nesmí být čitelný nikým jiným než spouštěcím uživatelem FastAPI aplikace (např. `rag-user`).

```bash
sudo mkdir -p /etc/rag
sudo mv svc-rag-reader.keytab /etc/rag/
sudo chown rag-user:rag-user /etc/rag/svc-rag-reader.keytab
sudo chmod 400 /etc/rag/svc-rag-reader.keytab
```

> **DŮLEŽITÉ:** Práva `400` garantují, že soubor může číst pouze vlastník `rag-user` a nikdo jiný na serveru k němu nemá přístup. Tím se předchází bezpečnostním incidentům a úniku pověření.

---

## 5. Odstranění staré konfigurace (Úklid)

Jelikož přecházíme na čisté uživatelské řešení, je nutné odstranit staré zranitelné konfigurace z OS:

```bash
# 1. Smazání starého mount skriptu
sudo rm -f /usr/local/bin/rag-mount-helper.sh

# 2. Smazání delegování práv v sudoers
sudo rm -f /etc/sudoers.d/rag-mount

# 3. Odinstalace nepotřebných balíků (volitelně)
sudo apt purge -y cifs-utils
```

---

## 6. Automatická obnova Kerberos lístku (Systemd Service)

Aby aplikace neztratila přístup k síťovým složkám po vypršení Kerberos ticketu (obvykle 10 hodin), vytvoříme jednoduchou systemd službu/timer pro periodické volání `kinit` na pozadí pod uživatelem `rag-user`.

Vytvořte službu `/etc/systemd/system/rag-kinit.service`:
```ini
[Unit]
Description=Obnova Kerberos Ticketu pro RAG gMSA
After=network.target

[Service]
Type=oneshot
User=rag-user
ExecStart=/usr/bin/kinit -kt /etc/rag/svc-rag-reader.keytab svc-rag-reader$@VASEDOMENA.LOCAL
```

Vytvořte timer `/etc/systemd/system/rag-kinit.timer`:
```ini
[Unit]
Description=Periodicka obnova Kerberos Ticketu pro RAG

[Timer]
OnBootSec=1min
OnUnitActiveSec=4h

[Install]
WantedBy=timers.target
```

Aktivujte timer:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now rag-kinit.timer
```

---

## 7. Restart FastAPI aplikace

Po dokončení konfigurace restartujte službu RAG asistenta, aby začala využívat novou pipeline bez OS závislostí:

```bash
sudo systemctl restart axima-web.service
```

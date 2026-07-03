# Architektonický návrh propojení File Serveru a Linux Serveru (User-Space SMB)

Tento dokument detailně navrhuje řešení pro **dynamické a bezpečné připojování a čtení** síťových složek z Windows File Serveru do Linuxové aplikační aplikace (RAG asistent) nativně v uživatelském prostoru (User Space) bez nutnosti montování na úrovni operačního systému.

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
         │ 1. Uloží cestu do DB     │ 2. Ověří cestu přes SMB       │ 3. Spustí sken
         ▼                          ▼                               ▼
 ┌───────────────┐          ┌───────────────┐               ┌───────────────┐
 │ SQL Server 19 │          │   smbclient   │               │  Reconciler   │
 │ (Konfigurace) │          │ (Python/User) │               │   (Skenování) │
 └───────────────┘          └───────┬───────┘               └───────┬───────┘
                                    │                               │
                                    │ TCP 445 (SMBv3)               │ Čte soubory přes SMB
                                    ▼                               ▼
 ┌────────────────────────────────────────────────────────────────────────┐
 │                    Windows Active Directory File Server                │
 └────────────────────────────────────────────────────────────────────────┘
```

### Hlavní principy řešení:
1. **Jedno rozhraní (Single Source of Truth):** Operátor zadá Windows UNC cestu (např. `\\herkules\public\smernice`) ve webovém prohlížeči. Cesta se uloží do SQL Serveru.
2. **Uživatelský SMB Klient:** Linuxový backend nepoužívá `cifs-utils` ani nepotřebuje práva `root` pro montování disků. Místo toho se připojuje k Windows File Serveru jako standardní síťový klient pomocí čistě pythonovské knihovny `smbclient` (nad `smbprotocol`).
3. **Dočasné stahování souborů pro analýzu (Temporary Directory):** Knihovny pro analýzu dokumentů (`pdfplumber`, `python-docx`, `openpyxl`) vyžadují lokální přístup k souborům. Abychom předešli bezpečnostnímu riziku ponechání citlivých dat v `/tmp` při chybě nebo pádu aplikace, soubory se stahují do kontextem řízeného dočasného adresáře (`tempfile.TemporaryDirectory()`), který garantuje smazání celého obsahu i při neočekávaných haváriích.
4. **Reconciliation Sken:** Watchdog na úrovni `inotify` je pro síťové cesty nespolehlivý. Systém proto využívá periodické (např. každých 15 minut) procházení struktury přes `smbclient.walk()`, porovnává změny (velikost, `mtime` a hash ACL) s DB a zpracovává pouze modifikované nebo nové dokumenty.

---

## 2. Výhody User-Space řešení oproti OS Mountu

| Vlastnost | OS-Level Mount (`cifs-utils`) | User-Space SMB (`smbclient`) |
|---|---|---|
| **Oprávnění systému** | Vyžaduje `root` práva (přes `sudoers`) | Běží pod neprivilegovaným uživatelem (`rag-user`) |
| **Bezpečnost** | Riziko Privilege Escalation přes helper skript | Maximální izolace, nulové navýšení systémových práv |
| **Stabilita při výpadku** | OS se zablokuje ve stavu "stale file handle" (I/O freeze) | Vyhodí standardní Python výjimku (rychlý fail/recovery) |
| **gMSA kompatibilita** | Složitá integrace přes Kerberos keytab v OS | Čistá integrace s Kerberos tokeny v rámci Python relace |
| **Zbytková data** | Soubory jsou trvale vystaveny v `/mnt/...` | Soubory se stáhnou na zlomek sekundy do `/tmp` a smažou se |

---

## 3. Práce s UNC cestou a Ingest Pipeline

Kanonický proces zpracování souboru ze síťové složky:

```python
import os
import tempfile
from smbclient import open_file as smb_open

def process_remote_file(unc_path):
    """
    Bezpečné stažení vzdáleného souboru do izolovaného dočasného adresáře
    a jeho následná analýza.
    """
    # TemporaryDirectory se postará o úklid automaticky i při kritické výjimce (OOM, pád)
    with tempfile.TemporaryDirectory(prefix="rag_ingest_") as temp_dir:
        # Extrakce názvu souboru pro zachování správné přípony pro parsery
        local_filename = os.path.basename(unc_path.replace('\\', '/'))
        tmp_path = os.path.join(temp_dir, local_filename)
        
        # Streamování dat z Windows File Serveru přímo do dočasného lokálního souboru
        with smb_open(unc_path, "rb") as remote_f, open(tmp_path, "wb") as local_f:
            local_f.write(remote_f.read())
            
        # Bezpečná analýza lokálního souboru
        text = extract_text(tmp_path)
        
    # temp_dir je nyní automaticky smazán z disku
    return text
```

---

## 4. Správa přístupových údajů a Integrace Active Directory

Systém plně podporuje integraci do podnikového prostředí Active Directory.

### Možnost A: Doménový gMSA účet (Doporučeno pro produkci)
1. Pro RAG asistenta je vytvořen **Group Managed Service Account** (např. `svc-rag-reader$`), který nemá statické heslo.
2. Na Linux serveru se zprovozní Kerberos klient (`krb5-user`, `libkrb5-dev`).
3. Vygeneruje se `.keytab` soubor pro tento gMSA účet s přísným oprávněním (viz [LINUX_SETUP_GUIDE.md](LINUX_SETUP_GUIDE.md)).
4. Python knihovna `smbprotocol` využije Kerberos lístek pro automatické bezpečné ověření (s explicitním `KRB5CCNAME="FILE:/home/aixima/krb5cc_axima"`) bez nutnosti ukládání jakéhokoliv hesla. Automatické doplňování FQDN k NetBIOS jménům hostitelů.

### Možnost B: Standardní servisní účet (Dev / Staging)
1. Přihlašovací údaje (uživatelské jméno a heslo) jsou předány FastAPI aplikaci bezpečně pomocí **proměnných prostředí** v konfiguraci Systemd služby (nikdy v textovém souboru nebo DB).
2. Inicializace relace se provádí při startu aplikace:
   ```python
   import smbclient
   smbclient.register_session(
       "fileserver.vasedomena.local", 
       username=os.getenv("SMB_USERNAME"), 
       password=os.getenv("SMB_PASSWORD")
   )
   ```

---

## 5. Zajištění souladu s ISO 27001 a GDPR

1. **Žádná trvalá kopie dat na Linuxu:** Dokumenty jsou staženy do `/tmp/rag_ingest_...` pouze po dobu nezbytně nutnou ke zpracování (milisekundy až sekundy) a poté jsou okamžitě zničeny.
2. **Zamezení úniku dat přes lokální uživatele:** Dočasné adresáře v Pythonu se vytvářejí s výchozí maskou `0700` (přístupné pouze pro spouštěcího uživatele `rag-user`). Žádný jiný lokální uživatel na serveru do nich nemůže nahlédnout.
3. **Indexace NTFS ACL za běhu:** Aby nedošlo ke zploštění přístupových práv (RAG by neměl vracet odpovědi z dokumentů, na které uživatel nemá právo), při procházení síťových cest načítá backend také bezpečnostní ACL deskriptory, ukládá je do Qdrantu a dotazy uživatelů za běhu filtruje podle jejich tranzitivního doménového členství.

import time, os, shutil, hashlib, requests, uuid, json
import tempfile
from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams, Distance, PointStruct
from langchain_text_splitters import RecursiveCharacterTextSplitter
import docx, openpyxl, pdfplumber

try:
    import smbclient
    HAS_SMBCLIENT = True
except ImportError:
    HAS_SMBCLIENT = False

# 1. Konfigurace a inicializace
QDRANT_URL = "http://localhost:6333"
OLLAMA_URL = "http://localhost:11434/api/embeddings"
COLLECTION_NAME = "axima_docs"
MANIFEST_FILE = "reconciliation_manifest.json"

qdrant = QdrantClient(QDRANT_URL)

# Vytvoření kolekce s dimenzí 768 (odpovídá nomic-embed-text)
if not qdrant.collection_exists(COLLECTION_NAME):
    qdrant.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(size=1024, distance=Distance.COSINE),
    )
    print(f"[INIT] Vytvořena nová databázová kolekce '{COLLECTION_NAME}'.")

def load_manifest():
    if os.path.exists(MANIFEST_FILE):
        try:
            with open(MANIFEST_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_manifest(manifest):
    try:
        with open(MANIFEST_FILE, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"[ERROR] Nelze uložit manifest: {e}")

def get_file_hash(filepath):
    hasher = hashlib.md5()
    try:
        with open(filepath, 'rb') as afile:
            buf = afile.read()
            hasher.update(buf)
        return hasher.hexdigest()
    except Exception: 
        return None

def extract_text(file_path):
    ext = os.path.splitext(file_path)[1].lower()
    text = ""
    try:
        if ext == '.docx':
            doc = docx.Document(file_path)
            text = "\n".join([p.text for p in doc.paragraphs])
        elif ext == '.xlsx':
            wb = openpyxl.load_workbook(file_path, data_only=True)
            for sheet in wb.worksheets:
                for row in sheet.iter_rows(values_only=True):
                    text += " ".join([str(cell) for cell in row if cell]) + "\n"
        elif ext == '.pdf':
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text: 
                        text += page_text + "\n"
        elif ext in (".txt", ".md", ".csv", ".log", ".ps1", ".html", ".htm", ".xml", ".json", ".ini", ".conf"):
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
    except Exception as e: 
        return f"CHYBA: {e}"
    return text

def get_embedding(text):
    """Zavolá lokální Ollamu pro převod textu na vektor."""
    try:
        response = requests.post(OLLAMA_URL, json={
            "model": "bge-m3",
            "prompt": text
        }, timeout=10)
        if response.status_code == 200:
            return response.json()["embedding"]
    except Exception as e:
        print(f"[ERROR] Chyba získání embeddingu: {e}")
    return None

def _get_fqdn_host(hostname):
    """Doplní FQDN k NetBIOS jménu hostitele, pokud chybí."""
    if "." not in hostname:  # Pokud hostname neobsahuje tečku, předpokládáme NetBIOS jméno
        return f"{hostname}.axinetwork.loc"
    return hostname

def init_smb_session(unc_path):
    """Zajistí registraci SMB relace pro daný server s Kerberos autentizací."""
    if not HAS_SMBCLIENT:
        return False

    norm = unc_path.replace("\\", "/")
    parts = [p for p in norm.split("/") if p]
    if parts:
        host_netbios = parts[0]
        host_fqdn = _get_fqdn_host(host_netbios)
        try:
            os.environ["KRB5CCNAME"] = "FILE:/home/aixima/krb5cc_axima"
            smbclient.register_session(host_fqdn, auth_protocol="negotiate")
            return True
        except Exception as e:
            print(f"[ERROR] Chyba při registraci SMB session pro {host_fqdn}: {e}")
    return False
def get_smb_file_info(unc_path):
    """Vrací mtime a size pro soubor na SMB."""
    try:
        # Normalizujeme UNC cestu pro získání hostitele a doplnění FQDN
        norm_path = unc_path.replace("\\", "/")
        host_netbios = norm_path.lstrip("/").split("/")[0]
        host_fqdn = _get_fqdn_host(host_netbios)
        unc_path_fqdn = unc_path.replace(host_netbios, host_fqdn, 1)

        stat = smbclient.stat(unc_path_fqdn)
        return stat.st_mtime, stat.st_size
    except Exception:
        return None, None

def index_file(local_path, display_name):
    """Rozseká text z lokálního souboru na bloky, vektorizuje a uloží do Qdrantu."""
    content = extract_text(local_path)
    if len(content.strip()) == 0 or content.startswith("CHYBA:"):
        print(f"[WARN] Soubor '{display_name}' nelze přečíst nebo je prázdný.")
        return False

    print(f"[INDEX] Zpracovávám '{display_name}' ({len(content)} znaků)...")
    
    # Rozsekání textu na překrývající se bloky
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    chunks = splitter.split_text(content)
    
    # Obohacení chunků o informaci o zdrojovém souboru
    enriched_chunks = [f"Zdrojový dokument: {display_name}\nObsah:\n{chunk}" for chunk in chunks]

    # Smazání starých vektorů pro tento konkrétní zdroj před novým vložením (prevence duplicit)
    try:
        from qdrant_client.http import models
        qdrant.delete(
            collection_name=COLLECTION_NAME,
            points_selector=models.Filter(
                must=[
                    models.FieldCondition(
                        key="source",
                        match=models.MatchValue(value=display_name)
                    )
                ]
            )
        )
    except Exception as e:
        print(f"[DEBUG] Nepodařilo se promazat staré body: {e}")

    # Vektorizace a uložení
    points = []
    for i, chunk in enumerate(enriched_chunks): # Používáme obohacené chunky
        vector = get_embedding(chunk)
        if vector:
            points.append(PointStruct(
                id=str(uuid.uuid4()),
                vector=vector,
                payload={"source": display_name, "chunk_index": i, "text": chunk}
            ))
    
    if points:
        qdrant.upsert(collection_name=COLLECTION_NAME, points=points)
        print(f"[SUCCESS] Uloženo {len(points)} bloků do Qdrantu pro '{display_name}'.")
        return True
    return False

def process_smb_file(unc_path):
    """Bezpečně stáhne soubor ze síťového disku do TemporaryDirectory a zaindexuje."""
    print(f"[DOWNLOAD] Stahuji ze SMB: {unc_path}")
    # TemporaryDirectory se postará o automatický a bezpečný úklid i při pádu
    with tempfile.TemporaryDirectory(prefix="rag_ingest_") as temp_dir:
        # Normalizujeme UNC cestu pro získání hostitele a doplnění FQDN
        norm_path = unc_path.replace("\\", "/")
        host_netbios = norm_path.lstrip("/").split("/")[0]
        host_fqdn = _get_fqdn_host(host_netbios)
        unc_path_fqdn = unc_path.replace(host_netbios, host_fqdn, 1)

        local_filename = os.path.basename(unc_path_fqdn.replace('\\', '/'))
        tmp_path = os.path.join(temp_dir, local_filename)
        
        try:
            with smbclient.open_file(unc_path_fqdn, "rb") as remote_f, open(tmp_path, "wb") as local_f:
                local_f.write(remote_f.read())
            
            # Indexace staženého lokálního souboru
            return index_file(tmp_path, unc_path_fqdn)
        except Exception as e:
            print(f"[ERROR] Selhalo stažení nebo zpracování souboru {unc_path_fqdn}: {e}")
            return False

def reconciliation_scan():
    """Provede kompletní sken hlídaných složek (lokálních i UNC) a provede synchronizaci."""
    print(f"\n[RECONCILIATION] Spouštím periodický skenovací cyklus: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    manifest = load_manifest()
    new_manifest = {}
    
    # Načtení hlídaných cest (v produkci z SQL Serveru, zde z konfigurace/env)
    # Načtení hlídaných cest z FastAPI
    try:
        response = requests.get("http://localhost:8000/api/monitored_paths") # Předpokládáme, že FastAPI běží na tomto URL
        response.raise_for_status() # Vyvolá HTTPError pro špatné odpovědi (4xx nebo 5xx)
        monitored_paths = response.json()
        print(f"[INFO] Načteno {len(monitored_paths)} monitorovaných cest z FastAPI.")
    except requests.exceptions.ConnectionError:
        print("[ERROR] Nepodařilo se připojit k FastAPI pro získání monitorovaných cest. Používám výchozí cesty z .env.")
        monitored_paths_raw = os.getenv("MONITORED_PATHS", "/data/llm-demo/watchdog/incoming")
        monitored_paths = [p.strip() for p in monitored_paths_raw.split(",") if p.strip()]
    except Exception as e:
        print(f"[ERROR] Chyba při načítání monitorovaných cest z FastAPI: {e}. Používám výchozí cesty z .env.")
        monitored_paths_raw = os.getenv("MONITORED_PATHS", "/data/llm-demo/watchdog/incoming")
        monitored_paths = [p.strip() for p in monitored_paths_raw.split(",") if p.strip()]

    for path_raw in monitored_paths:
        path = path_raw.replace("\\", "/") # Normalizujeme cestu na dopředná lomítka hned na začátku

        if path.startswith("//"):
            # UNC síťová cesta přes user-space SMB
            if not HAS_SMBCLIENT:
                print(f"[WARN] Přeskočeno UNC '{path}': knihovna smbclient není k dispozici.")
                continue
            
            _scan_smb_path(path, collection_name=COLLECTION_NAME, manifest=manifest, new_manifest=new_manifest)
        else:
            _scan_local_path(path, collection_name=COLLECTION_NAME, manifest=manifest, new_manifest=new_manifest)

    # Detekce smazaných souborů a pročištění Qdrantu
    for old_file_key in list(manifest.keys()):
        if old_file_key not in new_manifest:
            print(f"[DELETE] Soubor chybí na disku, odstraňuji jeho vektory z databáze Qdrant: {old_file_key}")
            try:
                from qdrant_client.models import Filter, FieldCondition, MatchValue
                qdrant.delete(
                    collection_name=COLLECTION_NAME,
                    points_selector=Filter(
                        must=[FieldCondition(key="source", match=MatchValue(value=old_file_key))]
                    )
                )
            except Exception as e:
                print(f"[ERROR] Nelze smazat body pro smazaný soubor {old_file_key}: {e}")
                
    save_manifest(new_manifest)
    print("[RECONCILIATION] Skenovací cyklus dokončen.")

def _scan_smb_path(path, collection_name, manifest, new_manifest):
    print(f"[DEBUG] _scan_smb_path zahájeno pro: {path}")

    if not HAS_SMBCLIENT:
        print(f"[WARN] Přeskočeno UNC \'{path}\": knihovna smbclient není k dispozici.")
        return

    try:
        win_path = path.replace("//", "\\\\").replace("/", "\\") # Konverze na zpětná lomítka pro smbclient
        print(f"[DEBUG] Konvertovaná Windows cesta pro smbclient: {win_path}")

        # 1. Extrakce hostitele
        parts = [p for p in path.split("/") if p]
        if not parts:
            print(f"[WARN] Neplatná UNC cesta: {path}")
            return
            
        host_netbios = parts[0]
        
        # 2. Doplnění FQDN (pokud není zadáno)
        if "." not in host_netbios:
            host_fqdn = f"{host_netbios}.axinetwork.loc"
        else:
            host_fqdn = host_netbios
        print(f"[DEBUG] Hostitel FQDN: {host_fqdn}")
        
        # Aktualizujeme win_path s FQDN hostem pro smbclient.walk a další operace
        win_path_fqdn = win_path.replace(host_netbios, host_fqdn, 1)
        print(f"[DEBUG] Konvertovaná FQDN Windows cesta pro smbclient: {win_path_fqdn}")

        # 3. Registrace session
        os.environ["KRB5CCNAME"] = "FILE:/home/aixima/krb5cc_axima"
        smbclient.register_session(host_fqdn, auth_protocol="negotiate")
        print(f"[DEBUG] SMB session registrována pro {host_fqdn}")
        
        # 4. Spuštění walk
        for dirpath, _, filenames in smbclient.walk(win_path_fqdn):
            for filename in filenames:
                print(f"[DEBUG] Nalezen soubor: {filename} v {dirpath}")
                if not filename.lower().endswith((".pdf", ".docx")):
                    print(f"[DEBUG] Soubor {filename} ignorován (nepodporovaná přípona).")
                    continue
                
                full_unc_win = os.path.join(dirpath, filename) # Původní UNC cesta se zpětnými lomítky
                full_unc_norm = full_unc_win.replace("\\", "/") # Normalizovaná cesta pro Qdrant

                mtime, size = get_smb_file_info(full_unc_norm)
                if mtime is None:
                    print(f"[WARN] Nelze získat informace o souboru {full_unc_norm}. Přeskakuji.")
                    continue
                
                file_key = full_unc_norm
                new_manifest[file_key] = {"mtime": mtime, "size": size}
                
                old_info = manifest.get(file_key)
                if not old_info or old_info.get("mtime") != mtime or old_info.get("size") != size:
                    print(f"[INFO] Indexuji nebo aktualizuji: {full_unc_norm}")
                    success = process_smb_file(full_unc_norm)
                    if not success:
                        if old_info:
                            new_manifest[file_key] = old_info
                        else:
                            new_manifest.pop(file_key, None)
    except Exception as e:
        print(f"[ERROR] Selhání uvnitř _scan_smb_path pro cestu {path}: {e}")


def _scan_local_path(path, collection_name, manifest, new_manifest):
    if not os.path.exists(path):
        print(f"[WARN] Lokální cesta neexistuje: {path}")
        return
    
    print(f"[SCAN] Skenuji lokální složku: {path}")
    for root, _, filenames in os.walk(path):
        for filename in filenames:
            if not filename.lower().endswith((".pdf", ".docx")):
                continue
            
            full_local = os.path.join(root, filename).replace("\\", "/")
            try:
                stat = os.stat(full_local)
                mtime, size = stat.st_mtime, stat.st_size
            except Exception:
                continue
            
            file_key = full_local
            new_manifest[file_key] = {"mtime": mtime, "size": size}
            
            old_info = manifest.get(file_key)
            if not old_info or old_info.get("mtime") != mtime or old_info.get("size") != size:
                success = index_file(full_local, full_local)
                if not success:
                    if old_info:
                        new_manifest[file_key] = old_info
                    else:
                        new_manifest.pop(file_key, None)

if __name__ == "__main__":
    print("Periodický asynchronní Reconciliation Ingest Service spuštěn.")
    print("Sleduje lokální i UNC cesty v uživatelském prostoru.")
    
    # Nekonečná smyčka periodického skenování (v produkci spouštěno např. systemd timerem, zde v sleep smyčce)
    # Interval nastaven na 15 minut (900s) pro produkci, pro demo/testovací účely 30 sekund
    INTERVAL = int(os.getenv("RECONCILIATION_INTERVAL_SEC", "30"))
    
    try:
        while True:
            reconciliation_scan()
            time.sleep(INTERVAL)
    except KeyboardInterrupt:
        print("Služba zastavena uživatelem.")

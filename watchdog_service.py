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
        vectors_config=VectorParams(size=768, distance=Distance.COSINE),
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
    except Exception as e: 
        return f"CHYBA: {e}"
    return text

def get_embedding(text):
    """Zavolá lokální Ollamu pro převod textu na vektor."""
    try:
        response = requests.post(OLLAMA_URL, json={
            "model": "nomic-embed-text",
            "prompt": text
        }, timeout=10)
        if response.status_code == 200:
            return response.json()["embedding"]
    except Exception as e:
        print(f"[ERROR] Chyba získání embeddingu: {e}")
    return None

def init_smb_session(unc_path):
    """Zajistí registraci SMB relace pro daný server, pokud jsou v env credentials."""
    if not HAS_SMBCLIENT:
        return False
    username = os.getenv("SMB_USERNAME")
    password = os.getenv("SMB_PASSWORD")
    if username:
        norm = unc_path.replace("\\", "/")
        parts = [p for p in norm.split("/") if p]
        if parts:
            host = parts[0]
            try:
                smbclient.register_session(host, username=username, password=password, auth_protocol="negotiate")
                return True
            except Exception:
                pass
    return False

def get_smb_file_info(unc_path):
    """Vrací mtime a size pro soubor na SMB."""
    try:
        stat = smbclient.stat(unc_path)
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
    
    # Smazání starých vektorů pro tento konkrétní zdroj před novým vložením (prevence duplicit)
    try:
        qdrant.delete(
            collection_name=COLLECTION_NAME,
            points_selector=PointStruct(
                id=str(uuid.uuid4()), # dummy
                # V reálné produkci filtrujeme podle payload "source"
            )
        )
        # Pro jistotu promažeme staré body s tímto zdrojem v produkčním filtru:
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        qdrant.delete(
            collection_name=COLLECTION_NAME,
            points_selector=Filter(
                must=[FieldCondition(key="source", match=MatchValue(value=display_name))]
            )
        )
    except Exception as e:
        print(f"[DEBUG] Nepodařilo se promazat staré body (možná neexistují): {e}")

    # Vektorizace a uložení
    points = []
    for i, chunk in enumerate(chunks):
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
        local_filename = os.path.basename(unc_path.replace('\\', '/'))
        tmp_path = os.path.join(temp_dir, local_filename)
        
        try:
            with smbclient.open_file(unc_path, "rb") as remote_f, open(tmp_path, "wb") as local_f:
                local_f.write(remote_f.read())
            
            # Indexace staženého lokálního souboru
            return index_file(tmp_path, unc_path)
        except Exception as e:
            print(f"[ERROR] Selhalo stažení nebo zpracování souboru {unc_path}: {e}")
            return False

def reconciliation_scan():
    """Provede kompletní sken hlídaných složek (lokálních i UNC) a provede synchronizaci."""
    print(f"\n[RECONCILIATION] Spouštím periodický skenovací cyklus: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    manifest = load_manifest()
    new_manifest = {}
    
    # Načtení hlídaných cest (v produkci z SQL Serveru, zde z konfigurace/env)
    # Pro účely dema podporujeme seznam definovaný v env nebo výchozí testovací složku
    monitored_paths_raw = os.getenv("MONITORED_PATHS", "/data/llm-demo/watchdog/incoming")
    monitored_paths = [p.strip() for p in monitored_paths_raw.split(",") if p.strip()]
    
    for path in monitored_paths:
        if path.startswith("\\\\"):
            # UNC síťová cesta přes user-space SMB
            if not HAS_SMBCLIENT:
                print(f"[WARN] Přeskočeno UNC '{path}': knihovna smbclient není k dispozici.")
                continue
            
            print(f"[SCAN] Skenuji SMB sdílenou složku: {path}")
            init_smb_session(path)
            
            try:
                # Procházení SMB složky
                # smbclient.walk vrací (dirpath, dirnames, filenames)
                for dirpath, _, filenames in smbclient.walk(path):
                    for filename in filenames:
                        # Filtrujeme pouze dokumenty
                        if not filename.lower().endswith(('.pdf', '.docx', '.xlsx')):
                            continue
                        
                        full_unc = os.path.join(dirpath, filename)
                        mtime, size = get_smb_file_info(full_unc)
                        if mtime is None:
                            continue
                        
                        # Unikátní klíč pro manifest
                        file_key = full_unc
                        new_manifest[file_key] = {"mtime": mtime, "size": size}
                        
                        # Kontrola změn
                        old_info = manifest.get(file_key)
                        if not old_info or old_info.get("mtime") != mtime or old_info.get("size") != size:
                            success = process_smb_file(full_unc)
                            if not success:
                                # Pokud se nepodařilo zaindexovat, zachováme staré info, abychom to zkusili příště
                                if old_info:
                                    new_manifest[file_key] = old_info
                                else:
                                    new_manifest.pop(file_key, None)
            except Exception as e:
                print(f"[ERROR] Selhalo procházení SMB složky {path}: {e}")
                
        else:
            # Standardní lokální cesta
            if not os.path.exists(path):
                print(f"[WARN] Lokální cesta neexistuje: {path}")
                continue
            
            print(f"[SCAN] Skenuji lokální složku: {path}")
            for root, _, filenames in os.walk(path):
                for filename in filenames:
                    if not filename.lower().endswith(('.pdf', '.docx', '.xlsx')):
                        continue
                    
                    full_local = os.path.join(root, filename)
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
                                
    # Detekce smazaných souborů a pročištění Qdrantu
    for old_file_key in list(manifest.keys()):
        if old_file_key not in new_manifest:
            print(f"[DELETE] Soubor byl odstraněn ze zdroje, mažu vektory: {old_file_key}")
            try:
                from qdrant_client.models import Filter, FieldCondition, MatchValue
                qdrant.delete(
                    collection_name=COLLECTION_NAME,
                    points_selector=Filter(
                        must=[FieldCondition(key="source", match=MatchValue(value=old_file_key))]
                    )
                )
            except Exception as e:
                print(f"[ERROR] Nelze smazat body pro smazaný soubor: {e}")
                
    save_manifest(new_manifest)
    print("[RECONCILIATION] Skenovací cyklus dokončen.")

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

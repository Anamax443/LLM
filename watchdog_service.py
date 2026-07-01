import time, os, shutil, hashlib, requests, uuid
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import docx, openpyxl, pdfplumber
from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams, Distance, PointStruct
from langchain_text_splitters import RecursiveCharacterTextSplitter

# 1. Konfigurace a inicializace Qdrantu
QDRANT_URL = "http://localhost:6333"
OLLAMA_URL = "http://localhost:11434/api/embeddings"
COLLECTION_NAME = "axima_docs"

qdrant = QdrantClient(QDRANT_URL)

# Vytvoření kolekce s dimenzí 768 (odpovídá nomic-embed-text)
if not qdrant.collection_exists(COLLECTION_NAME):
    qdrant.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(size=768, distance=Distance.COSINE),
    )
    print(f"[INIT] Vytvořena nová databázová kolekce '{COLLECTION_NAME}'.")

def get_file_hash(filepath):
    hasher = hashlib.md5()
    try:
        with open(filepath, 'rb') as afile:
            buf = afile.read()
            hasher.update(buf)
        return hasher.hexdigest()
    except Exception: return None

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
                    if page_text: text += page_text + "\n"
    except Exception as e: return f"CHYBA: {e}"
    return text

def get_embedding(text):
    """Zavolá lokální Ollamu pro převod textu na vektor."""
    response = requests.post(OLLAMA_URL, json={
        "model": "nomic-embed-text",
        "prompt": text
    })
    if response.status_code == 200:
        return response.json()["embedding"]
    return None

class DocumentHandler(FileSystemEventHandler):
    def on_created(self, event):
        if not event.is_directory and not event.src_path.startswith('.'):
            time.sleep(1) # Počkáme na uvolnění ze Samby
            filename = os.path.basename(event.src_path)
            dest_path = os.path.join("/data/llm-demo/watchdog/docs", filename)
            
            # Kontrola duplikátů
            if os.path.exists(dest_path):
                if get_file_hash(event.src_path) == get_file_hash(dest_path):
                    print(f"\n[INFO] '{filename}' je beze změny. Zahazuji duplikát.")
                    try: os.remove(event.src_path)
                    except: pass
                    return
                else:
                    print(f"\n[UPDATE] Nová verze '{filename}'. Aktualizuji.")
                    try: os.remove(dest_path)
                    except: pass
            
            shutil.move(event.src_path, dest_path)
            content = extract_text(dest_path)
            
            if len(content.strip()) == 0 or content.startswith("CHYBA:"):
                print(f"[WARN] Soubor '{filename}' nelze přečíst nebo je prázdný.")
                return

            print(f"\n[INFO] Zpracovávám '{filename}' ({len(content)} znaků)...")
            
            # 2. Rozsekání textu na překrývající se bloky
            splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
            chunks = splitter.split_text(content)
            
            # 3. Vektorizace a uložení do Qdrantu
            points = []
            for i, chunk in enumerate(chunks):
                vector = get_embedding(chunk)
                if vector:
                    # PointStruct je jeden záznam v databázi (vektor + metadata)
                    points.append(PointStruct(
                        id=str(uuid.uuid4()),
                        vector=vector,
                        payload={"source": filename, "chunk_index": i, "text": chunk}
                    ))
            
            if points:
                qdrant.upsert(collection_name=COLLECTION_NAME, points=points)
                print(f"[SUCCESS] Uloženo {len(points)} bloků do vektorové databáze.")

observer = Observer()
observer.schedule(DocumentHandler(), "/data/llm-demo/watchdog/incoming", recursive=False)
observer.start()
print("Watchdog napojený na AI běží. Čekám na soubory ve složce /incoming...")
try:
    while True: time.sleep(1)
except KeyboardInterrupt: observer.stop()
observer.join()

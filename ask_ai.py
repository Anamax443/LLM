import sys, requests
from qdrant_client import QdrantClient

# Konfigurace
QDRANT_URL = "http://localhost:6333"
OLLAMA_URL = "http://localhost:11434/api"
COLLECTION_NAME = "axima_docs"
CHAT_MODEL = "llama3.1"

def get_embedding(text):
    resp = requests.post(f"{OLLAMA_URL}/embeddings", json={"model": "nomic-embed-text", "prompt": text})
    return resp.json().get("embedding")

def ask_ai(question):
    # 1. Převedeme otázku na vektor
    vector = get_embedding(question)
    if not vector:
        print("[ERROR] Nelze vytvořit vektor z otázky.")
        return

    # 2. Najdeme 3 nejrelevantnější bloky v Qdrantu (Ošetřeno pro nové Qdrant API >1.11.x)
    client = QdrantClient(QDRANT_URL)
    search_result = client.query_points(
        collection_name=COLLECTION_NAME,
        query=vector,
        limit=3
    ).points

    # 3. Sestavíme kontext z nalezených dokumentů
    context = "\n\n".join([f"--- Zdroj: {hit.payload['source']} ---\n{hit.payload['text']}" for hit in search_result])
    
    if not context.strip():
        print("Nenašel jsem v databázi žádné relevantní dokumenty k této otázce.")
        return

    print("\n[INFO] Nalezený kontext v dokumentech:")
    print(context)
    print("\n" + "="*50 + "\n")
    print("🤖 AI generuje odpověď...\n")

    # 4. Pošleme kontext a otázku do generativního modelu
    prompt = f"""Jsi IT asistent ve firmě AXIMA. Odpovídej POUZE na základě dodaného kontextu. Pokud odpověď v kontextu není, řekni, že to nevíš.
    
KONTEXT:
{context}

OTÁZKA: {question}
"""
    
    resp = requests.post(f"{OLLAMA_URL}/generate", json={
        "model": CHAT_MODEL,
        "prompt": prompt,
        "stream": False
    })
    
    print(resp.json().get("response", "[CHYBA] AI neodpověděla."))

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Použití: python3 ask_ai.py 'Tvoje otázka?'")
    else:
        ask_ai(sys.argv[1])

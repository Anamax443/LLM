import os
import subprocess
from datetime import datetime, timezone

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import requests
from qdrant_client import QdrantClient

app = FastAPI(title="AXIMA RAG API", version="1.1")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE_DIR, "web")
STARTED_AT = datetime.now(timezone.utc).isoformat()


def _git(*args):
    """Best-effort git dotaz; při chybě vrátí None (např. mimo git checkout)."""
    try:
        return subprocess.check_output(
            ["git", *args], cwd=BASE_DIR, stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return None

QDRANT_URL = "http://localhost:6333"
OLLAMA_URL = "http://localhost:11434/api"
COLLECTION_NAME = "axima_docs"
CHAT_MODEL = "llama3.1"

class QueryRequest(BaseModel):
    question: str

class QueryResponse(BaseModel):
    answer: str
    sources: list[str]

def get_embedding(text):
    resp = requests.post(f"{OLLAMA_URL}/embeddings", json={"model": "nomic-embed-text", "prompt": text})
    if resp.status_code == 200:
        return resp.json().get("embedding")
    return None

@app.post("/ask", response_model=QueryResponse)
def ask_ai_endpoint(req: QueryRequest):
    vector = get_embedding(req.question)
    if not vector:
        raise HTTPException(status_code=500, detail="Nelze komunikovat s modelem.")

    client = QdrantClient(QDRANT_URL)
    try:
        # Zvýšeno na 6 bloků pro zachycení celého kontextu dokumentu
        search_result = client.query_points(
            collection_name=COLLECTION_NAME,
            query=vector,
            limit=6
        ).points
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Chyba databáze: {str(e)}")

    raw_sources = [hit.payload['source'] for hit in search_result]
    unique_sources = list(set(raw_sources))
    
    context = "\n\n".join([f"--- Zdroj: {hit.payload['source']} ---\n{hit.payload['text']}" for hit in search_result])
    
    if not context.strip():
        return QueryResponse(answer="Nenašel jsem v databázi relevantní dokumenty.", sources=[])

    # Detailní a striktní prompt (ochrana proti halucinacím a ztrátě detailů)
    prompt = f"""Jsi senior IT administrátor ve firmě AXIMA. Tvým úkolem je vysvětlit postupy detailně, krok za krokem, aby to zvládl i neznalý člověk. 
Nevynechávej ŽÁDNÉ technické detaily z kontextu (např. IP adresy, názvy programů jako Veeam, cesty). Pokud odpověď v kontextu vůbec není, řekni 'Nevím', přísně zakazuji si cokoliv domýšlet nebo halucinovat.
    
KONTEXT:
{context}

OTÁZKA: {req.question}
"""
    
    resp = requests.post(f"{OLLAMA_URL}/generate", json={
        "model": CHAT_MODEL,
        "prompt": prompt,
        "stream": False
    })
    
    if resp.status_code == 200:
        answer = resp.json().get("response", "[CHYBA] Prázdná odpověď.")
    else:
        raise HTTPException(status_code=500, detail="Model neodpověděl.")

    return QueryResponse(answer=answer, sources=unique_sources)


@app.get("/api/version")
def version():
    """Servisní kontrakt pro patičku UI (AXIMA UI standard)."""
    return {
        "commit": _git("rev-parse", "--short", "HEAD") or "dev",
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "builtAt": _git("log", "-1", "--format=%cI"),
        "startedAt": STARTED_AT,
    }


# Servírování web UI (index.html na kořeni). Mount se přidává poslední,
# takže explicitní API routy (/ask, /api/version) mají přednost.
if os.path.isdir(WEB_DIR):
    @app.get("/")
    def homepage():
        return FileResponse(os.path.join(WEB_DIR, "index.html"))

    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

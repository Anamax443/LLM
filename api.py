import os
import subprocess
from datetime import datetime, timezone

import json
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
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

class VerifyRequest(BaseModel):
    paths: list[str]

def get_embedding(text):
    resp = requests.post(f"{OLLAMA_URL}/embeddings", json={"model": "nomic-embed-text", "prompt": text})
    if resp.status_code == 200:
        return resp.json().get("embedding")
    return None

@app.post("/ask")
def ask_ai_endpoint(req: QueryRequest):
    vector = get_embedding(req.question)
    if not vector:
        raise HTTPException(status_code=500, detail="Nelze komunikovat s modelem.")

    client = QdrantClient(QDRANT_URL)
    try:
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
    
    def event_generator():
        # Poslat nejprve zdroje
        yield f"data: {json.dumps({'sources': unique_sources}, ensure_ascii=False)}\n\n"
        
        if not context.strip():
            yield f"data: {json.dumps({'error': 'Nenašel jsem v databázi relevantní dokumenty.'}, ensure_ascii=False)}\n\n"
            return

        prompt = f"""Jsi senior IT administrátor ve firmě AXIMA. Tvým úkolem je vysvětlit postupy detailně, krok za krokem, aby to zvládl i neznalý člověk. 
Nevynechávej ŽÁDNÉ technické detaily z kontextu (např. IP adresy, názvy programů jako Veeam, cesty). Pokud odpověď v kontextu vůbec není, řekni 'Nevím', přísně zakazuji si cokoliv domýšlet nebo halucinovat.
    
KONTEXT:
{context}

OTÁZKA: {req.question}
"""
        try:
            resp = requests.post(
                f"{OLLAMA_URL}/generate",
                json={
                    "model": CHAT_MODEL,
                    "prompt": prompt,
                    "stream": True
                },
                stream=True
            )
            if resp.status_code == 200:
                for line in resp.iter_lines():
                    if line:
                        chunk = json.loads(line.decode('utf-8'))
                        token = chunk.get("response", "")
                        yield f"data: {json.dumps({'token': token}, ensure_ascii=False)}\n\n"
            else:
                yield f"data: {json.dumps({'error': 'Model neodpověděl.'}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': f'Chyba spojení s modelem: {str(e)}'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/version")
def version():
    """Servisní kontrakt pro patičku UI (AXIMA UI standard)."""
    return {
        "commit": _git("rev-parse", "--short", "HEAD") or "dev",
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "builtAt": _git("log", "-1", "--format=%cI"),
        "startedAt": STARTED_AT,
    }


@app.post("/api/verify")
def verify_paths(req: VerifyRequest):
    """Ověří platnost/dostupnost cest ze strany serveru (os.path.isdir).
    Vrací [{path, ok}] — reálný stav, který smí UI zobrazit jako ověřený."""
    results = []
    for p in req.paths:
        try:
            ok = os.path.isdir(p)
        except Exception:
            ok = False
        results.append({"path": p, "ok": ok})
    return results


# Servírování web UI (index.html na kořeni). Mount se přidává poslední,
# takže explicitní API routy (/ask, /api/version) mají přednost.
if os.path.isdir(WEB_DIR):
    @app.get("/")
    def homepage():
        return FileResponse(os.path.join(WEB_DIR, "index.html"))

    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

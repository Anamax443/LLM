from qdrant_client import QdrantClient

QDRANT_URL = "http://localhost:6333"
COLLECTION_NAME = "axima_docs"

try:
    client = QdrantClient(QDRANT_URL)
    client.delete_collection(collection_name=COLLECTION_NAME)
    print(f"[OK] Kolekce \'{COLLECTION_NAME}\' byla úspěšně smazána z Qdrantu.")
    print("Při dalším spuštění watchdog_service.py se celá databáze vytvoří znovu načisto s novou strukturou.")
except Exception as e:
    print(f"[CHYBA] Nepodařilo se smazat kolekci: {e}")

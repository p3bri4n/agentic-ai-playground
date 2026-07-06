"""
Context Manager : retrieval (RAG) et mémoire long-terme, stockés dans Qdrant
(deux collections distinctes : "documents" et "memory").

NOTE : ce squelette utilise sentence-transformers pour les embeddings (modèle
téléchargé depuis Hugging Face au premier démarrage -> accès réseau requis).
Remplacer par un modèle local si le déploiement doit être 100% air-gapped.
En environnement de test, EMBEDDING_MODEL=fake bascule sur un embedder
déterministe sans dépendance réseau ni sur sentence-transformers (voir
tests/conftest.py).

Les briques LlamaIndex / Mem0 / LLMLingua / reranker mentionnées dans
l'architecture peuvent se greffer ici : LlamaIndex pour le chunking/ingestion
avancée, Mem0 pour une mémoire structurée par utilisateur, LLMLingua pour
compresser le contexte avant de l'envoyer au LLM, un cross-encoder pour
reranker les résultats avant de les retourner à l'agent.
"""

import os
import time
import uuid

from fastapi import FastAPI
from pydantic import BaseModel
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

QDRANT_URL = os.environ.get("QDRANT_URL", "http://qdrant:6333")
EMBEDDING_MODEL_NAME = os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

class _DeterministicFakeEmbedder:
    """
    Embedder sans dépendance réseau, activé via EMBEDDING_MODEL=fake.
    Utilisé uniquement par la suite de tests : il ne produit aucun embedding
    sémantiquement valide, seulement un vecteur déterministe basé sur un hash
    du texte, suffisant pour exercer la logique Qdrant (upsert/query) sans
    télécharger de modèle depuis Hugging Face.
    """

    def __init__(self, dim: int = 384):
        self._dim = dim

    def get_sentence_embedding_dimension(self) -> int:
        return self._dim

    def encode(self, text: str):
        import hashlib
        import numpy as np

        digest = hashlib.sha256(text.encode("utf-8")).digest()
        repeated = (digest * (self._dim // len(digest) + 1))[: self._dim]
        return np.array([b / 255.0 for b in repeated])


app = FastAPI(title="Context Manager")

# ":memory:" permet de faire tourner les tests sans instance Qdrant réelle ;
# en production, QDRANT_URL pointe toujours vers le conteneur qdrant du compose.
qdrant = QdrantClient(location=":memory:") if QDRANT_URL == ":memory:" else QdrantClient(url=QDRANT_URL)

def _build_embedder():
    if EMBEDDING_MODEL_NAME == "fake":
        return _DeterministicFakeEmbedder()
    # importé ici seulement : évite de dépendre de sentence-transformers/torch
    # quand EMBEDDING_MODEL=fake (mode test, cf. tests/conftest.py)
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(EMBEDDING_MODEL_NAME)


embedder = _build_embedder()
VECTOR_SIZE = embedder.get_sentence_embedding_dimension()


def _ensure_collections(max_retries: int = 10, delay_seconds: float = 3.0):
    """
    Attend que Qdrant soit joignable avant de créer les collections.
    `depends_on` dans docker-compose garantit seulement que le CONTENEUR Qdrant
    a démarré, pas qu'il accepte déjà des connexions : sans ce retry, une
    course au démarrage fait planter ce service au premier `docker compose up`.
    """
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            for collection in ("documents", "memory"):
                if not qdrant.collection_exists(collection):
                    qdrant.create_collection(
                        collection_name=collection,
                        vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
                    )
            return
        except Exception as exc:  # noqa: BLE001 - on veut retenter sur toute erreur réseau
            last_error = exc
            time.sleep(delay_seconds)
    raise RuntimeError(f"Impossible de joindre Qdrant après {max_retries} tentatives") from last_error


_ensure_collections()


class RetrieveRequest(BaseModel):
    query: str
    top_k: int = 5
    collection: str = "documents"


class IngestRequest(BaseModel):
    text: str
    metadata: dict = {}
    collection: str = "documents"


class RememberRequest(BaseModel):
    text: str
    user_id: str = "default"


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/retrieve")
async def retrieve(request: RetrieveRequest):
    vector = embedder.encode(request.query).tolist()
    hits = qdrant.query_points(
        collection_name=request.collection, query=vector, limit=request.top_k
    ).points
    return {"results": [hit.payload.get("text", "") for hit in hits]}


@app.post("/ingest")
async def ingest(request: IngestRequest):
    vector = embedder.encode(request.text).tolist()
    point_id = str(uuid.uuid4())
    qdrant.upsert(
        collection_name=request.collection,
        points=[
            PointStruct(
                id=point_id,
                vector=vector,
                payload={"text": request.text, **request.metadata},
            )
        ],
    )
    return {"id": point_id}


@app.post("/remember")
async def remember(request: RememberRequest):
    """Stocke un fait de mémoire long-terme lié à un utilisateur."""
    vector = embedder.encode(request.text).tolist()
    point_id = str(uuid.uuid4())
    qdrant.upsert(
        collection_name="memory",
        points=[
            PointStruct(
                id=point_id,
                vector=vector,
                payload={"text": request.text, "user_id": request.user_id},
            )
        ],
    )
    return {"id": point_id}

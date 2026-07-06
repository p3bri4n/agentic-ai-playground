import os

# Doit être défini AVANT le premier import de app.main, car le module crée
# son client Qdrant et son embedder au chargement.
os.environ["QDRANT_URL"] = ":memory:"
os.environ["EMBEDDING_MODEL"] = "fake"

import os

# Doit être défini AVANT le premier import de app.main/app.ocr_engine, car
# get_engine() choisit FakeOCREngine (sans dépendance à paddleocr/
# paddlepaddle) dès l'import du module — même principe que EMBEDDING_MODEL=fake
# côté context-manager (voir services/context-manager/tests/conftest.py).
os.environ["OCR_ENGINE"] = "fake"

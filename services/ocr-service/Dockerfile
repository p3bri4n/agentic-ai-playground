FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Télécharge les modèles PaddleOCR (détection + reconnaissance, use_angle_cls
# désactivé côté app/ocr_engine.py) AU BUILD plutôt qu'au premier appel :
# évite un accès réseau et plusieurs secondes de latence sur le premier
# find_text/read_screen en production. OCR_LANGS repris ici (même défaut
# "fr" que app/ocr_engine.py) pour builder les modèles réellement utilisés.
ARG OCR_LANGS=fr
RUN python3 -c "from paddleocr import PaddleOCR; PaddleOCR(use_angle_cls=False, lang='${OCR_LANGS}', show_log=False)"

COPY app/ ./app

EXPOSE 8004

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8004"]

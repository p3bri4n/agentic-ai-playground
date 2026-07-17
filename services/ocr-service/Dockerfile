FROM python:3.12-slim

WORKDIR /app

# Libs système absentes de python:3.12-slim, requises dès l'IMPORT (pas
# seulement à l'exécution) par la chaîne paddlepaddle/paddleocr/opencv — même
# classe de bug que celui déjà documenté pour llama-server (README, tableau
# des bugs) : une lib manquante dans une image *-slim, détectée seulement en
# exécutant réellement le build.
#   - libgomp1 (OpenMP) : "ImportError: libgomp.so.1: cannot open shared
#     object file" sans lui.
#   - libgl1 + libglib2.0-0 : requis par le binding natif cv2 (opencv-python,
#     dépendance transitive de paddleocr) : "ImportError: libGL.so.1"/
#     "libgthread-2.0.so.0: cannot open shared object file" sans eux.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# paddlepaddle==2.6.2 embarque sa PROPRE copie de zlib dans libpaddle.so, avec
# des symboles globaux (inflateInit2_/inflateReset2 non isolés) qui entrent
# en collision avec libz.so.1 système dès qu'un AUTRE consommateur de zlib
# est chargé dans le même process — ici Cython, importé en cascade par
# `paddle.utils.cpp_extension` (lui-même déclenché par la simple présence de
# `setuptools`, requis par paddleocr — voir plus bas). Confirmé par
# backtrace gdb : le crash (glibc "double free or corruption"/
# "munmap_chunk(): invalid pointer", symptôme différent à chaque run selon
# l'ASLR — signature classique d'une corruption de tas, pas d'une simple
# dépendance manquante) survient précisément dans inflateReset2 de
# libpaddle.so, appelé via le module `zlib` de la stdlib Python utilisé par
# Cython. LD_PRELOAD force la résolution des symboles zlib vers la bonne
# libz.so.1 système en priorité, quel que soit l'ordre de chargement des
# librairies Python — contournement nécessaire aussi bien au build
# (RUN plus bas) qu'à l'exécution (CMD tout en bas, PaddleOCR importé
# paresseusement par app/ocr_engine.py).
ENV LD_PRELOAD=/lib/x86_64-linux-gnu/libz.so.1

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

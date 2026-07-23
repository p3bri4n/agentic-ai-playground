# Couche minimale au-dessus de l'image officielle TabbyAPI, épinglée par
# digest (voir RESULTS.md pour le triplet de versions exllamav3/torch/
# tabbyAPI constaté). Nécessaire : l'image officielle contient gcc mais PAS
# les en-têtes de développement Python (python3-dev), requis par la
# compilation JIT Triton du module gated_delta_net (attention hybride/SSM de
# Qwen3.6) au premier chargement du modèle — sans ce correctif, le
# chargement échoue systématiquement avec
# "fatal error: Python.h: No such file or directory".
FROM ghcr.io/theroyallab/tabbyapi@sha256:cbceb3032963ab7ada80c76649956b01f54e9e0b04a050fb3396c95950c52b03

RUN apt-get update && apt-get install -y --no-install-recommends python3-dev \
    && rm -rf /var/lib/apt/lists/*

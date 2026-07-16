#!/bin/sh
# Vérifie la présence du modèle et du projecteur multimodal AVANT de lancer
# llama-server : ce service ne télécharge jamais de poids lui-même (contraste
# avec Ollama, qui peut `pull` à la demande) — un modèle absent doit échouer
# vite avec un message clair plutôt que la longue trace d'erreur générique de
# llama-server sur un chemin introuvable.
set -eu

MODEL_PATH="/models/${LLAMA_MODEL_FILE:-Qwen3.6-35B-A3B-Q5_K_M.gguf}"
MMPROJ_PATH="/models/${LLAMA_MMPROJ_FILE:-mmproj-F16.gguf}"

if [ ! -f "$MODEL_PATH" ]; then
    echo "ERREUR llama-server : modèle introuvable : $MODEL_PATH" >&2
    echo "Ce service ne télécharge jamais de modèle. Placez le fichier .gguf attendu dans ./models (ou ajustez LLAMA_MODEL_FILE dans .env)." >&2
    exit 1
fi

if [ ! -f "$MMPROJ_PATH" ]; then
    echo "ERREUR llama-server : projecteur multimodal introuvable : $MMPROJ_PATH" >&2
    echo "Requis pour l'entrée image (screen_shot GhostDesk). Placez le fichier mmproj attendu dans ./models (ou ajustez LLAMA_MMPROJ_FILE dans .env)." >&2
    exit 1
fi

exec /app/llama-server \
    --model "$MODEL_PATH" \
    --mmproj "$MMPROJ_PATH" \
    --tensor-split 0.55,0.45 \
    --ctx-size 32768 \
    --cache-type-k q8_0 \
    --cache-type-v turbo3 \
    --flash-attn on \
    --jinja \
    --parallel 1 \
    --host 0.0.0.0 \
    --port 8000 \
    --alias agent-llm \
    "$@"

#!/usr/bin/env bash
# Recrée l'alias Ollama "agent-llm" à partir d'un modèle source, en appliquant
# les paramètres de sampling validés pour ce backend (voir README, tableau
# des bugs — modèles fortement quantisés type IQ2_M) : des pénalités
# anti-répétition trop agressives (repeat_penalty/repeat_last_n/
# presence_penalty élevés) forcent le modèle à piocher un vocabulaire de plus
# en plus rare et le font dériver vers de l'incohérence. Ces valeurs vivent
# dans le store Ollama du conteneur (volume ollama-data), donc PAS dans ce
# repo par défaut : un `ollama pull` + `ollama cp` refait à la main perd ce
# réglage. Ce script fige la recette pour la reproduire à l'identique après
# tout changement de modèle source.
#
# Usage :
#   scripts/rebuild-agent-llm.sh <modèle-source-ollama>
#   scripts/rebuild-agent-llm.sh qwen3.6:35b
set -euo pipefail

SOURCE="${1:?Usage: $0 <modèle-source-ollama> (ex. qwen3.6:35b)}"
CONTAINER="${OLLAMA_CONTAINER:-ollama}"

docker exec -i "$CONTAINER" sh -c "cat > /tmp/agent-llm.Modelfile" <<EOF
FROM ${SOURCE}
PARAMETER min_p 0
PARAMETER presence_penalty 0
PARAMETER repeat_last_n 256
PARAMETER repeat_penalty 1.05
PARAMETER temperature 1
PARAMETER top_k 20
PARAMETER top_p 0.95
EOF

docker exec -i "$CONTAINER" ollama create agent-llm -f /tmp/agent-llm.Modelfile

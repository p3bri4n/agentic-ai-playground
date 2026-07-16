# Build de llama-server depuis le fork YV17labs/llama-cpp-turboquant-webp
# (branche feature/turboquant-webp) plutôt que llama.cpp upstream : ce fork
# ajoute le décodage WebP natif (screen_shot GhostDesk transmis sans
# reconversion PNG côté langgraph-agent, voir IMAGE_FORMAT_PASSTHROUGH,
# services/langgraph-agent/app/graph.py) et le type de cache KV "turbo3"
# (compression propriétaire à ce fork, absente de llama.cpp upstream — d'où
# --cache-type-v turbo3 dans la commande de démarrage, entrypoint.sh).
#
# Buildé et exécuté réellement (docker compose build llama-server, puis
# `llama-server --list-devices` avec --gpus all) sur une machine à 2 GPU
# (RTX 4070 Ti SUPER, Ada / RTX 5060 Ti, Blackwell) — les deux détectées
# correctement par le binaire final. Ce qui a été confirmé en conditions
# réelles (voir aussi le tableau des bugs du README) :
#   - la cible CMake s'appelle bien `llama-server` (tools/server/CMakeLists.txt)
#   - `--cache-type-v turbo3` est un flag réel de ce fork, explicitement
#     documenté comme "recommended default" avec `--cache-type-k q8_0`
#   - le décodage WebP passe par mtmd (tools/mtmd/mtmd-helper.cpp,
#     `#include <webp/decode.h>`), activé par défaut (MTMD_WEBP=ON) mais
#     nécessite libwebp au build (`find_package(WebP)`/pkg-config) ET au
#     runtime (libwebp-dev/libwebp7 ci-dessous)
#   - Blackwell (sm_120, ex. RTX 5060 Ti) nécessite CUDA >= 12.8 pour
#     compiler — d'où la base 12.8.1 plutôt que 12.4
#   - GGML_NATIVE=OFF + CMAKE_CUDA_ARCHITECTURES explicite ("89-real;120a-real",
#     Ada + Blackwell) : la détection "native" de ggml interroge le GPU au
#     moment du `cmake configure`, absent pendant un `docker build` standard
#     (pas de --gpus sur les étapes RUN) — sans ce réglage, la configuration
#     retomberait sur une détection ratée ou une liste d'architectures par
#     défaut ne couvrant pas forcément Blackwell. Ajuster cette liste si le
#     matériel cible diffère.
# Non vérifié : inférence réelle avec le modèle cible (Qwen3.6-35B-A3B
# Q5_K_M + mmproj) — poids non disponibles dans l'environnement qui a écrit
# ce commentaire, voir README section Backend d'inférence.
FROM nvidia/cuda:12.8.1-devel-ubuntu22.04 AS build

RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        cmake \
        build-essential \
        pkg-config \
        libcurl4-openssl-dev \
        libwebp-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
RUN git clone --branch feature/turboquant-webp --depth 1 \
        https://github.com/YV17labs/llama-cpp-turboquant-webp.git .

# GGML_NATIVE=OFF + CMAKE_CUDA_ARCHITECTURES explicite : la détection
# "native" de ggml interroge le GPU au moment du `cmake configure`, absent
# pendant un `docker build` standard (pas de --gpus sur les étapes RUN) —
# sans ce réglage, la configuration retomberait sur une détection ratée ou
# une liste d'architectures par défaut ne couvrant pas forcément Blackwell.
# GGML_CUDA_NO_VMM=ON : ggml active par défaut l'allocateur "CUDA Virtual
# Memory Management" (pooling KV cache), qui lie ggml-cuda contre le driver
# CUDA réel (libcuda.so, target CMake CUDA::cuda_driver) — absent d'une
# image *-devel au moment du BUILD (fourni seulement au runtime par le
# driver hôte via nvidia-container-toolkit), d'où un échec de link
# ("undefined reference to cuMemCreate/cuDeviceGet/...") confirmé en
# buildant réellement ce Dockerfile sans cette option. Désactiver VMM ne
# touche ni --flash-attn ni --cache-type-v turbo3, seulement l'allocateur
# de pooling mémoire (peu pertinent ici avec --parallel 1, une seule
# séquence à la fois).
# LLAMA_CURL=ON conservé au cas où le fork l'utilise encore pour le
# téléchargement de modèles à la volée — non utilisé ici (modèle monté
# depuis ./models, jamais téléchargé par ce service, voir entrypoint.sh)
# mais requis pour que la configuration CMake aboutisse selon les versions.
RUN cmake -B build \
        -DGGML_CUDA=ON \
        -DGGML_NATIVE=OFF \
        -DGGML_CUDA_NO_VMM=ON \
        -DCMAKE_CUDA_ARCHITECTURES="89-real;120a-real" \
        -DLLAMA_CURL=ON \
        -DCMAKE_BUILD_TYPE=Release \
    && cmake --build build --target llama-server --config Release -j"$(nproc)"

FROM nvidia/cuda:12.8.1-runtime-ubuntu22.04

RUN apt-get update && apt-get install -y --no-install-recommends \
        libcurl4 \
        libwebp7 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Tout /src/build/bin/, pas seulement l'exécutable llama-server : le build
# CMake de ce fork produit les bibliothèques partagées (libggml-base,
# libggml-cuda, libggml-cpu, libllama, libllama-common, libmtmd) DANS LE
# MÊME DOSSIER que les exécutables. Confirmé en inspectant le binaire
# buildé : `ldd llama-server` échouait sur ces bibliothèques quand seul le
# binaire était copié ("cannot open shared object file"). Le binaire n'a
# PAS de RPATH/RUNPATH embarqué (vérifié via `readelf -d`, contrairement à
# l'hypothèse initiale d'une résolution $ORIGIN) : LD_LIBRARY_PATH est donc
# nécessaire pour que le loader dynamique trouve ces .so au même endroit.
COPY --from=build /src/build/bin/ /app/
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh /app/llama-server

ENV LD_LIBRARY_PATH=/app

ENTRYPOINT ["/app/entrypoint.sh"]

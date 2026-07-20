# agentic-ai-playground

![Logo](logo-agentic-ai-playground.jpg)

Stack Docker Compose pour un agent IA local : Open WebUI → LangGraph Agent →
(Skill Manager / Context Manager / MCP Client) → llama-server.

## Démarrage rapide

```bash
cp .env.example .env
# éditer .env : WORKSPACE_HOST_PATH doit être le chemin ABSOLU de ./workspace sur l'hôte
# (requis car mcp-client monte ce chemin dans des conteneurs qu'il spawn lui-même)
# éditer .env : LLAMA_MODEL_FILE/LLAMA_MMPROJ_FILE doivent correspondre aux
# .gguf réellement présents dans ./models (voir section Backend d'inférence
# ci-dessous — jamais téléchargés automatiquement)

docker pull mcp/filesystem:latest
docker pull mcp/git:latest
docker pull mcp/playwright:latest
docker compose --profile build-only build mcp-terminal-build   # construit l'image locale mcp-terminal:local

docker compose up -d
```

Interface accessible sur http://localhost:3000 (Open WebUI).

## Arborescence

```
docker-compose.yml
.env.example
requirements-test.txt   dépendances de test communes (pytest, respx)
services/
  langgraph-agent/   API compatible OpenAI + graphe LangGraph
    app/
    tests/
  skill-manager/      liste/sélectionne les skills (./skills)
    app/
    tests/
  context-manager/    RAG + mémoire (Qdrant + sentence-transformers)
    app/
    tests/
  mcp-client/          spawn les serveurs MCP à la demande (docker.sock)
    app/
    tests/
  mcp-terminal/        serveur MCP "terminal" maison, liste blanche stricte
    server.py
    tests/
  ghostdesk/           image officielle YV17labs, bureau virtuel piloté par l'agent
                       (pas de code applicatif ici : service docker-compose à part,
                       mcp-client s'y connecte en Streamable HTTP)
  llama-server/        build du fork llama.cpp servant le modèle (voir
                       section Backend d'inférence) — pas de code Python ici,
                       Dockerfile + entrypoint.sh de vérification du modèle
  ocr-service/         OCR d'appoint pour le grounding du VLM (PaddleOCR CPU,
                       find_text/read_screen), serveur MCP HTTP persistant
                       comme ghostdesk (voir section OCR d'appoint)
    app/
    tests/
  dashboard/           Cockpit d'observabilité local : page unique + API
                       d'agrégation best-effort (llama-server, langgraph-agent,
                       nvidia-smi) — voir section Observabilité
    app/
      static/          page HTML/JS vanille servie telle quelle (pas de build)
    tests/
skills/     à remplir (un sous-dossier par skill, avec un SKILL.md)
workspace/  partagé avec les serveurs MCP filesystem/git/terminal, ainsi
            qu'avec langgraph-agent pour le journal d'audit (.audit/, voir
            section Supervision humaine)
models/     poids (.gguf) du modèle et du projecteur multimodal servis par
            llama-server — jamais téléchargés automatiquement, voir section
            Backend d'inférence
```

## Backend d'inférence

Le backend par défaut est `llama-server`, buildé depuis le fork
[YV17labs/llama-cpp-turboquant-webp](services/llama-server/Dockerfile)
(branche `feature/turboquant-webp`) plutôt que llama.cpp upstream — ce fork
ajoute le décodage WebP natif (voir Conversion d'images plus bas) et un
type de cache KV `turbo3` (compression propriétaire à ce fork).

Le build, le démarrage ET l'inférence ont été exécutés réellement (GPU +
accès réseau disponibles), modèle cible chargé (`Qwen3.6-35B-A3B` quant
`Q5_K_M` + `mmproj-F16`, réparti sur les deux GPU via `--tensor-split`)
et une conversation complète menée de bout en bout à travers toute la
stack (`langgraph-agent` → `llama-server`, streaming SSE, balises
`<think>` correctement ouvertes/fermées, réponse finale correcte) — cinq
bugs ont été trouvés et corrigés dans ce processus (packaging du build,
CLI du serveur, format des deltas de raisonnement), voir le tableau des
bugs plus bas.

Commande de démarrage (`services/llama-server/entrypoint.sh`) :
`--tensor-split 0.55,0.45 --ctx-size 32768 --cache-type-k q8_0
--cache-type-v turbo3 --flash-attn --jinja --mmproj <mmproj> --parallel 1`.

Modèle cible : **Qwen3.6-35B-A3B, quantisation Q5_K_M**, plus un projecteur
multimodal (`--mmproj`) pour l'entrée image (screen_shot GhostDesk). Fichiers
attendus dans `./models` (ou `MODELS_HOST_PATH`), noms configurables via
`LLAMA_MODEL_FILE`/`LLAMA_MMPROJ_FILE` (défauts :
`Qwen3.6-35B-A3B-Q5_K_M.gguf`/`mmproj-F16.gguf`) — **jamais téléchargés
automatiquement** : `entrypoint.sh` vérifie leur présence au démarrage du
conteneur et échoue avec un message clair (sur stderr, avant même de lancer
`llama-server`) plutôt que de laisser échouer `llama-server` lui-même avec
une erreur générique de chemin introuvable.

vLLM a été retiré du projet : il attend un format de poids HuggingFace natif
incompatible avec les `.gguf`, et n'apportait rien que llama.cpp ne couvre
pas ici. Ollama reste disponible comme backend alternatif dans
`docker-compose.yml` (llama.cpp sous le capot lui aussi, voir ce fichier
pour l'activer), notamment pour un modèle non couvert par le fork
turboquant-webp ; penser alors à repasser `IMAGE_FORMAT_PASSTHROUGH=png`
(voir Conversion d'images plus bas), le décodeur mtmd d'Ollama échouant
explicitement sur le WebP.

## Images et thinking adaptatif (`services/langgraph-agent/app/graph.py`)

**Conversion d'images** (`IMAGE_FORMAT_PASSTHROUGH`, variable d'env, défaut
absent = conversion PNG) : `_to_png_data_uri` reste le chemin par défaut —
chaque résultat image d'outil (`screen_shot` GhostDesk, WebP natif) est
systématiquement reconverti en PNG avant transmission au LLM, seul format
supporté par le décodeur mtmd d'Ollama. `IMAGE_FORMAT_PASSTHROUGH=webp`
bascule sur `_to_image_data_uri`, qui transmet le WebP brut tel quel (data
URI directe, aucun passage par Pillow) : à activer avec le backend
`llama-server` par défaut, dont le fork llama.cpp décode le WebP nativement
— gain CPU non négligeable sur une boucle capture/clic répétée.

**Rétention d'images** (`MAX_IMAGES_IN_CONTEXT`, variable d'env, défaut `1`) :
seules les `MAX_IMAGES_IN_CONTEXT` dernières captures d'écran restent en
blocs `image_url` multimodaux dans l'historique soumis au LLM à chaque
appel ; les précédentes sont remplacées par le texte indicatif
`[screenshot antérieure supprimée]` (`_apply_image_retention`). **Ne touche
jamais au checkpointer** : ce filtrage ne s'applique qu'à la liste de
messages construite juste avant `bound_llm.astream()`, jamais à
`state["messages"]` lui-même — l'historique complet, avec toutes les images
d'origine, reste intact et rejouable (ex. si `MAX_IMAGES_IN_CONTEXT` change
d'une conversation à l'autre). Motivation : une boucle capture/clic
GhostDesk répétée peut accumuler de nombreuses captures dans l'historique,
chacune coûteuse en tokens visuels, pour un intérêt quasi nul au-delà de la
plus récente (seule reflète l'état actuel de l'écran).

**Thinking adaptatif** (`ADAPTIVE_THINKING`, variable d'env, défaut `false`) :
Qwen3.6 raisonne par défaut sur chaque tour (balises de pensée étendue),
coûteux en latence pour une boucle perception-action rapide où chaque tour
n'a qu'à décider "où cliquer ensuite". Si activé, `_apply_adaptive_thinking`
ajoute un system prompt transitoire `/no_think` (lui aussi jamais persisté
dans l'état du graphe, même principe que la rétention d'images ci-dessus)
quand **tous** les tool_calls du tour précédent étaient auto-approuvés
(même politique par tiers que `has_tool_calls`, grants de session inclus —
voir `approval_policy.py`). Pas d'injection sur le tout premier tour d'une
tâche (aucun tool_calls précédent à évaluer) ni dès qu'un outil sensible
était en jeu dans ce tour précédent : le raisonnement complet y garde toute
sa valeur.

## OCR d'appoint (`services/ocr-service`)

**Pourquoi** : le VLM servi par défaut (Qwen3.6 MoE) raisonne bien mais
localise mal — son grounding visuel (viser le bon pixel d'un élément à
l'écran) reste imprécis, sans OCR ni détection d'éléments UI dédiée (voir
Limites connues assumées plus bas). `ocr-service` compense en donnant à
l'agent des coordonnées de texte EXACTES via deux tools MCP : `find_text
(query, fuzzy=true)` (correspondances triées par confiance, liste vide si
aucune — jamais d'erreur) et `read_screen()` (tout le texte détecté,
plafonné à 80 éléments). Consigne de grounding injectée au system prompt de
langgraph-agent (`GROUNDING_DIRECTIVE`, `app/graph.py`) : privilégier
`find_text` à l'estimation visuelle pour cliquer sur du texte, réserver
cette dernière aux éléments sans texte (icônes).

Serveur MCP HTTP persistant (Streamable HTTP, bearer `OCR_AUTH_TOKEN`), sur
le même modèle que `desktop`/GhostDesk côté `mcp-client` — pas un conteneur
spawné à la demande. `find_text`/`read_screen` sont tier lecture
(`approval_policy.py`) : lecture pure, aucun effet de bord, auto-approuvés
et silencieux.

**Capture** : `ocr-service` se connecte lui-même en Streamable HTTP à
GhostDesk (réseau interne `agent-net`, bearer `GHOSTDESK_AUTH_TOKEN`,
`format="png"` explicite — aucune dépendance au décodage WebP natif de
llama-server, non pertinent ici) pour appeler `screen_shot` à chaque
`find_text`/`read_screen`. Aucune image ne transite par `mcp-client` ni par
le LLM pour ce flux, entièrement interne à `ocr-service`.

**Mapping de coordonnées — source classique de clics décalés** : PaddleOCR
travaille en pixels réels de la capture, alors que `mouse_click` côté
GhostDesk attend le repère normalisé 0-1000 (même repère que
`GHOSTDESK_MODEL_SPACE` côté `mcp-client`, voir Supervision humaine plus
bas). `ocr-service` convertit donc systématiquement ses coordonnées avant de
répondre (`x_norm = round(x_px * 1000 / largeur_image)`, voir
`app/coords.py`) — sans cette conversion, les coordonnées renvoyées par
`find_text` seraient en pixels alors que le modèle (et GhostDesk) les
interprètent en 0-1000, garantissant des clics à côté de leur cible.
`OCR_COORD_SPACE` (défaut `"1000"`) désactive cette conversion (`"pixels"`)
si l'appelant travaille lui-même en pixels.

**PaddleOCR en CPU uniquement** : les deux GPU sont déjà saturés par
llama-server (voir Backend d'inférence). Langue `fr` (configurable via
`OCR_LANGS`) : PaddleOCR regroupe le français et l'anglais sous un seul
modèle de reconnaissance (alphabet latin partagé), inutile de faire tourner
deux passes OCR séparées pour ce projet. Modèles téléchargés **au build** de
l'image Docker (`ARG OCR_LANGS`, voir `services/ocr-service/Dockerfile`),
jamais au premier appel — évite un accès réseau et plusieurs secondes de
latence en production.

Hors périmètre explicite (itération future) : détection d'icônes/éléments UI
sans texte (type OmniParser), annotation Set-of-Marks des screenshots, OCR
GPU, cache des résultats entre appels.

## Observabilité (`services/dashboard`)

Cockpit web local en une page (http://localhost:8090 par défaut,
`DASHBOARD_PORT`) : métriques d'inférence llama-server (débit decode/prefill
en tok/s, contexte occupé par slot), composition détaillée du contexte
construit par langgraph-agent (system prompt, skills, schéma d'outils,
historique, images — voir `POST /context` plus bas) et VRAM des GPU.

**Architecture** : `GET /api/snapshot` agrège en parallèle, chaque source en
best-effort (une source en panne renvoie sa section à `null`, jamais une 500
globale, statut 200 systématique — le dashboard poll ce endpoint toutes les
2s) : `llama-server` (`/metrics`, format Prometheus parsé par un parser
minimal maison, `app/prometheus.py` ; `/slots`), `langgraph-agent`
(`/threads/recent` puis `POST /context` pour le thread résolu) et
`nvidia-smi` en subprocess (VRAM, `app/gpu.py`). La page (`GET /`, HTML/JS
vanille, aucune dépendance externe) ne parle jamais directement à
llama-server/langgraph-agent : seuls Open WebUI et le dashboard ont un port
publié sur l'hôte, tout le reste n'est joignable que via le réseau interne
`agent-net` — d'où l'agrégation côté backend du dashboard plutôt que des
appels depuis le navigateur.

**`POST /context` (langgraph-agent, `app/graph.py:describe_context`)** :
décompose le contexte persisté d'un thread en blocs approximatifs
(`system`/`skills`/`tools_schema`/`history_text`/`images`/`pending`), chacun
avec un compte de tokens estimé (`estimate_tokens`, ~3.5 caractères/token —
pas un tokenizer exact, volontairement hors périmètre, voir plus bas) et un
forfait fixe par image (`IMAGE_TOKEN_ESTIMATE`, défaut `1500`, un compte
exact dépendrait du tokenizer visuel du modèle servi). Le schéma d'outils est
mesuré depuis le cache déjà rempli par `_get_bound_llm` (jamais recalculé :
`/context` reste strictement lecture seule, comme `/pending`). Thread inconnu
du checkpointer -> 200 avec des blocs vides plutôt qu'une 404, pour ne pas
transformer le polling continu du dashboard en bruit d'erreurs côté client.

**Sélection de thread (`GET /threads/recent`)** : langgraph-agent n'a jamais
d'identifiant de conversation stable côté Open WebUI (voir plus bas,
`_derive_thread_id`) ; un registre en mémoire process, jamais persisté
(cohérent avec le checkpointer `MemorySaver` lui-même en mémoire), retient
les 5 threads vus le plus récemment (alimenté par `/v1/chat/completions` et
`/approve`, jamais par les endpoints purement lecture seule `/pending` ou
`/context` eux-mêmes). La page sélectionne le plus récent par défaut, avec un
menu déroulant pour en choisir un autre.

**VRAM (`ENABLE_GPU_STATS`, défaut `false`)** : `nvidia-smi --query-gpu=...
--format=csv,noheader,nounits` en subprocess, désactivé par défaut — nécessite
le runtime nvidia (bloc `deploy` commenté dans `docker-compose.yml`, à
décommenter avec cette variable) pour que le binaire `nvidia-smi` soit
présent dans le conteneur `python:3.12-slim` du dashboard, qui n'a sinon
aucun besoin d'accès GPU.

Hors périmètre explicite (voir demande initiale) : Prometheus/Grafana,
Langfuse, persistance des métriques (tout est en mémoire, perdu au
redémarrage), alerting, auth (réseau local), WebSocket/SSE (le polling 2s
suffit), télémétrie de tâches (taux de succès), tokenizer exact.

## Tests

Chaque service a sa propre suite pytest, isolée des autres (aucune dépendance
partagée entre services, comme en production où chacun tourne dans sa propre
image Docker). Pour exécuter la suite d'un service :

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-test.txt -r services/<nom-du-service>/requirements.txt
cd services/<nom-du-service> && python3 -m pytest tests/ -v
```

Utiliser `python3 -m pytest`, pas la commande `pytest` seule : chaque service
importe son code applicatif comme `import app.main`, ce qui suppose que le
répertoire du service (`services/<nom>`) soit sur `sys.path`. `python3 -m`
l'y ajoute automatiquement ; l'exécutable `pytest` seul ne le fait pas
forcément selon le mode de découverte des tests, et échoue alors avec
`ModuleNotFoundError: No module named 'app'`.

Aucun service tiers réel n'est nécessaire pour lancer les tests : Qdrant
tourne en mode `:memory:`, les serveurs MCP sont remplacés par de vrais petits
serveurs de test (mêmes protocole et transport stdio qu'en production, mais
sans Docker), et les appels HTTP vers les autres microservices ainsi que vers
le LLM sont interceptés par [`respx`](https://github.com/lundberg/respx) (qui
patche le transport HTTP, pas la classe `httpx.AsyncClient` elle-même — voir
plus bas pourquoi cette distinction compte).

Pour `context-manager`, la suite de tests n'a pas besoin de `sentence-transformers`
ni de `torch` (dépendance lourde) : `EMBEDDING_MODEL=fake` (déjà positionné
dans `tests/conftest.py`) bascule sur un embedder déterministe sans dépendance
réseau. Cette variable ne doit jamais être utilisée en production. La commande
générique ci-dessus installe `sentence-transformers` quand même puisqu'il fait
partie de `requirements.txt` ; pour l'éviter explicitement :

```bash
grep -v sentence-transformers services/context-manager/requirements.txt > /tmp/cm-reqs.txt
pip install -r requirements-test.txt -r /tmp/cm-reqs.txt
cd services/context-manager && python3 -m pytest tests/ -v
```

Résumé des suites, à date de la dernière vérification :

| Service | Tests | Ce qui est couvert |
|---|---|---|
| `skill-manager` | 5 | chargement des skills, matching mot-clé, endpoints HTTP |
| `context-manager` | 4 | ingestion/retrieval Qdrant, mémoire par utilisateur, collection vide |
| `mcp-client` | 11 | registre d'outils, schéma function-calling (description/inputSchema) exposé pour le LLM, appel réel via stdio, erreur 404 sur outil inconnu, appel réel via Streamable HTTP (serveur "desktop"/GhostDesk) avec vérification du bearer token et de l'en-tête `GhostDesk-Model-Space` (présent avec la valeur configurée ET absent quand `GHOSTDESK_MODEL_SPACE=""`), serveur "ocr" (services/ocr-service) enregistré/appelable via Streamable HTTP et bearer invalide rejeté |
| `mcp-terminal` | 6 | liste blanche de commandes, lecture de fichier (y compris nom avec espace), blocage du path traversal |
| `ocr-service` | 14 | matching `find_text` exact/fuzzy/désactivé/sans résultat (insensible à la casse, distance de Levenshtein légère mot par mot en secours), conversion de coordonnées pixels -> repère normalisé 0-1000 sur une image 1280x1024 connue (`OCR_COORD_SPACE`) et désactivation (`coord_space="pixels"`), `find_text`/`read_screen` de bout en bout contre un faux serveur MCP GhostDesk réel (Streamable HTTP, image PNG de taille connue), plafond de `read_screen` à 80 éléments triés par confiance, `OCR_ENGINE=fake` (aucune dépendance à PaddleOCR dans les tests) |
| `dashboard` | 16 | parser Prometheus minimal maison sur un payload `/metrics` figé réaliste (commentaires `# HELP`/`# TYPE` ignorés, lignes illisibles tolérées), normalisation des slots `/slots` (clé `used_tokens` : premier champ connu présent parmi plusieurs noms possibles selon la version), parsing CSV `nvidia-smi` (lignes malformées ignorées), `GET /api/snapshot` : agrégation des 3 sources quand tout va bien, llama-server injoignable -> section `null` + statut 200 (jamais 500), langgraph-agent injoignable -> `context` à `null`, `thread_id` explicite en query prioritaire sur le plus récent, VRAM activée (`ENABLE_GPU_STATS`, nvidia-smi mocké) vs désactivée par défaut (nvidia-smi jamais appelé, pas d'erreur), `GET /` renvoie 200 en HTML (page non testée en détail, statique) |
| `langgraph-agent` | 96 (+1 test d'intégration live, ignoré par défaut) | `POST /context` (décomposition du contexte en blocs system/skills/tools_schema/history_text/images sur un historique texte+image réel, schéma d'outils mesuré depuis le cache `_get_bound_llm` jamais recalculé, thread inconnu -> blocs vides plutôt qu'une 404) et `GET /threads/recent` (registre en mémoire alimenté par `/v1/chat/completions`/`/approve`, ordonné par récence, plafonné à 5 — voir section Observabilité), boucle d'appel d'outil, non-duplication des messages, endpoint streaming et non-streaming, pause/reprise d'approbation humaine (approuvé, refusé, streaming inclus), non-duplication de l'historique sur plusieurs tours de conversation, repli du raisonnement en balises `<think>` (champ `reasoning` Ollama OU `reasoning_content` llama-server), **récupération de réponse vide** (`test_empty_answer_recovery.py` : extraction d'un tool_call `<tool_call><function=...>` piégé en prose et reconstruction en tool_calls structuré, tour normalement soumis à approbation après récupération si l'outil est sensible, retry automatique jusqu'à `MAX_EMPTY_ANSWER_RETRIES` puis succès, reset de l'état `<think>` au retry, abandon propre une fois le budget épuisé, flux normal inchangé) + **notice de réponse vide** (`test_non_streaming_endpoint_reports_empty_answer_notice`/`test_streaming_endpoint_reports_empty_answer_notice` : dernier filet si les deux mitigations précédentes échouent), liaison du schéma d'outils mcp-client au LLM (bind_tools), repli des résultats d'outil image en message multimodal, **rétention d'images et thinking adaptatif** (`test_image_retention_and_thinking.py` : ne garde que les `MAX_IMAGES_IN_CONTEXT` dernières captures dans la requête envoyée au LLM sans jamais toucher au checkpointer, passthrough WebP vs conversion PNG par défaut selon `IMAGE_FORMAT_PASSTHROUGH`, injection `/no_think` après un tour entièrement auto-approuvé si `ADAPTIVE_THINKING` est actif, absence d'injection sur le premier tour ou après un outil sensible), **politique d'approbation par tiers de réversibilité** (`approval_policy.py` : tiers lecture/réversible/sensible par défaut, override `TIER_READ_TOOLS`/`TIER_REVERSIBLE_TOOLS`/`AUTO_APPROVED_TOOLS` rétrocompatible, outil inconnu toujours sensible, tour 100% tiers auto-approuvés vs tour mixte, `find_text`/`read_screen` en tier lecture — voir OCR d'appoint plus bas, aussi bien au niveau unitaire que routage réel dans le graphe via `test_find_text_skips_approval_silently`), **règles sur arguments** (`test_approval_rules.py` : `key_type` court/mono-ligne auto-approuvé vs long ou multi-lignes soumis à approbation (au niveau unitaire ET routage réel dans le graphe), règle absente retombe sur le tier statique, ambiguïté entre règles résolue par le plus restrictif, une règle peut durcir un tier autant que l'assouplir, grant de session appliqué après résolution de règle, chargement `APPROVAL_RULES_PATH`/YAML), **grants de session** (`test_session_grants.py` : premier appel toujours soumis à approbation même avec intention de grant, "approuver pour la session" auto-approuve les appels suivants du même outil, portée strictement par outil, grants perdus après reconstruction simulée du checkpointer, champ `grant_session` de `POST /approve`), **journal d'audit** (`test_audit_log.py` : tool_call tiers réversible auto-approuvé tracé, tiers lecture jamais tracé, seul l'appel auto-approuvé via un grant de session apparaît — pas le premier passé par approbation humaine, filtrage `GET /audit?thread_id=`), endpoints `/pending` et `/approve` pour une approbation par bouton d'UI, fermeture de la balise `<think>` restée ouverte en streaming avant le texte d'approbation, fusion d'un seul bloc `<think>` continu sur plusieurs itérations de la boucle d'outils auto-approuvés, notice explicite quand MAX_TOOL_ITERATIONS coupe un run avec un tool_call encore en attente, garde-fou `AUTO_APPROVAL_STREAK_LIMIT` forçant un passage humain après N tours auto-approuvés consécutifs (avec réarmement du compteur après approbation). `tests_integration/` (séparé, non mocké, opt-in via `RUN_LIVE_LLM_TESTS=1`) : non-régression de la dérive du LLM réel sur "va sur google.fr" (longueur de réponse, répétition de trigrammes), vérifiée aussi bien en échouant sur l'ancien Modelfile trop agressif qu'en passant sur le Modelfile corrigé |

## Bugs trouvés et corrigés pendant le développement

Chaque service a été exécuté réellement (pas seulement relu) avant livraison.
Cette démarche a permis de trouver et corriger les bugs suivants :

| Service | Bug trouvé | Correctif |
|---|---|---|
| `mcp-terminal` | `git` absent de l'image `python:3.12-slim` → `git_status` aurait planté | `git` ajouté au `Dockerfile` |
| `mcp-terminal` | `shlex.quote` cassait `cat` sur les noms de fichiers avec espace (quoting shell inutile en mode liste `subprocess`) | remplacé par une résolution de chemin réelle (`os.path.realpath`) qui bloque aussi mieux le path traversal |
| `context-manager` | crash au démarrage si Qdrant pas encore prêt (`depends_on` sans condition ne garantit que l'ordre de démarrage des conteneurs) | retry avec backoff au démarrage + `healthcheck` Qdrant dans le compose |
| `langgraph-agent` | double comptage de certains messages (contexte RAG, résultats d'outils) : les nœuds mutaient `state["messages"]` en place et retournaient l'état entier, ce qui perturbe le reducer `add_messages` de LangGraph | chaque nœud retourne désormais uniquement son delta (`{"messages": [...]}`) |
| `langgraph-agent` | `InvalidUpdateError` de LangGraph quand un nœud ne retourne rien de neuf (`{}`) | retour explicite `{"messages": []}` |
| `langgraph-agent` | `requirements.txt` ne pinnait pas `openai` : `langchain-openai==0.2.2` autorise `openai<2.0.0,>=1.40.0`, mais les versions récentes d'`openai` (1.109+, 2.x) cassent le wrapper HTTP interne de `langchain-openai` (`AttributeError: 'AsyncHttpxClientWrapper' object has no attribute 'build_request'`) — un bug connu et récurrent entre les deux librairies (cf. [langchain-ai/langchain#19116](https://github.com/langchain-ai/langchain/issues/19116)) | `openai==1.51.2` épinglé explicitement, combinaison testée et validée |
| `mcp-client` | `requirements.txt` non installable tel quel : `pydantic==2.9.2` entrait en conflit avec `mcp==1.2.0`, qui exige `pydantic>=2.10.1` — `pip install` (donc le build Docker) aurait échoué | `pydantic==2.10.3` |
| `langgraph-agent` | l'ajout du checkpointer pour la supervision humaine a introduit une duplication de l'historique : Open WebUI renvoie l'historique complet à chaque requête, mais celui-ci était désormais aussi persisté par thread — chaque tour réinjectait donc tout l'historique déjà stocké (2 tours simples produisaient 6 messages internes au lieu de 4) | `owui_message_count` dans l'état du graphe : seuls les messages Open WebUI non encore vus sont soumis à chaque tour |
| `langgraph-agent` | avec Ollama (modèles Qwen3+) comme backend, le raisonnement du modèle est renvoyé dans un champ `reasoning` séparé de `content` sur les deltas SSE — hors format OpenAI standard, donc silencieusement ignoré par `langchain-openai` (`_convert_delta_to_message_chunk` ne lit que `content`/`tool_calls`/`function_call`) : la pensée du modèle n'atteignait jamais Open WebUI | patch de `_convert_delta_to_message_chunk` (`app/graph.py`) qui replie `reasoning` dans `content`, entouré de `<think>...</think>` (convention reconnue par Open WebUI pour la bulle de pensée repliable) — appliqué en direct dans le flux de streaming, pas seulement en fin de réponse |
| `langgraph-agent` | le LLM n'était jamais lié aux outils MCP (`ChatOpenAI` instancié sans `bind_tools`) : le modèle ignorait purement et simplement l'existence de `terminal`/`filesystem`/`git`/`browser`/`desktop`(GhostDesk) et ne produisait donc jamais de `tool_calls` en usage réel — `require_approval`/`call_tools` restaient du code mort, alors que les 14 tests existants passaient quand même (ils simulent directement une réponse LLM avec `tool_calls` tout fait) | `mcp-client` expose désormais `GET /tools/schema` (description + `inputSchema` de chaque outil, jusque-là jetés) ; `langgraph-agent` les récupère et les lie via `bind_tools` (`_get_bound_llm`, mis en cache pour la durée du process) |
| `langgraph-agent` | le résultat brut d'un outil (ex. `screen_shot` de GhostDesk, bloc image MCP `{"type": "image", "data": <base64>, "mimeType": ...}`) était `json.dumps()` intégralement dans un `ToolMessage` — un rôle qui ne supporte que du texte au format OpenAI-compatible : le modèle recevait un blob base64 illisible, jamais une vraie image, indépendamment de ses capacités vision | `_split_image_blocks` extrait les blocs image et les réinjecte en message `user` multimodal (`image_url`), seul rôle qui les supporte |
| `langgraph-agent` | même après le correctif ci-dessus, l'image restait invisible pour le modèle : le décodeur d'image d'Ollama (`mtmd`/llama.cpp) rejette explicitement le WebP (`"Failed to load image or audio file"`), format par défaut de `screen_shot` | `_to_png_data_uri` (Pillow) reconvertit systématiquement en PNG avant transmission, plutôt que de compter sur le modèle pour penser à demander `format="png"` à chaque appel |
| `ollama` (service) | avec une image dans le contexte, le nombre de tokens (texte + tokens visuels) dépassait le contexte par défaut choisi automatiquement par Ollama selon la VRAM disponible (4096 tokens observés) — `"request (4713 tokens) exceeds the available context size (4096 tokens)"` | `OLLAMA_CONTEXT_LENGTH=16384` fixé explicitement dans `docker-compose.yml` |
| `mcp-client` | les clics souris GhostDesk (`mouse_click`, etc.) atterrissaient systématiquement à côté de leur cible avec les modèles Qwen : ceux-ci raisonnent nativement en repère de coordonnées normalisé 0-1000, alors que GhostDesk interprète par défaut les coordonnées reçues comme des pixels écran natifs (documenté par GhostDesk) | en-tête `GhostDesk-Model-Space` (`GHOSTDESK_MODEL_SPACE`, défaut `1000`) ajouté à chaque appel HTTP vers GhostDesk dans `_run_on_server` |
| `langgraph-agent` | avec `AUTO_APPROVED_TOOLS`, `call_llm` peut s'exécuter plusieurs fois d'affilée sans pause d'approbation (boucle capture/clic GhostDesk) ; chaque appel remettait l'état de la balise `<think>` à zéro, donc chaque itération de raisonnement rouvrait sa propre balise en plein milieu du flux — Open WebUI n'affiche en bulle repliable que celle en tout début de message, les suivantes apparaissaient en texte brut visible (ex. observé en usage réel : `<think>...<think>...</think>Cliqué.`) | état `think_opened`/`think_closed` déplacé de la variable de contexte locale à `AgentState` (comme `tool_iterations`), reporté d'un appel de `call_llm` à l'autre au sein d'un même tour et remis à `False` uniquement au tout début d'un nouveau tour (`_resolve_run`, `app/main.py`) — un seul bloc `<think>` continu sur toute la boucle |
| `langgraph-agent` | `tool_iterations` ne se réinitialise jamais entre deux tours "approuver" (seulement sur un tout nouveau message utilisateur) : le budget de `MAX_TOOL_ITERATIONS` (5 à l'origine) est donc partagé sur toute une chaîne d'approbations, épuisé en 2-3 aller-retours à peine, avant même la boucle GhostDesk auto-approuvée qui en consomme 2 par geste (capture+clic) — `has_tool_calls` force alors la fin du graphe MÊME SI le dernier message du modèle contient un tool_calls en attente, silencieusement jeté sans aucun message d'explication (observé en usage réel : l'agent semblait "s'arrêter" en plein milieu d'une tâche, ex. en train de taper une URL) | `MAX_TOOL_ITERATIONS` relevé (configurable via env, défaut `20`) ; `app/main.py` détecte désormais ce cas (dernier message avec `tool_calls` mais graphe non mis en pause) et renvoie une notice explicite au lieu du texte de raisonnement brut ; `recursion_limit` de LangGraph (25 par défaut, indépendant de `MAX_TOOL_ITERATIONS` et bien plus vite atteint par une longue boucle auto-approuvée) relevé en conséquence pour éviter un `GraphRecursionError` brut avant même d'atteindre cette notice |
| `ollama` (modèle `agent-llm`, quant IQ2_M) | un tour de raisonnement pouvait dégénérer en dérive sémantique (pas une répétition mot à mot, mais une cascade de synonymes de plus en plus rares/incohérents, ex. observé en usage réel sur la tâche "va sur google.fr" : dérive vers une énumération de gentilés régionaux français puis d'ères géologiques) sans jamais produire de `tool_calls`, jusqu'à saturer tout le contexte (`OLLAMA_CONTEXT_LENGTH`). Nos garde-fous (`MAX_TOOL_ITERATIONS`/`AUTO_APPROVAL_STREAK_LIMIT`) ne s'appliquent pas ici : ils comptent des itérations d'*outils*, pas la longueur d'une génération. Cause réelle, confirmée en comparant l'horodatage du manifest Ollama (recréation à 10:56) à celui de la conversation cassée (11:12) puis en rejouant la même tâche après correction : le Modelfile de `agent-llm` avait été durci un peu plus tôt dans la même session (`repeat_penalty` `1.0`→`1.15`, `repeat_last_n` `64`→`1024`, `presence_penalty` déjà à `1.5`) pour parer une boucle de répétition redoutée, mais cette combinaison était en réalité bien trop agressive pour un modèle aussi quantisé — en interdisant la réutilisation de mots sur une fenêtre de 1024 tokens, elle forçait le modèle à piocher un vocabulaire toujours plus rare pour continuer, provoquant elle-même la dérive observée. Une première explication écrite ici ("`repeat_last_n` trop court") s'est donc révélée fausse : le réglage durci était déjà actif *pendant* la dérive, pas absent | Modelfile assoupli : `repeat_penalty` `1.15`→`1.05`, `repeat_last_n` `1024`→`256`, `presence_penalty` `1.5`→`0` — revérifié en rejouant "va sur google.fr" via `/v1/chat/completions`, deux tours consécutifs cohérents (`key_type` puis `key_press`, sans dérive). Ce réglage vivait uniquement dans le store Ollama du conteneur (volume `ollama-data`), perdu au moindre `ollama pull`/`cp` refait à la main : `scripts/rebuild-agent-llm.sh <modèle-source>` fige désormais la recette dans le repo pour la réappliquer à l'identique quel que soit le modèle source, y compris après un changement de modèle puis un retour au modèle actuel. `LLM_MAX_TOKENS` (configurable via env, défaut `2048`, `app/graph.py`) conservé en filet de sécurité indépendant, pour plafonner tout dérapage résiduel d'un tour plutôt que de laisser saturer tout le contexte |
| `llama-server` | build CUDA échouant à l'édition de liens (`undefined reference to cuMemCreate/cuDeviceGet/cuGetErrorString/...`) : ggml active par défaut l'allocateur "CUDA Virtual Memory Management" (pooling KV-cache), qui lie `ggml-cuda` contre le driver CUDA réel (`libcuda.so`, cible CMake `CUDA::cuda_driver`) — absent d'une image `*-devel` au moment du build (fourni seulement au runtime par le driver hôte via `nvidia-container-toolkit`, jamais pendant un `docker build` classique) | `-DGGML_CUDA_NO_VMM=ON` ajouté à la configuration CMake — ne touche ni `--flash-attn` ni `--cache-type-v turbo3`, seulement cet allocateur de pooling (peu pertinent ici avec `--parallel 1`) |
| `llama-server` | Blackwell (sm_120, RTX 5060 Ti) non pris en charge : la base `nvidia/cuda:12.4.1-*` initialement choisie ne supporte pas la compilation pour cette architecture (confirmé dans le CMakeLists du fork : `120a-real` nécessite CUDA >= 12.8) | base `nvidia/cuda:12.8.1-devel/runtime-ubuntu22.04` + `CMAKE_CUDA_ARCHITECTURES="89-real;120a-real"` explicite (Ada + Blackwell) plutôt que la détection "native" (nécessite un GPU visible PENDANT le build, absent d'un `docker build` standard) — revérifié via `llama-server --list-devices --gpus all`, les deux GPU détectés |
| `llama-server` | binaire buildé mais inexécutable : `libllama-common.so.0`/`libmtmd.so.0`/`libllama.so.0`/`libggml-base.so.0` introuvables au lancement (`cannot open shared object file`) — le build CMake de ce fork produit les bibliothèques partagées dans le même dossier que les exécutables, mais SANS RPATH/RUNPATH embarqué (vérifié via `readelf -d`), contrairement à l'hypothèse initiale d'une résolution `$ORIGIN` ; `libgomp.so.1` (OpenMP, utilisé par le backend CPU de ggml) manquait aussi de l'image runtime | `COPY --from=build /src/build/bin/ /app/` (tout le dossier, pas seulement le binaire) + `ENV LD_LIBRARY_PATH=/app` + `libgomp1` ajouté aux paquets runtime |
| `llama-server` | conteneur en boucle de redémarrage au premier lancement réel : `--flash-attn` (passé sans valeur dans `entrypoint.sh`, comme un simple flag booléen) avalait l'argument suivant (`--jinja`) comme sa propre valeur — `error: unknown value for --flash-attn: '--jinja'`. Ce fork a changé `-fa`/`--flash-attn` d'un flag booléen vers une option à valeur obligatoire (`on`/`off`/`auto`), confirmé via `llama-server --help` | `--flash-attn on` explicite dans `entrypoint.sh` — revérifié en relançant le conteneur, plus de boucle de redémarrage, modèle chargé jusqu'au bout |
| `langgraph-agent` | avec llama-server (fork turboquant-webp) comme backend, le raisonnement du modèle disparaissait silencieusement du flux streamé (aucune erreur, juste absent) — le patch `_convert_delta_with_reasoning` (`app/graph.py`) ne lisait que le champ `reasoning` (convention Ollama, sur laquelle il avait été écrit et testé), alors que llama-server streame le raisonnement dans un champ `reasoning_content` (convention DeepSeek-R1/OpenAI o1). Confirmé en inspectant les deltas SSE bruts d'un vrai appel streamé contre le vrai binaire : jamais de clé `reasoning`, toujours `reasoning_content` | le patch lit désormais `reasoning` OU `reasoning_content` (`_dict.get("reasoning") or _dict.get("reasoning_content")`) — revérifié de bout en bout via `langgraph-agent` réel : `<think>` s'ouvre, le raisonnement s'affiche, `</think>` se ferme avant la réponse finale, comme avec Ollama |
| `langgraph-agent` | observé en usage réel (conversation "va sur wikipedia.org et cherche l'article sur la ville de toulouse, en français", pilotage GhostDesk) : le modèle finissait parfois un tour SANS aucun `tool_calls` structuré ET sans texte de réponse visible — sa tentative d'appel d'outil restait écrite en prose façon Qwen (`<tool_call><function=NOM><parameter=...>`) noyée dans le raisonnement (`reasoning_content`), jamais reconnue comme un vrai tool_calls OpenAI. **Cause racine confirmée** en lisant le parseur du fork (`common/chat-auto-parser-generator.cpp`) : le raisonnement (`<think>...`) est capturé comme texte LIBRE, non contraint par la grammaire, jusqu'à rencontrer `</think>` — la grammaire stricte du tool-calling n'est appliquée qu'APRÈS cette balise. Si le modèle "tente" un appel avant d'avoir fermé `</think>` (observé après un raisonnement anormalement long/répétitif, à rapprocher de la dérive sémantique déjà documentée pour Ollama), la tentative reste piégée dans la zone non contrainte. Confirmé non-déterministe (rejouer le même prompt donne tantôt un `tool_calls` correct, tantôt cet échec) et confirmé résolu par `/no_think` (contourne entièrement ce chemin de code, voir Thinking adaptatif) — mais celui-ci ne s'injecte qu'à partir du tour suivant un tour auto-approuvé, pas sur le tout premier tour d'une tâche, là où le bug a justement été observé la première fois. Sans correctif, l'utilisateur ne voyait que la bulle de raisonnement se refermer sur rien, exactement le symptôme "l'agent s'arrête en plein milieu d'une tâche" déjà documenté pour `MAX_TOOL_ITERATIONS` | Trois mitigations complémentaires (aucune ne corrige la cause côté serveur/modèle, hors de portée ici) : **(1)** `_extract_fallback_tool_call` (`app/graph.py`) reconnaît la syntaxe `<tool_call><function=...>` piégée dans le texte et la reconstruit en tool_calls structuré avant même de compter le tour comme un échec (log `WARNING` à chaque récupération, pour garder la visibilité sur la fréquence réelle du problème) ; **(2)** `retry_empty_answer` reboucle automatiquement sur `call_llm` jusqu'à `MAX_EMPTY_ANSWER_RETRIES` fois (défaut `1`, budget cumulé pour toute la tâche comme `tool_iterations`) quand la reconstruction échoue aussi ; **(3)** au-delà, `has_visible_answer`/`_format_empty_answer_notice` (`app/main.py`) affiche une notice explicite plutôt qu'un message vide. **Confirmé efficace en conditions réelles** : sur 4 tâches indépendantes rejouées après déploiement du correctif, le parseur de secours s'est déclenché 5 fois (`app_launch`, `app_running` ×2, `screen_shot`) et a récupéré l'intention du modèle à chaque fois, sans qu'aucune des 4 tâches n'affiche la notice de repli |

| `ocr-service` | build de l'image réellement exécuté (jusque-là seule la suite de tests, en `OCR_ENGINE=fake`, avait tourné) : trois échecs successifs. **(1)** `libgomp.so.1` introuvable — absent de `python:3.12-slim`, requis dès l'import de paddlepaddle (même classe de bug que `llama-server` ci-dessus). **(2)** une fois corrigé, `ModuleNotFoundError: No module named 'setuptools'` — `paddle.utils.cpp_extension` l'importe inconditionnellement dès `import paddle`, absent par défaut de cette image (seul `pip` y est préinstallé). **(3)** une fois les deux corrigés, crash restant (`Segmentation fault`, puis `double free or corruption`/`munmap_chunk(): invalid pointer` selon le run — symptôme différent à chaque fois selon l'ASLR, signature classique d'une corruption de tas plutôt que d'une dépendance manquante). **Cause racine confirmée par backtrace `gdb`** : `paddlepaddle==2.6.2` embarque sa propre copie de `zlib` dans `libpaddle.so`, avec des symboles globaux non isolés (`inflateReset2`) qui entrent en collision avec `libz.so.1` système dès que `Cython` (importé en cascade par `paddle.utils.cpp_extension`) décompresse quoi que ce soit via le module `zlib` de la stdlib | `libgomp1`/`libgl1`/`libglib2.0-0` (ce dernier duo requis par `cv2`, dépendance transitive de paddleocr) ajoutés au `Dockerfile` ; `setuptools==75.6.0` épinglé dans `requirements.txt` ; `ENV LD_PRELOAD=/lib/x86_64-linux-gnu/libz.so.1` force la résolution vers la bonne bibliothèque, au build ET à l'exécution (import paresseux dans `app/ocr_engine.py`) — revérifié en buildant l'image pour de vrai (téléchargement des modèles PP-OCRv3 au build) puis en déclenchant un vrai appel `read_screen` via `mcp-client` contre GhostDesk : texte réel détecté à l'écran avec coordonnées et scores de confiance |
| `llama-server` | découvert en rejouant le harnais de baseline Phase 0 de la migration langgraph/langchain-openai/openai (`tests_integration/test_tool_calling_baseline.py`) : une bonne partie des tours (jusqu'à environ la moitié sur une session de 25 générations réelles) se terminaient par la notice de repli `⚠️ Erreur interne pendant la génération, réessayez.` (`except Exception` de `_stream_response`, `app/main.py`) au lieu d'un résultat de tool-calling exploitable — le `<think>` du tour restait parfois même ouvert sans jamais se refermer, la génération ayant été coupée en plein milieu. Persiste à l'identique en espaçant les requêtes de plusieurs secondes avec vérification de santé entre chaque (`_wait_for_llama_health`) : pas un effet du harnais qui martèlerait le serveur. **Cause racine confirmée** dans les logs `llama-server` : un crash GPU dur (`CUDA error: unspecified launch failure` sur `ggml_backend_cuda_device_event_synchronize`, `ggml-cuda.cu:5742`), systématiquement sur `device 1` (RTX 5060 Ti, Blackwell) et systématiquement juste après une ligne `restored context checkpoint` — pointe vers le mécanisme de cache de prompt/checkpoints de contexte de ce fork (`prompt cache is enabled`, cf. [llama.cpp#16391](https://github.com/ggml-org/llama.cpp/pull/16391)), probablement incompatible avec ce rig double-GPU hétérogène (Ada `RTX 4070 Ti SUPER` + Blackwell `RTX 5060 Ti`, tensor-split entre les deux) lors de la resynchronisation CUDA inter-GPU nécessaire pour restaurer un checkpoint. `llama-server` se relance seul après coup (superviseur interne `cmd_child_to_router`), d'où l'absence de panne totale visible côté utilisateur — seulement des tours qui échouent au hasard | **Non résolu à ce jour, hors périmètre de cette migration** (bug driver/CUDA de `llama-server`, aucun rapport avec le trio Python langgraph/langchain-openai/openai en cours de montée de version). Piste de contournement identifiée mais pas encore testée : désactiver le cache de prompt (`--cache-ram 0` via `LLAMA_EXTRA_ARGS`, voir section Observabilité) pour vérifier si ça supprime la restauration de checkpoint qui déclenche le crash — à faire avant de pouvoir considérer une baseline Phase 0 fiable |

Une fausse alerte a aussi été rencontrée puis écartée : un test utilisait un
monkeypatch global de `httpx.AsyncClient` pour simuler les appels HTTP vers
les autres microservices, ce qui cassait par effet de bord le client interne
du SDK `openai` (qui construit ses propres classes comme sous-classes de
`httpx.AsyncClient`). La suite de tests finale utilise `respx`, qui patche au
niveau du transport HTTP sans jamais toucher à la hiérarchie de classes.

## Streaming SSE token-par-token

Implémenté et couvert par les tests (`stream: true` sur `/v1/chat/completions`) :

- `call_llm` utilise `llm.astream()` et fusionne les `AIMessageChunk`
  (opérateur `+=`) — y compris les `tool_call_chunks`, qui arrivent eux aussi
  streamés en morceaux et se fusionnent automatiquement en `tool_calls`
  complets.
- L'endpoint HTTP utilise `agent_graph.astream_events(..., version="v2")` et
  ne transmet au client que les événements `on_chat_model_stream` — dans la
  pratique, une itération qui déclenche un appel d'outil produit un contenu
  vide côté LLM (le tool_call passe par un canal séparé), donc l'utilisateur
  ne voit jamais l'agent "réfléchir" à quel outil utiliser : seule la réponse
  finale s'affiche, token par token.
- Format SSE conforme à l'API OpenAI (`chat.completion.chunk`, `delta.content`,
  `finish_reason`, `data: [DONE]`).
- Le mode non-streamé (`stream: false`) continue de fonctionner à l'identique.

**Point d'attention** : la combinaison `langgraph==0.2.34` +
`langchain-openai==0.2.2` + `openai==1.51.2` est celle qui a été testée et
validée pour le streaming. Une mise à jour de l'une de ces trois dépendances
sans revalider `ChatOpenAI.astream()` en conditions réelles risque de
réintroduire la régression décrite plus haut.

## Persistance des données

Deux volumes Docker nommés persistent à travers les redémarrages et les
`docker compose down` / `up` (mais pas `docker compose down -v`, qui les
supprime) :

- **`qdrant-data`** : contenu des collections `documents` et `memory` de
  `context-manager` (RAG et mémoire long-terme).
- **`open-webui-data`** (`/app/backend/data`) : conversations, comptes
  utilisateurs, fichiers uploadés et paramètres d'Open WebUI (base SQLite
  interne à l'image).

Trois répertoires montés en bind mount persistent nativement, puisqu'ils
vivent directement sur le système de fichiers de l'hôte, indépendamment du
cycle de vie des conteneurs : `./workspace`, `./skills`, `./models`.

**Point de vigilance corrigé** : `WEBUI_SECRET_KEY` n'était fixé nulle part.
Sans cette clé fixe, Open WebUI en génère une nouvelle à chaque recréation de
conteneur, ce qui invalide toutes les sessions de connexion (et empêche de
déchiffrer d'éventuels secrets stockés, comme des jetons OAuth) même si les
données elles-mêmes restent intactes dans le volume. Corrigé : la clé se
configure maintenant via `.env` (voir `.env.example`), à générer une seule
fois avec `openssl rand -hex 32`.

Les autres services (`skill-manager`, `mcp-client`, `mcp-terminal`) sont sans
état. `langgraph-agent` reste conceptuellement sans état lui non plus : c'est
Open WebUI qui renvoie l'historique complet de la conversation à chaque
requête `/v1/chat/completions`, pas `langgraph-agent` qui le conserve de façon
persistante. Il compile toutefois désormais son graphe avec un checkpointer
(`MemorySaver`, **en mémoire seulement**), nécessaire pour la supervision
humaine des appels d'outils (voir section suivante) : un redémarrage du
service perd toute approbation en attente, ce qui relance simplement une
conversation "fraîche" pour le thread concerné — aucune donnée n'est donc
réellement perdue au sens propre.

## Supervision humaine des appels d'outils

Tout appel d'outil demandé par le LLM (`terminal`, `filesystem`, `git`,
`browser`, `desktop`/GhostDesk) suspend le graphe LangGraph au lieu de
s'exécuter automatiquement (nœud `require_approval`,
`services/langgraph-agent/app/graph.py`). L'agent répond alors dans la
conversation avec un message `⚠️ Approbation requise pour : ...` proposant
trois réponses : "approuver" (une fois), "approuver pour la session" (voir
Grants de session plus bas) ou "refuser" (un `ToolMessage` d'erreur "Rejeté
par l'utilisateur" est renvoyé au LLM, qui peut réagir normalement).

**Politique par tiers de réversibilité** (`services/langgraph-agent/app/
approval_policy.py`), qui remplace l'ancienne whitelist binaire :

| Tier | Comportement | Exemples par défaut |
|---|---|---|
| `TIER_READ` (lecture) | auto, silencieux | `screen_shot`, `mouse_move`, `app_list`, `app_running`, `app_status`, lecture filesystem/git (`read_file`, `git_status`, `git_log`...), `run_command` (mcp-terminal, déjà une liste blanche stricte en lecture seule) |
| `TIER_REVERSIBLE` (réversible) | auto + journalisation (voir Phase 2, journal d'audit) | `mouse_click`, `mouse_double_click`, `mouse_drag`, `mouse_scroll`, `key_press`, `app_launch`, `clipboard_set`, écritures filesystem/git confinées (`write_file`, `git_commit`...) |
| `TIER_SENSITIVE` (sensible) | approbation humaine requise | `key_type` (saisie de texte libre), tout le reste, **et tout outil inconnu** |

**Règles sur arguments** (Phase 4, `RULES`/`_load_rules` dans
`approval_policy.py`, format `outil(pattern)` à la Claude Code) : affinent
le tier d'un outil selon SES ARGUMENTS plutôt que son seul nom. Implémentées
comme des matchers nommés en Python (pas de DSL de pattern générique), pas
comme une simple ANDition avec le tier statique — une règle qui matche
l'emporte entièrement sur `tool_tier()`. Règle par défaut :
`key_type(len<50,no_newline)` → `TIER_REVERSIBLE` (saisie courte et
mono-ligne, assez anodine pour ne pas justifier une approbation à chaque
frappe), alors que `key_type` reste `TIER_SENSITIVE` par défaut pour tout le
reste (texte long ou multi-lignes — script collé, code...). Un matcher
`command_prefix` est aussi fourni (préfixes de commande, ex. pour
`run_command` côté mcp-terminal) mais sans règle par défaut, ce serveur
n'exposant déjà qu'une liste blanche en lecture seule. En cas d'ambiguïté
(plusieurs règles nommées pour le même outil matchent à la fois), le tier
le plus restrictif gagne. `APPROVAL_RULES_PATH` (variable d'env, optionnel)
pointe vers un fichier YAML qui complète ces règles par défaut (jamais ne
les remplace) — voir `_load_rules_from_yaml` pour le format exact
(`tool`/`matcher`/`tier`, `command_prefix` prenant en plus `prefixes`).

Le défaut est toujours le tier le plus restrictif, jamais l'inverse : un
outil qui n'apparaît dans aucune des listes `TIER_READ_TOOLS`/
`TIER_REVERSIBLE_TOOLS` (surchargeables via ces variables d'env,
CSV) est automatiquement `TIER_SENSITIVE`. Routage dans `has_tool_calls` :
un tour dont **tous** les tool_calls sont en tier lecture ou réversible
saute `require_approval` ; un tour mixte (même un seul outil sensible)
reste entièrement soumis à approbation, par sécurité — pas d'approbation
partielle par outil.

`AUTO_APPROVED_TOOLS` (ancienne variable d'env) reste utilisable comme
override rétrocompatible : tout outil qui y figure est traité comme
`TIER_REVERSIBLE` même s'il n'est dans aucune des deux listes ci-dessus.
Vide par défaut désormais — les anciens défauts historiques (`app_list,
app_running,screen_shot,mouse_move,mouse_click,mouse_double_click,
mouse_drag,mouse_scroll`) sont déjà couverts par les tiers par défaut
ci-dessus, donc ce nouveau défaut vide reproduit le même comportement pour
un déploiement qui ne fixe pas cette variable.

Une exclusion volontaire malgré son nom trompeur : `clipboard_get` reste
`TIER_SENSITIVE` malgré son nom de "lecture" — il peut exfiltrer des
données sensibles copiées par l'utilisateur (mot de passe, jeton...), pas
moins sensible que `clipboard_set`.

`key_type`/`key_press` restent hors `TIER_READ`, mais une **suite** de
`mouse_click` auto-approuvés peut en théorie composer n'importe quelle
saisie via un clavier virtuel à l'écran, contournant de fait cette
exclusion — voir `AUTO_APPROVAL_STREAK_LIMIT` juste en dessous, qui
s'applique à tout outil auto-approuvé (tier lecture ou réversible), pas
seulement à l'ancienne liste `AUTO_APPROVED_TOOLS`.

**Garde-fou contre le clavier virtuel** (`AUTO_APPROVAL_STREAK_LIMIT`,
variable d'env, défaut `6`) : au-delà de ce nombre de tours auto-approuvés
consécutifs *sans passage par un humain*, `has_tool_calls` force le tour
suivant à repasser par `require_approval` — même s'il ne contient que des
outils normalement auto-approuvés. Compteur `auto_approval_streak` dans
`AgentState`, incrémenté à chaque tour exécuté (`call_tools`) et remis à 0
dès qu'un humain valide réellement une approbation (`require_approval`,
uniquement lors de la reprise, pas pendant la pause). Distinct de
`tool_iterations`/`MAX_TOOL_ITERATIONS`, qui mesure un budget total pour
toute la tâche et non un nombre de tours *consécutifs sans supervision*.

**Grants de session** (Phase 3, `AgentState.session_grants` dans
`app/graph.py`) : répondre "approuver pour la session" plutôt que
"approuver" ajoute le(s) outil(s) du tour en attente à une liste
`session_grants` propre à ce thread. Un outil qui y figure est ensuite
plafonné à `TIER_REVERSIBLE` (auto + audit, voir Phase 2 ci-dessous) pour le
reste de la conversation — `approval_policy.effective_tier()` en tient
compte en plus du tier statique de l'outil. Un grant ne s'applique jamais
rétroactivement : le tour qui le demande reste soumis à CETTE approbation,
seuls les appels *suivants* du même outil en profitent. Portée strictement
par outil : accorder `key_type` ne dispense pas `browser_navigate`.

Ces grants vivent dans l'état du graphe, donc dans le même checkpointer
`MemorySaver` (en mémoire uniquement, voir section Persistance des données)
que le reste du thread — **ils meurent avec lui** : un redémarrage du
service les perd exactement comme il perd une approbation en attente,
puisqu'il n'existe aucune distinction entre "perdre l'état du thread" et
"perdre les grants qu'il contenait". Comportement voulu pour un usage
local : pas de persistance de grants inter-redémarrage, chaque nouvelle
conversation (ou reprise après redémarrage) repart sans historique
d'approbation.

**Journal d'audit** (Phase 2, `services/langgraph-agent/app/audit_log.py`) :
chaque tool_call `TIER_REVERSIBLE` **effectivement auto-approuvé** (arrivé
directement depuis `has_tool_calls`, sans passer par `require_approval` CE
tour-ci) est loggé en JSONL sous `AUDIT_LOG_DIR` (défaut `/workspace/.audit`,
même bind mount que les serveurs MCP filesystem/git/terminal — voir
`docker-compose.yml`), un fichier par jour (`YYYY-MM-DD.jsonl`, rotation par
nom de fichier). Chaque ligne : `timestamp`, `thread_id`, `tool`,
`arguments`, `tier`. Volontairement **pas** de trace pour :
- les tool_calls `TIER_READ` (silencieux par design, rien de nouveau à
  auditer) ;
- les tool_calls exécutés après un passage par `require_approval` (même
  s'ils sont `TIER_REVERSIBLE`) : ce tour a déjà un humain dans la boucle,
  déjà tracé dans l'historique de conversation ("⚠️ Approbation requise" +
  la réponse) — dupliquer cette trace dans le journal d'audit irait à
  l'encontre de son objet, qui est justement de tracer ce qu'un humain n'a
  PAS vu passer.

Concrètement, pour un outil accordé "pour la session" (voir Grants de
session ci-dessus) : le tout premier appel (celui qui a déclenché
`require_approval`) n'apparaît jamais dans le journal, seuls les appels
*suivants* du même outil, désormais auto-approuvés via le grant, y
apparaissent. `GET /audit?thread_id=...` (optionnel, sans lui renvoie tout
le journal disponible) permet la consultation ; une ligne corrompue
individuelle est ignorée à la lecture plutôt que de faire échouer toute la
requête.

**Approbation par bouton d'UI, sans passer par un message texte** : deux
endpoints complètent le flux texte "approuver"/"approuver pour la
session"/"refuser" —

- `POST /pending` (lecture seule, ne modifie aucun état) : indique si le
  thread dérivé de `messages` est en pause d'approbation, et renvoie le
  texte de la demande. Ne dépend que du premier message humain (dérivation
  du `thread_id`), jamais du contenu du dernier message assistant — celui-ci
  peut être vide ou tronqué côté client selon la façon dont Open WebUI
  interprète les balises `<think>`.
- `POST /approve` (`{"messages": [...], "approved": bool, "grant_session":
  bool}`) : reprend le thread en pause directement depuis une décision hors
  bande (Open WebUI Action function), en éditant en place le message "⚠️
  Approbation requise" existant plutôt qu'en ajoutant un nouveau message —
  d'où un bookkeeping de `owui_message_count` sans le `+1` appliqué au flux
  texte normal. `grant_session` (optionnel, défaut `false`, ignoré si
  `approved=false`) est le miroir de "approuver pour la session" pour ce
  flux hors bande. Renvoie 409 s'il n'y a aucune approbation en attente pour
  ce thread.

**Correctif streaming** : quand le modèle raisonne (balises `<think>`) avant
de décider d'un appel d'outil, le tour se termine avec un `content` réel
vide (le tool_call passe par un canal séparé), donc aucun chunk de contenu
ne referme jamais la balise côté client. Sans correctif, le texte
d'approbation qui suit se retrouvait concaténé à l'intérieur du `<think>`
resté ouvert — invisible en dehors de la bulle de pensée repliée d'Open
WebUI. `_stream_response` (`app/main.py`) referme désormais la balise avant
d'émettre ce texte, en se basant sur ce qui a réellement été streamé au
client (pas sur l'état déjà réparé en interne par `call_llm`).

Comme Open WebUI ne fournit pas d'identifiant de conversation stable à
`/v1/chat/completions` (il renvoie juste l'historique complet à chaque
appel), le thread LangGraph associé est retrouvé en dérivant un `thread_id`
déterministe à partir du hash du premier message de la conversation
(`_derive_thread_id`, `services/langgraph-agent/app/main.py`). **Limite
assumée** : deux conversations distinctes commençant par un message
strictement identique partageraient le même thread — acceptable pour un
usage local mono-utilisateur, pas au-delà. Un vrai correctif existerait côté
Open WebUI (écrire une "Pipe function" qui récupère son `chat_id` interne et
le transmet en amont) mais Open WebUI ne transmet actuellement pas cette
métadonnée à un backend OpenAI-compatible externe comme celui-ci (limitation
connue et documentée par le projet, non résolue à ce jour :
[discussion #6999](https://github.com/open-webui/open-webui/discussions/6999)).

Puisque ce thread persiste maintenant sur toute la durée d'une conversation
(pas seulement pendant une pause d'approbation), et qu'Open WebUI renvoie à
chaque tour l'historique complet en plus de ce qui est déjà persisté,
`owui_message_count` (champ de l'état du graphe) retient combien de messages
Open WebUI ont déjà été intégrés — seul le nouveau message est alors soumis
au tour suivant, ce qui évite de dupliquer l'historique (bug réellement
rencontré et corrigé pendant le développement, voir le tableau plus haut).

Aucune version de dépendance n'a été modifiée pour implémenter cette
fonctionnalité : `langgraph==0.2.34` (déjà pinné) fournissait déjà
`NodeInterrupt`, `MemorySaver` et les méthodes async `aget_state`/`aupdate_state`
nécessaires — la combinaison fragile `langgraph`/`langchain-openai`/`openai`
documentée plus haut pour le streaming n'a donc pas été touchée.



- **Téléchargement du modèle d'embeddings** (`sentence-transformers`) :
  aucun test n'a pu être exécuté avec un accès réseau à `huggingface.co`
  dans l'environnement de développement utilisé. La logique Qdrant est
  couverte avec un embedder factice déterministe (voir section Tests), mais
  `SentenceTransformer.encode()` en conditions réelles n'a pas été exercé.
- **Spawn réel de conteneurs Docker par `mcp-client`** : couvert avec un vrai
  serveur MCP lancé en process Python direct (même protocole que les vrais
  serveurs), mais pas avec le socket Docker ni les images `mcp/*` réelles.
- **`llama-server` : build, démarrage et inférence texte vérifiés
  réellement** (modèle `Qwen3.6-35B-A3B` quant `Q5_K_M` + `mmproj-F16`,
  conversation complète de bout en bout à travers `langgraph-agent`, voir
  section Backend d'inférence et tableau des bugs). **Non vérifié : function
  calling réel avec un tool_call effectif** (les tests d'intégration
  couvrant `has_tool_calls`/`require_approval`/`call_tools` restent basés
  sur des réponses LLM simulées, voir section Tests) **et le décodage WebP
  natif en conditions réelles** (`IMAGE_FORMAT_PASSTHROUGH=webp` — testé
  uniquement en conversation texte pure, jamais avec un `screen_shot`
  GhostDesk réel) ; aucun test de charge non plus.

## Limites connues assumées (choix de conception, pas des bugs)

- **`mcp-terminal` n'expose pas de shell libre** : liste blanche stricte
  (`ls`, `pwd`, `cat`, `git status`), confinée à `/workspace`. Étendre cette
  liste avec prudence : chaque commande ajoutée est une nouvelle surface
  d'attaque potentielle.
- **`mcp-client` monte `/var/run/docker.sock`** : équivaut à un accès root sur
  l'hôte. Acceptable en usage local ; à remplacer par un socket-proxy filtrant
  avant toute exposition réseau.
- **Matching de skills et RAG volontairement simplistes** (mot-clé naïf, pas
  de reranker) — à muscler si le volume de skills/documents grossit.
- **`ghostdesk` (serveur MCP "desktop") tourne avec `cap_add: SYS_ADMIN` et
  expose un shell** : surface d'attaque bien plus large que `mcp-terminal`
  (pas de whitelist, contrôle GUI complet). À ne jamais exposer au-delà du
  réseau interne `agent-net` — seul le port noVNC (6080) est publié sur
  l'hôte, volontairement, pour observer l'agent piloter le bureau ; le port
  MCP (3000) ne l'est pas. `mcp-terminal` reste l'outil par défaut pour les
  commandes simples ; `ghostdesk` n'est sollicité que pour du pilotage GUI
  qui le justifie réellement — les deux coexistent sciemment plutôt que de
  remplacer l'un par l'autre. Accès : http://localhost:6080 une fois le
  service démarré, mot de passe = `GHOSTDESK_VNC_PASSWORD` (voir `.env`).
- **Limite historique levée** : les outils de capture d'écran/clic guidé de
  `ghostdesk` n'étaient pas exploitables par l'agent tant que le modèle
  servi (Qwen2.5-Coder, via vLLM) n'était pas multimodal. Le backend par
  défaut est désormais `llama-server` (voir section Backend d'inférence),
  servant Qwen3.6-35B-A3B avec un projecteur multimodal (`--mmproj`) —
  l'agent peut donc désormais recevoir et interpréter les captures d'écran
  GhostDesk. Reste néanmoins une limite distincte, désormais atténuée mais
  pas résolue : la précision du grounding (viser le bon élément à l'écran)
  d'un modèle de vision généraliste. `ocr-service` (voir section OCR
  d'appoint plus haut) compense pour les éléments TEXTUELS via
  `find_text`/`read_screen` (coordonnées OCR exactes plutôt qu'une
  estimation visuelle) ; les éléments sans texte (icônes) restent estimés
  visuellement par le VLM, sans détection d'éléments UI dédiée (type
  OmniParser, explicitement hors périmètre pour l'instant).
- **`ghostdesk` est un serveur MCP HTTP persistant avec état** (bureau/session
  VNC), contrairement aux autres serveurs MCP du projet qui sont spawnés en
  STDIO éphémère par `mcp-client` (`docker run -i --rm` par appel). Il tourne
  en continu comme service `docker-compose` à part ; `mcp-client` s'y
  connecte via `streamablehttp_client` (SDK `mcp` ≥ 1.8, d'où le bump de
  `mcp==1.2.0` vers `mcp==1.9.4` dans `services/mcp-client/requirements.txt`),
  authentifié par bearer token (`GHOSTDESK_AUTH_TOKEN`, voir `.env.example`).
- **Précision des clics avec les modèles Qwen** : ces modèles raisonnent
  nativement en repère de coordonnées normalisé 0-1000, alors que GhostDesk
  attend par défaut des pixels écran natifs (documenté par GhostDesk) — sans
  correction, les clics atterrissent à côté de leur cible. `mcp-client`
  envoie donc l'en-tête `GhostDesk-Model-Space` (valeur `GHOSTDESK_MODEL_SPACE`,
  défaut `1000`) sur chaque appel HTTP vers GhostDesk (`_run_on_server`,
  `services/mcp-client/app/main.py`). À vider (`GHOSTDESK_MODEL_SPACE=`) si
  le modèle servi passe à un modèle frontière (Claude, GPT-4o), qui travaille
  nativement en pixels écran. Ce fix ne résout pas le grounding en soi (viser
  le bon élément reste imprécis avec un modèle de vision généraliste) — voir
  la limite ci-dessus sur l'absence d'OCR/détection d'éléments UI.

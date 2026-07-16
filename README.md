# agentic-ai-playground

![Logo](logo-agentic-ai-playground.jpg)

Stack Docker Compose pour un agent IA local : Open WebUI → LangGraph Agent →
(Skill Manager / Context Manager / MCP Client) → vLLM.

## Démarrage rapide

```bash
cp .env.example .env
# éditer .env : WORKSPACE_HOST_PATH doit être le chemin ABSOLU de ./workspace sur l'hôte
# (requis car mcp-client monte ce chemin dans des conteneurs qu'il spawn lui-même)

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
skills/     à remplir (un sous-dossier par skill, avec un SKILL.md)
workspace/  partagé avec les serveurs MCP filesystem/git/terminal, ainsi
            qu'avec langgraph-agent pour le journal d'audit (.audit/, voir
            section Supervision humaine)
models/     poids du modèle servi par vLLM
```

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
| `mcp-client` | 8 | registre d'outils, schéma function-calling (description/inputSchema) exposé pour le LLM, appel réel via stdio, erreur 404 sur outil inconnu, appel réel via Streamable HTTP (serveur "desktop"/GhostDesk) avec vérification du bearer token et de l'en-tête `GhostDesk-Model-Space` |
| `mcp-terminal` | 6 | liste blanche de commandes, lecture de fichier (y compris nom avec espace), blocage du path traversal |
| `langgraph-agent` | 47 (+1 test d'intégration live, ignoré par défaut) | boucle d'appel d'outil, non-duplication des messages, endpoint streaming et non-streaming, pause/reprise d'approbation humaine (approuvé, refusé, streaming inclus), non-duplication de l'historique sur plusieurs tours de conversation, repli du raisonnement Ollama/Qwen3 (champ `reasoning`) en balises `<think>`, liaison du schéma d'outils mcp-client au LLM (bind_tools), repli des résultats d'outil image en message multimodal PNG, **politique d'approbation par tiers de réversibilité** (`approval_policy.py` : tiers lecture/réversible/sensible par défaut, override `TIER_READ_TOOLS`/`TIER_REVERSIBLE_TOOLS`/`AUTO_APPROVED_TOOLS` rétrocompatible, outil inconnu toujours sensible, tour 100% tiers auto-approuvés vs tour mixte), **grants de session** (`test_session_grants.py` : premier appel toujours soumis à approbation même avec intention de grant, "approuver pour la session" auto-approuve les appels suivants du même outil, portée strictement par outil, grants perdus après reconstruction simulée du checkpointer, champ `grant_session` de `POST /approve`), **journal d'audit** (`test_audit_log.py` : tool_call tiers réversible auto-approuvé tracé, tiers lecture jamais tracé, seul l'appel auto-approuvé via un grant de session apparaît — pas le premier passé par approbation humaine, filtrage `GET /audit?thread_id=`), endpoints `/pending` et `/approve` pour une approbation par bouton d'UI, fermeture de la balise `<think>` restée ouverte en streaming avant le texte d'approbation, fusion d'un seul bloc `<think>` continu sur plusieurs itérations de la boucle d'outils auto-approuvés, notice explicite quand MAX_TOOL_ITERATIONS coupe un run avec un tool_call encore en attente, garde-fou `AUTO_APPROVAL_STREAK_LIMIT` forçant un passage humain après N tours auto-approuvés consécutifs (avec réarmement du compteur après approbation). `tests_integration/` (séparé, non mocké, opt-in via `RUN_LIVE_LLM_TESTS=1`) : non-régression de la dérive du LLM réel sur "va sur google.fr" (longueur de réponse, répétition de trigrammes), vérifiée aussi bien en échouant sur l'ancien Modelfile trop agressif qu'en passant sur le Modelfile corrigé |

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
- **vLLM et le GPU** : aucune inférence réelle, aucun test de charge.
- **Function calling streamé par un vrai vLLM** : le format exact peut varier
  légèrement selon le modèle servi (Qwen, Devstral, etc.) par rapport au
  format simulé dans les tests ; une vérification contre un déploiement vLLM
  réel est recommandée avant mise en production.

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
- **Les outils de capture d'écran/clic guidé de `ghostdesk` ne sont pas
  exploitables par l'agent actuel** : le modèle servi (Qwen2.5-Coder) n'est
  pas multimodal, donc l'interprétation de captures d'écran nécessiterait un
  LLM avec capacité vision — non fait ici.
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

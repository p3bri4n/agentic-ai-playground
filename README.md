# agentic-ai-playground

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
workspace/  partagé avec les serveurs MCP filesystem/git/terminal
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
| `mcp-client` | 6 | registre d'outils, appel réel via stdio, erreur 404 sur outil inconnu, appel réel via Streamable HTTP (serveur "desktop"/GhostDesk) avec vérification du bearer token |
| `mcp-terminal` | 6 | liste blanche de commandes, lecture de fichier (y compris nom avec espace), blocage du path traversal |
| `langgraph-agent` | 14 | boucle d'appel d'outil, non-duplication des messages, endpoint streaming et non-streaming, pause/reprise d'approbation humaine (approuvé, refusé, streaming inclus), non-duplication de l'historique sur plusieurs tours de conversation |

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
`browser`, `desktop`/GhostDesk — sans distinction, décision volontaire pour
rester simple) suspend désormais le graphe LangGraph au lieu de s'exécuter
automatiquement (nœud `require_approval`, `services/langgraph-agent/app/graph.py`).
L'agent répond alors dans la conversation avec un message
`⚠️ Approbation requise pour : ...` ; répondre "approuver" au tour suivant
relance l'exécution réelle, toute autre réponse la refuse (un `ToolMessage`
d'erreur "Rejeté par l'utilisateur" est renvoyé au LLM, qui peut réagir
normalement).

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
  remplacer l'un par l'autre.
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

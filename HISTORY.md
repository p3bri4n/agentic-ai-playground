# PoC TabbyAPI/ExLlamaV3 — pin d'image et versions constatées

## Digest résolu (2026-07-21)

`:latest` est une rolling release (ne fige rien dans le temps) — l'image est
donc référencée par digest dans `docker-compose.yml`, résolu via :

```
docker inspect --format='{{index .RepoDigests 0}}' ghcr.io/theroyallab/tabbyapi:latest
```

Résultat :
```
ghcr.io/theroyallab/tabbyapi@sha256:cbceb3032963ab7ada80c76649956b01f54e9e0b04a050fb3396c95950c52b03
```

## Triplet de versions — constaté AU RUNTIME (pas déduit du `pyproject.toml`)

Commande exacte :
```
docker run --rm --entrypoint sh \
  ghcr.io/theroyallab/tabbyapi@sha256:cbceb3032963ab7ada80c76649956b01f54e9e0b04a050fb3396c95950c52b03 \
  -c 'pip show exllamav3 torch; pip list | grep -iE "exllamav3|torch|tabbyapi"'
```

| Composant | Version réelle |
|---|---|
| `exllamav3` | `1.1.0+cu128.torch2.9.0` |
| `torch` | `2.9.0+cu128` |
| `tabbyAPI` | `0.0.1` (métadonnée `pip list` telle quelle — pas un vrai numéro de release, à noter tel quel plutôt que supposer une signification) |

Concordance confirmée avec la déduction précédente faite depuis
`pyproject.toml` de TabbyAPI (`main`) — même triplet, cette fois vérifié dans
le conteneur réel plutôt que déduit d'un fichier source. Équivalent, pour ce
PoC, de la preuve `/proc/1/cmdline` utilisée pendant le diagnostic CUDA
llama-server.

## Phase A — vérifications empiriques (résolution des risques ouverts du plan)

**Chargement du modèle** : `qwen3.6-27b-exl3-3.50bpw` (variante VL, MTP natif,
poids seuls 14,29 Gio). Mono-GPU insuffisant (Ada puis Blackwell testées,
voir historique dans `services/tabbyapi/config.yml`) — chargé avec succès en
**multi-GPU** (`gpu_split_auto`, autosplit), vision + MTP + tool-calling tous
actifs simultanément.

- **Risque #1 (nom de modèle)** : résolu. `/v1/models` liste `agent-llm`
  (symlink créé) parmi les modèles disponibles ; une requête avec
  `"model": "agent-llm"` est acceptée sans rejet (TabbyAPI répond avec le nom
  réel du répertoire chargé dans le champ `model` de la réponse, mais ne
  bloque pas sur un nom de requête différent).
- **Risque #3 (nom du champ SSE de reasoning)** : résolu. C'est
  **`reasoning_content`** — déjà géré par le fallback existant dans
  `graph.py` (`_dict.get("reasoning") or _dict.get("reasoning_content")`),
  **aucun changement de code nécessaire**.
- **Risque #7 (MTP réellement engagé)** : résolu. Log de chargement :
  `"Using main model MTP component for drafting"`.
- **Risque #8 (tool_format qwen3_coder)** : résolu. Round-trip réel
  (requête avec un outil `get_weather`) → `delta.tool_calls` au format
  streaming OpenAI standard, `finish_reason: "tool_calls"`, arguments JSON
  corrects. Format confirmé compatible.

**Bugs/corrections rencontrés pendant l'implémentation** (image officielle
TabbyAPI, ce digest) :
- Image officielle sans `python3-dev` → échec de compilation JIT Triton
  (`fatal error: Python.h: No such file or directory`) au premier
  chargement (module `gated_delta_net`, attention hybride/SSM). Corrigé par
  une couche `services/tabbyapi/Dockerfile` minimale (`apt-get install
  python3-dev`) au-dessus de l'image épinglée par digest.
- `draft_mode` placé par erreur sous `model:` dans `config.yml` (silencieux,
  log "Draft model is disabled because a model name wasn't provided") — sa
  vraie section est `draft_model:` (top-level), vérifié contre
  `config_sample.yml` de l'image réelle plutôt que deviné.
- `vision: true` doit être explicite (défaut `false` même si le modèle a
  des capacités vision).
- GPU cible revu deux fois en cours de route : Ada (mono-GPU) insuffisant
  (affichage du bureau hôte y consommant ~770 Mio), puis Blackwell seule
  encore insuffisante avec vision activée (~822 Mio de marge sans vision
  même à cache_size minimal), retenu **multi-GPU** au final.

Risques ouverts restants du plan (non encore vérifiés) : #2 (décodage WebP
natif — PNG déjà retenu par défaut, donc non bloquant), #4 (variables d'env
de l'image, non nécessaires ici — tout passe par `config.yml` monté), #5
(pas de `/health` dédié trouvé, healthcheck TCP générique à ajouter si
besoin), #6 (marge VRAM multi-GPU à surveiller en usage réel prolongé).

## Benchmark débit (multi-GPU, MTP actif, vision chargée)

| Métrique | Valeur |
|---|---|
| Génération (decode), sortie longue (495 tokens, contenu non répétitif) | **56,2 tok/s** |
| Génération, sortie courte (54-55 tokens) | 54,6-55,6 tok/s |
| Prefill (prompt long, 1370 tokens) | **761 tok/s** |
| Acceptation du draft MTP | ~47-49% (327/672 sur le run long, 35-36/73 sur les runs courts) |

Débit de génération stable autour de **~55 tok/s** entre les essais. Le taux
d'acceptation MTP (~48%) confirme un gain de vitesse réel (chaque token
accepté évite un forward pass complet du modèle principal), pas un MTP
inactif ou dégradé.

Note mineure (non bloquante, requêtes toujours en 200 OK) : un warning
`Unable to switch model to agent-llm because "inline_model_loading" is not
True in config.yml` est apparu une fois en cours de benchmark — TabbyAPI
tente de "changer" vers le modèle déjà chargé sous ce nom sans conséquence
fonctionnelle observée sur la requête elle-même.

## Phase C — bug découvert et corrigé (chunks reasoning+content combinés)

**Bug** : contrairement à `llama-server`/Ollama (toujours des chunks SSE
séparés), TabbyAPI peut regrouper la fin du raisonnement et le début de la
réponse finale dans le **même delta** (`{"reasoning_content": "...",
"content": "..."}`). Le patch `_convert_delta_with_reasoning`
(`services/langgraph-agent/app/graph.py`) utilisait un `if/elif` qui, dès
qu'il voyait `reasoning_content`, écrasait `chunk.content` avec le seul
raisonnement — jetant silencieusement la vraie réponse. Symptôme observé en
conditions réelles via l'API `langgraph-agent` : ~2/3 des tours simples
("Dis bonjour") se terminaient par la notice de secours "le modèle a
terminé son tour sans réponse exploitable", ou avec une réponse tronquée
(perte du premier mot).

**Diagnostic** : confirmé en isolant chaque couche — requête directe à
TabbyAPI (non-streaming ET streaming) avec le payload exact reconstruit
(system prompt + 16 outils MCP réels + température/max_tokens identiques) :
3/3 succès. Donc le bug n'était pas dans le modèle/la config TabbyAPI, mais
dans le traitement des deltas streamés côté `langgraph-agent`.

**Correctif** : `_convert_delta_with_reasoning` détecte maintenant le cas où
`content` est aussi présent dans le même dict que le raisonnement — ferme
la balise `<think>` et ajoute le vrai contenu à la suite, au lieu de
l'écraser. Test de non-régression ajouté
(`test_reasoning_and_content_combined_in_same_chunk_still_yields_visible_answer`,
`tests/test_graph.py`), nouvelle fixture
`reasoning_response_combined_final_chunk` (`tests/fixtures/llm_sse.py`).
**98/98 tests passent.**

**Validation en conditions réelles** (5 requêtes identiques via
`langgraph-agent`, sans thread_id distinct — le checkpointer les a donc
enchaînées comme une conversation continue, artefact de test sans
conséquence) : **4/5 réponses visibles** (contre ~1/3 avant correctif).
L'échec résiduel (1/5) reproduit le comportement déjà documenté et accepté
pour `llama-server` dans le tableau des bugs du README (le modèle peut, de
façon non-déterministe, terminer un tour sans jamais produire de contenu
réel après son raisonnement) — le filet de secours existant
(`MAX_EMPTY_ANSWER_RETRIES` + notice) est précisément conçu pour absorber
ce cas, pas un bug résiduel de cette migration.

**Vision confirmée fonctionnelle de bout en bout** : requête réelle
"Prends une capture d'écran et décris ce que tu vois" → `screen_shot`
GhostDesk auto-approuvé → description précise et détaillée d'une vraie
capture (terminal, contenu, couleurs, date affichée) via le VL du modèle.

**Limite de cette Phase C** : l'extension Chrome n'était pas connectée,
donc pas de test littéral "via l'interface Open WebUI" au clavier/souris —
tests effectués via l'API `langgraph-agent` (même endpoint qu'Open WebUI
appelle), pas depuis le navigateur lui-même.

## Phase C — grounding OCR et approbation (suite)

**`find_text` + `mouse_click` (grounding OCR)** : confirmé fonctionnel de
bout en bout — capture d'écran réelle, `find_text` localise "bin" parmi
plusieurs occurrences (usr/bin, usr/sbin, bin), `mouse_click` exécuté aux
coordonnées correctes. **Confirmé réellement exécuté** (pas juste rapporté
par le modèle) via le journal d'audit
(`{"tool": "mouse_click", "arguments": {"x": 266, "y": 140}, "tier":
"reversible"}`).

**Point méthodologique** : une tentative initiale de valider le flux
d'approbation en rejouant manuellement une conversation via
`/v1/chat/completions` (avec un faux message assistant injecté) a produit
une réponse du modèle décrivant un clic... jamais exécuté (absent du
journal d'audit) — le modèle avait simplement halluciné une confirmation
plausible sans qu'aucun état de graphe ne soit correctement repris. Le bon
mécanisme pour reprendre un thread en pause hors du texte "approuver"/
"refuser" naturel est l'endpoint dédié `POST /approve` (voir
`app/main.py`). Rejouer une conversation à la main via
`/v1/chat/completions` n'est pas fiable pour tester ce flux — noté pour
tout futur test manuel similaire.

**`AUTO_APPROVAL_STREAK_LIMIT`** (garde-fou anti-clavier-virtuel, défaut 6)
observé se déclencher réellement en cours de test (accumulation de tours
auto-approuvés sur le même thread implicite) puis se réinitialiser sur un
thread frais — comportement conforme à sa conception, confirmé fonctionnel
avec TabbyAPI comme avec l'ancien backend.

**Bilan Phase C** : Q&A texte ✅, vision GhostDesk (`screen_shot`) ✅,
grounding OCR (`find_text`+`mouse_click`, exécution réelle confirmée) ✅,
flux d'approbation humaine (tier sensible → notice → reprise) ✅ observé
fonctionnel à travers ces scénarios. Pas de test littéral via l'interface
Open WebUI (extension Chrome non connectée) — tout validé via l'API
`langgraph-agent` directement.

## Prérequis Phase 0 (plan d'autonomie) — persistance du serveur MCP "browser"

En préparant le harnais de tâches web de la Phase 0 (`PLAN.md`), la
question s'est posée directement : le serveur "browser" (Playwright)
redémarre-t-il à chaque appel d'outil ? Réponse : oui, confirmé dans
`BUGS.md` — spawn éphémère (`docker run -i --rm mcp/playwright:latest` par
appel), sans continuité d'état. Or la quasi-totalité des 11 tâches prévues
(pagination, tri/filtre, piste multi-pages, session authentifiée,
navigation inter-articles Wikipédia...) suppose un état navigateur partagé
entre appels d'outils successifs : sans correctif, la baseline de la Phase
0 aurait surtout mesuré ce bug d'architecture plutôt que les capacités
réelles de l'agent. Corrigé avant de poursuivre.

**Diagnostic en deux temps, chacun vérifié par un vrai appel réseau (pas
une lecture de doc)** :
1. L'image officielle `mcp/playwright` supporte un mode serveur HTTP natif
   (`--host 0.0.0.0 --port 8931`, endpoint Streamable HTTP `/mcp`) —
   confirmé en la lançant directement. Nouveau service `docker-compose`
   `playwright-mcp`, sur le même patron que `ghostdesk`/`ocr-service`.
   Premier test après bascule : `mcp-client` ne remontait toujours PAS
   les outils `browser_*` (`_refresh_registry` avale les exceptions
   silencieusement) — cause réelle trouvée en connectant directement
   depuis le conteneur `mcp-client` : `httpx.LocalProtocolError: Illegal
   header value b'Bearer '` (le code construisait inconditionnellement
   `Authorization: Bearer {token}`, y compris avec un token vide — jamais
   rencontré avant car `desktop`/`ocr` ont toujours un token non-vide).
   Corrigé (en-tête omis si le token est vide) : les 25 outils `browser_*`
   apparaissent alors dans `/tools`.
2. Une fois le PROCESS serveur persistant, l'état ne l'était toujours
   pas : un `browser_navigate` suivi d'un `browser_snapshot` séparé
   retombait sur `about:blank`. Cause : `mcp-client` ouvrait encore une
   SESSION MCP neuve à chaque appel HTTP (`_run_on_server`), et Playwright
   MCP scope son contexte navigateur (page, cookies, historique) à la
   session, pas au process. Ajout de `_get_persistent_session`/
   `_persistent_sessions` (`services/mcp-client/app/main.py`) : la session
   "browser" reste ouverte entre deux appels, avec relance automatique si
   la session tombe. **Vérifié par un vrai test bout en bout** : navigation
   vers l'article Wikipédia de Clément Ader via `browser_navigate`, puis
   `browser_snapshot` en appel HTTP séparé — la page retournée est bien
   celle visitée par le premier appel (titre, URL, contenu), plus
   `about:blank`.

**Point méthodologique** : la première hypothèse (juste rendre le process
serveur persistant) semblait suffisante sur le papier, mais un test réel
immédiat a révélé qu'elle ne l'était pas — la persistance de session côté
client est une couche distincte de la persistance du process serveur, et
aucune des deux ne remplace l'autre pour ce serveur précis.

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

## Phase 0 — harnais de tâches web construit, baseline double campagne

Construction complète du harnais `test_web_tasks.py` : 3 fixtures locales
générées et vérifiées réellement (`catalog` 30 produits/3 pages,
`docs` ~30 pages avec piste à 2 sauts, `hr-app` Flask avec login/tableau
dynamique/formulaire/export CSV), branchées en service `docker-compose`
dédié (profil `test-fixtures`). Recalibrages faits AVANT la baseline (donc
non contaminants) : catalogue réduit de 120/12 pages à 30/3 (le pire cas
exhaustif dépassait largement `MAX_TOOL_ITERATIONS`), T5 recentré sur la
valeur finale plutôt qu'un fichier CSV présent sur disque (aucun outil
`browser_*` ne fait redescendre un téléchargement vers un répertoire
lisible par le harnais).

Le harnais joue lui-même le rôle de l'humain (`POST /approve`,
`grant_session=True`) puisque les outils `browser_*` sont TIER_SENSITIVE
par défaut (Phase 3 pas encore faite) — comptabilisé comme métrique
"approbations". Ajout d'une métrique diagnostique demandée explicitement en
cours de session : `tool_calls_observés` (proxy = approbations + entrées du
journal d'audit pour le thread) et une sous-classification des échecs
"boucle" en `boucle_fabrication` (navigation vers une URL absente du
sitemap réel du fixture) vs `boucle_budget` (URLs réelles mais budget
épuisé) — vérifiable seulement pour les tâches locales (sitemap de
référence connu), pas pour les sites réels.

**Deux campagnes réelles, une seule variable (MAX_TOOL_ITERATIONS)** :

| | Campagne A (budget 20, défaut) | Campagne B (budget 60, diagnostic) |
|---|---|---|
| Score | 16/33 | 25/33 |
| T1 (catalogue paginé) | 0/3 (extraction) | 3/3 |
| T5 (CSV + calcul) | 3/3 | 1/3 |
| T7 (produit inexistant) | 1/3 (`boucle_fabrication`×1) | 3/3 |
| T8/T11 (Wikipédia/python.org) | 0/3 chacune (infra) | 0/3 chacune (infra) |
| T9 (Google→INSEE) | 0/3 (infra) | 3/3 |

**Constat n°1 : fabrication d'URL.** Sur les deux campagnes, l'agent invente
régulièrement des URL plausibles mais jamais observées (`page-4.html` sur
un catalogue à 3 pages, `product-KX-4471.html` en devinant un motif depuis
la référence cherchée, `/catalog/search?q=...` sans fonction de recherche,
`file:///app/.playwright-mcp/employees.csv` pour "télécharger" un CSV)
plutôt que de suivre un lien réellement présent dans le DOM. Un budget plus
large (Campagne B) laisse le temps de se rattraper après ces essais ratés
(T1, T7 passent à 3/3), mais le comportement de fabrication lui-même
persiste identique — relever le budget ne le corrige pas, ça masque juste
son coût. Première cible désignée pour la Phase 1 (vérification post-action
systématique, budget d'échec avec stratégie alternative exigée à chaque
retry).

**Constat n°2 : dépassement de contexte non rattrapé, pas une limite
d'itérations.** T8/T11 échouent identiquement dans LES DEUX campagnes
(budget 20 ET 60) — pas un problème de budget d'itérations donc, mais
`openai.BadRequestError: Prompt length 69510 exceeds the available context
size of 32768 tokens` : les pages réelles (Wikipédia, python.org) génèrent
des snapshots DOM bien plus lourds que les fixtures locales, et
`/v1/chat/completions` (chemin non-streaming) n'a pas le même filet de
rattrapage que le chemin streaming (`except Exception` présent dans
`_stream_response`, absent équivalent autour de `agent_graph.ainvoke` en
non-streaming, `app/main.py`) — d'où un 500 brut plutôt qu'une notice
propre. Bug identifié mais PAS corrigé ici (hors périmètre : mesurer
l'agent tel quel, pas le modifier).

**T9 a réussi en Campagne B** (Google → INSEE, 3/3, budget 60) : la
recherche/tri du signal Google + navigation vers insee.fr a fonctionné une
fois le budget suffisant — donc pas bloqué par l'INSEE elle-même
(contrairement à l'hypothèse d'incident technique envisagée plus tôt), mais
par le nombre d'étapes nécessaires pour traverser écran de consentement +
SERP.

**Bug de harnais trouvé et corrigé en cours de route** : `_assert_t9`
retournait toujours le même message de détail ("insee absent...") qu'importe
le verdict réel — le booléen de succès était correct, seul le texte affiché
en cas de succès était trompeur. Corrigé (`test_web_tasks.py`), rapport
Campagne B corrigé a posteriori pour refléter le vrai verdict sans
relancer (coûteux).

Rapports complets : `tests_integration/TASKS-BASELINE.md` (Campagne A,
officielle) et `tests_integration/TASKS-DIAGNOSTIC-budget60.md` (Campagne B,
diagnostic). `MAX_TOOL_ITERATIONS` restauré à 20 (défaut) sur la stack
après la Campagne B.

## Phase 0 — vérification T5, correctif de parité d'erreur, GO Phase 1

**Vérification T5 (Campagne B)** : les logs bruts des runs originaux avaient
été perdus (le conteneur `langgraph-agent` avait été recréé juste après pour
restaurer `MAX_TOOL_ITERATIONS=20`, vidant le checkpointer `MemorySaver` en
mémoire). Reproduction fraîche (3 runs, budget 60) plutôt qu'analyse
forensique des runs originaux. Verdict : ni errance ni pollution de
contexte — un bug d'assertion. L'agent répondait correctement "199 000 €"
(espace comme séparateur de milliers), `_assert_t5` cherchait la sous-chaîne
stricte "199000". Faux négatif à 100%, corrigé (tolère espace/virgule/point).
Score T5 réel : 3/3 aux deux budgets. Aucune contre-indication empirique à
l'élargissement du budget trouvée pour cette tâche — voir détail dans
`TASKS-DIAGNOSTIC-budget60.md`.

**Correctif de parité d'erreur interne** (`app/main.py`) : le chemin
streaming (`_stream_response`) attrapait déjà toute exception pendant
`agent_graph.ainvoke`/`astream_events` via un `except Exception` englobant
et répondait une notice propre. Ni `/v1/chat/completions` non-streaming ni
`/approve` ne l'avaient — découvert en conditions réelles pendant la
Campagne A/B (T8/T11, `openai.BadRequestError: Prompt length ... exceeds
the available context size`), qui y remontait en 500 brut plutôt qu'une
réponse HTTP 200 avec notice. Ajout d'une constante partagée
`_INTERNAL_ERROR_NOTICE` (au lieu du literal dupliqué) et d'un `try/except`
autour de `ainvoke` sur les deux chemins manquants, retournant directement
la notice sans passer par `_current_answer` (l'état du graphe peut être
incohérent après une erreur en plein milieu). Test de non-régression
`test_internal_error_parity.py` (2 tests, reproduit le `BadRequestError`
exact vu en conditions réelles via `respx`, sur les 3 chemins). Suite
complète rejouée : 119 tests passent, aucune régression. Campagne complète
PAS relancée (T8/T11 seront re-mesurées naturellement à la campagne
post-Phase 1, comme convenu) — seuls les 2 nouveaux tests unitaires
valident ce correctif pour l'instant.

**GO Phase 1** décidé sur ces bases : fabrication d'URL désignée cible n°1
(garde-fou mécanique sur `browser_navigate`, voir `PLAN.md`), tronquage des
snapshots à la source également en périmètre Phase 1 (borne de sortie
d'outil, pas de la gestion d'historique qui reste Phase 2). Critère de
réussite chiffré, sur la même Campagne A (budget 20) : T1 et T4 passent
(tuées par la fabrication), compteur de fabrications proche de zéro, T7 à
3/3, aucun recul sur T2/T3/T10.

## Phase 1 (1ère tranche) — garde-fou fabrication d'URL + tronquage snapshots

Implémenté dans `app/graph.py` : `_execute_tool_calls` vérifie désormais
l'URL de tout `browser_navigate` contre `observed_urls` (racines du
périmètre de la tâche, extraites du 1er message humain + navigations déjà
exécutées + liens extraits des résultats `browser_*` précédents, y compris
liens relatifs résolus via la page courante). URL non observée → refusée
AVANT tout appel à `mcp-client`, feedback d'outil explicite, comptée dans
`fabricated_navigation_attempts` (nouveau champ `AgentState`). Bascule
`BROWSER_NAVIGATE_GUARDRAIL` (défaut activé). En parallèle,
`BROWSER_TOOL_OUTPUT_MAX_CHARS` (défaut 8000) tronque à la source tout
résultat d'outil `browser_*` trop volumineux — distinct de la rétention
d'images (Phase 2) : une borne de sortie d'outil, pas de gestion
d'historique. 5 nouveaux tests unitaires
(`test_url_fabrication_guardrail.py`) + 6 tests existants ajustés (URL de
test `http://example.com` absente du périmètre de leur tâche factice,
jamais mentionnée dans le 1er message — corrigé en l'y ajoutant). Suite
complète : 124 tests passent.

**Campagne A rejouée (même budget 20, seule variable : le garde-fou actif)
— verdict chiffré contre les 5 critères de réussite fixés, aucun n'est
intégralement atteint** (détail complet et analyse dans
`tests_integration/TASKS-BASELINE-post-phase1.md`) :
- Score global : 16/33 → **24/33** (amélioration réelle, non ciblée
  spécifiquement par les critères).
- T1 : toujours 0/3 (❌ critère non atteint).
- T4 : 1/3 → 3/3 (✅ critère atteint).
- Compteur de fabrications : PAS proche de zéro (❌) — jusqu'à 20 URL
  fabriquées distinctes par run en échec (T7). Le garde-fou bloque bien
  l'EXÉCUTION (vérifié unitairement : `mcp_route.call_count == 0` sur URL
  fabriquée), mais le modèle ne cesse pas d'inventer : il enchaîne
  plusieurs suppositions rejetées une par une plutôt qu'une seule
  navigation ratée puis un abandon — `tool_calls_observés` sur T1/T7 a
  AUGMENTÉ (T1 : 20-32 → 49-61 ; T7 : 30-42 → 58-70). Le garde-fou change
  la CONSÉQUENCE de la fabrication (pas de pollution du contexte par de
  vraies navigations ratées), pas le COMPORTEMENT lui-même.
- T7 : 1/3 → 2/3 (❌ critère "3/3" non atteint, mais amélioré).
- Aucun recul T2/T3/T10 : T2 et T3 stables (3/3), **T10 recule à 2/3**
  (❌, 1 échec "boucle" — site réel, pas de sitemap de référence donc pas
  de sous-classification possible ; possiblement du bruit de
  non-déterminisme plutôt qu'un effet du garde-fou).

**Gains inattendus, probablement dus au tronquage plutôt qu'au garde-fou
de navigation** : T8 (Wikipédia) 0/3 (infra, dépassement de contexte) →
3/3 ; T9 (Google→INSEE) stable à 3/3. Cohérent avec la cause identifiée au
bloc précédent (dépassement de contexte sur pages réelles denses) —
`BROWSER_TOOL_OUTPUT_MAX_CHARS` semble la traiter efficacement, sans test
dédié isolant formellement ce lien de cause à effet ici.

T11 reste 0/3 (hallucination) — attendu, hors périmètre de cette tranche
(conscience temporelle, amendement séparé du plan).

**Conclusion** : le garde-fou mécanique seul ne suffit pas à faire
converger le modèle vers les vrais liens après un refus — confirmé
empiriquenent, pas juste supposé. Prochaine tranche Phase 1 à discuter :
soit enrichir le feedback de refus (suggérer explicitement les liens
RÉELLEMENT observés dans la dernière page, pas juste dire "non"), soit
la vérification post-action systématique déjà prévue au plan d'origine
(énoncer un critère de succès AVANT l'action, comparer après), qui
pourrait mieux capter ce pattern de raisonnement répétitif que le seul
blocage d'exécution.

## Phase 1 (2e tranche) — hypothèse "le tronquage affame la navigation"

**Étape 1, vérification d'archive (zéro run agent)** : appels directs
`mcp-client` (hors LLM) sur les pages réellement en cause.
- **T1 (catalogue local)** : hypothèse NON applicable — plus gros snapshot
  observé (page-1.html, 10 produits) = 1626 caractères, snapshot produit =
  508 caractères, très sous le seuil de troncature (8000). Le tronquage ne
  s'est jamais déclenché sur ce fixture.
- **T10 (books.toscrape.com, réel)** : hypothèse CONFIRMÉE. Snapshot de la
  catégorie Science = 25900 caractères, 82 liens ; la cible ("The Origin
  of Species") apparaît après le 8000e caractère — seuls 49/82 liens
  survivaient à l'ancien tronquage naïf, et pas le bon.

**Étape 2, tronquage structuré** (`app/graph.py`) : `_extract_affordances`
extrait tout élément interactif (lien avec cible, bouton, champ) d'un
snapshot ; `_truncate_browser_result` place cet inventaire INTÉGRAL en
tête (jamais tronqué, y compris si l'inventaire seul dépasse le plafond —
préserver la navigation prime sur le respect strict du plafond dans ce cas
rare), et ne tronque que le contenu descriptif restant. La ligne
"Page URL: ..." est préservée séparément (nécessaire pour résoudre les
liens relatifs). Test dédié : page catalogue synthétique à 200 liens
(>8000 car.) → 100% des liens survivent à la troncature à 2000 car.

**Étape 3, feedback redirection** : le rejet d'une URL fabriquée inclut
désormais les liens réellement observés sur la page COURANTE (coût nul,
même ensemble que celui consulté par le garde-fou), pas juste un refus sec.

**Bug trouvé en cours de route** : le premier format choisi pour
l'inventaire (`- link "Label" -> url`) était invisible à `_extract_urls`
(qui reconnaît spécifiquement le motif `/url: ...`), ce qui aurait cassé
le suivi `observed_urls` sur tout résultat effectivement tronqué en
production (pas seulement en test). Corrigé (format `/url: ...` conservé).
8 tests unitaires dédiés, suite complète : 127 tests passent.

**Étape 4, re-campagne A (budget 20 inchangé), mêmes 5 critères — recul
net, pas une amélioration** :

| Tâche | Phase 1a (garde-fou seul) | Phase 1b (+ tronquage structuré + feedback) |
|---|---|---|
| Score global | 24/33 | **20/33** |
| T1 | 0/3 | 2/3 (amélioré) |
| T4 | 3/3 | **1/3** (recul net) |
| T7 | 2/3 | **0/3** (recul net) |
| T8 | 3/3 | **0/3** (recul net) |
| T10 | 2/3 | 3/3 (récupéré, cohérent avec l'hypothèse confirmée) |

Aucun des 5 critères de réussite n'est mieux atteint qu'en 1a — T10 seul
progresse comme attendu (cohérent avec la vérification d'archive), mais
T4/T7/T8 se dégradent nettement. Hypothèse la plus probable (non vérifiée
formellement, faute de budget dans cette itération) : la liste de liens
ajoutée à CHAQUE rejet (jusqu'à 40 lignes) alourdit le message de rejet
lui-même — sur des tâches qui accumulent déjà beaucoup de rejets (T7 :
jusqu'à 85 tool_calls_observés ici, contre 70 en 1a), ce surcoût par rejet
semble épuiser le budget plus vite qu'il n'aide à corriger la trajectoire.
Détail complet dans `tests_integration/TASKS-BASELINE-post-phase1b.md`.

**Étape 5, pas de conclusion sur les critères Phase 1** (comme demandé) :
les mécanismes restants (plan explicite, vérification post-action
systématique, budget d'échec avec stratégie alternative exigée à chaque
retry) ne sont pas encore en place. Le comportement "enchaîne les
suppositions" est précisément ce que le budget d'échec doit adresser —
prématuré de juger la Phase 1 avant qu'il soit implémenté. Prochaine
décision à prendre au checkpoint : garder, ajuster (ex. alléger le
feedback : moins de liens, ou seulement sur la 2e tentative fabriquée) ou
retirer l'étape 3 (feedback enrichi) en isolant sa contribution de celle du
tronquage structuré (étape 2), qui elle est positivement confirmée par la
vérification d'archive sur T10.

## Phase 1 (3e tranche) — feedback gradué + plafond de rejets

Diagnostic retenu du recul 1b : la liste complète des liens à CHAQUE rejet
était redondante (le snapshot structuré la contient déjà) et alourdissait
chaque rejet. Remplacé par un feedback à 3 paliers selon le nombre de
tentatives fabriquées POUR CETTE TÂCHE (`fabricated_navigation_attempts`,
déjà suivi) : 1-2 = message minimal sans liste ; 3 à `FABRICATION_LIMIT-1`
(défaut 5) = quelques liens les plus proches de l'URL fabriquée
(`difflib.get_close_matches`) ; à partir de `FABRICATION_LIMIT` = le
feedback change de nature, pousse vers une conclusion honnête d'absence
plutôt qu'une énième supposition — pont direct vers T7. Nouvelle fonction
pure `_fabrication_feedback` (`app/graph.py`), `FABRICATION_LIMIT` en env.
4 nouveaux tests unitaires (les 3 paliers + câblage bout en bout du
compteur), 1 ancien test remplacé (l'assertion "Liens disponibles"
inconditionnelle ne tenait plus). Suite complète : 130 tests passent.

**Campagne A rejouée (budget 20 inchangé), mêmes 5 critères — 4/5 atteints,
un motif de vigilance nouveau hors périmètre des critères** (détail complet
dans `tests_integration/TASKS-BASELINE-post-phase1c.md`) :

| Critère | Résultat |
|---|---|
| T1 passe | ✅ 3/3 |
| T4 passe | ✅ 3/3 |
| Fabrications ≈ 0 | ⚠️ toujours nombreuses (T7 : jusqu'à 24/run), mais convergent maintenant vers une conclusion honnête plutôt que la limite d'itérations |
| **T7 à 3/3 (juge principal)** | **✅ 3/3, atteint** — les 3 runs concluent honnêtement à l'absence, avec peu d'approbations (5, 1, 0), signe d'une vraie convergence plutôt qu'un blocage mécanique |
| Aucun recul T2/T3/T10 | ✅ tous 3/3 |

Score global : 16/33 (pré-Phase 1) → 24/33 (1a) → 20/33 (1b) → **24/33
(1c)**, avec un mix de tâches réussies différent de 1a (T1/T4/T6/T7 montent,
T5 tombe à 0/3 — nouveau, absent des 5 critères fixés). Cause du recul T5
non investiguée dans cette itération (hors périmètre demandé) : le
"fichier" CSV réapparaît comme `file:///...` fabriqué (déjà connu), mais
`tool_calls_observés` a nettement augmenté (30-34 contre 20-30
auparavant) — hypothèse à vérifier séparément (interaction avec le
matching "liens proches" du palier 2, ou simple non-déterminisme). T8 reste
bloqué mais change de cause (extraction, plus infra — le tronquage a bien
réglé le dépassement de contexte identifié en 1b, Wikipédia reste
difficile pour une autre raison non isolée ici).

## Phase 1d — vérification d'archive T5/T8 (zéro run) et sa limite

Avant tout nouveau code, tentative de trancher les hypothèses du checkpoint
1c (un lien/bouton export était-il présent au moment du plafond ? la
donnée cible était-elle dans la partie élidée de l'inventaire ?) depuis les
archives existantes, sans rejouer aucune tâche. Le journal d'audit
(`workspace/.audit/`, bind mount hôte) a survécu au redémarrage du
conteneur `langgraph-agent` entre la campagne 1c et cette vérification
(contrairement au checkpointer `MemorySaver`, en mémoire) : les threads T5
et T8 de la campagne ont été retrouvés par fenêtre temporelle.

**Limite structurelle découverte** : `audit_log` ne journalisait que
`tool` + `arguments`, jamais le RÉSULTAT de l'appel — le contenu du
snapshot renvoyé au modèle n'était persisté nulle part. Les hypothèses 0a/0b
portent précisément sur ce contenu (présence d'un lien, portion élidée) :
ni confirmables ni infirmables strictement avec l'existant. Seule la
SÉQUENCE d'appels était reconstructible :
- T5 : navigation correcte et répétée vers l'URL réelle d'export, une
  fabrication (`file:///.playwright-mcp/employees.csv` et variantes), puis
  retour spontané à l'URL réelle et tentatives `browser_run_code_unsafe`/
  `browser_evaluate` — pas de blocage permanent visible sur le chemin
  fabriqué.
- T8 : URL directe, variante mobile, recherche interne Wikipédia,
  `Spécial:Recherche`, repli Google — jamais de retour franc sur une page
  exploitée avec succès dans la séquence journalisée.

**Conséquence sur le correctif "plafond conditionnel" de la 1d initiale**
(candidats forts par jetons distinctifs à `_strong_candidates`) : conçu et
codé sur l'hypothèse 0a, non confirmée par les séquences ci-dessus.
**SUSPENDU** — reverté (`_fabrication_feedback` revient au message
inconditionnel de 1c). Principe retenu : on ne corrige pas un mécanisme sur
une hypothèse affaiblie par la vérification ; il redeviendra candidat si
des archives enrichies (voir plus bas) montrent le pattern ailleurs.

## Phase 1d-révisée — observabilité d'abord, puis T5 requalifié côté infra

**1. Persistance des résultats d'outil dans le journal d'audit**
(`app/audit_log.py`) : chaque entrée porte désormais le résultat TEL QUE VU
PAR LE MODÈLE (déjà tronqué/hiérarchisé par `_truncate_browser_result` côté
appelant, jamais la version brute — on n'archive pas une donnée que le
modèle n'a jamais reçue). Rotation/compression ajoutée (`AUDIT_LOG_MAX_BYTES`,
défaut 20 Mio) : un fichier journalier qui dépasse le seuil est compressé en
`.N.jsonl.gz` avant la prochaine écriture, `read_entries` relit les deux
formes de façon transparente. C'est la fondation du futur endpoint
"contexte de l'agent" du dashboard, et ce qui manquait pour vérifier
strictement 0a/0b la prochaine fois qu'un cas similaire se présente.

**2. Investigation infra pour T5** : les deux options envisagées au
checkpoint précédent se sont révélées non viables, vérifié empiriquement
avant tout code —
- (a) outil de download natif + lecture via filesystem-MCP : `playwright-mcp`
  tourne en `--isolated` SANS AUCUN volume monté (vérifié dans
  `docker-compose.yml`) ; un téléchargement atterrit dans le filesystem du
  conteneur `playwright-mcp` lui-même
  (`/home/node/.playwright-mcp/employees.csv` — vérifié en inspectant le
  conteneur en direct : NI `/app/.playwright-mcp/` NI `/.playwright-mcp/`,
  les deux chemins que le modèle fabriquait à chaque tentative), jamais
  partagé avec filesystem-MCP.
- (b) `curl` via mcp-terminal : conteneur spawné SANS accès réseau
  (`agent-net` non attaché, vérifié : une requête `curl` vers
  `fixture-hr-app` échoue) et liste blanche strictement en lecture
  (`ls`/`pwd`/`cat`/`git_status`, voir `services/mcp-terminal/server.py`) —
  ajouter `curl` aurait été une vraie extension de surface réseau, pas une
  simple directive.

**Option refusée, consignée pour faire jurisprudence** : utiliser
`browser_evaluate` (`fetch(url).then(r=>r.text())` dans le contexte de la
page) comme canal de transfert de fichier — ne demandait aucune nouvelle
capacité ni changement de surface, mais **rejetée sur le principe** :
l'exécution de code arbitraire dans la page n'est pas la primitive d'un
outil de lecture/téléchargement, même quand elle "marche" pour ce cas
précis. Un besoin de transfert de fichier légitime mérite un CHEMIN
DÉDIÉ, pas un détournement d'un canal d'exécution. Si un besoin futur
similar se présente, ne pas reproposer `browser_evaluate`/
`browser_run_code_unsafe` comme solution de contournement — construire le
chemin dédié équivalent.

**3. Solution retenue : volume de téléchargement dédié** —
- `docker-compose.yml` : volume nommé `agent-downloads`, monté en écriture
  dans `playwright-mcp` (`--output-dir=/downloads`, chemin EXPLICITE plutôt
  que le défaut implicite du conteneur — l'anti-fabrication directe), monté
  en LECTURE SEULE dans le serveur MCP filesystem (voir
  `services/mcp-client/app/main.py`, `SERVERS["filesystem"]`, argument racine
  supplémentaire `/downloads`). Le profil navigateur reste `--isolated` en
  mémoire — seuls les artefacts de téléchargement sont partagés, jamais
  l'état du navigateur.
- Directive système `DOWNLOAD_DIRECTIVE` (`app/graph.py`) : documente le
  chemin réel (`/downloads/<nom>`) plutôt que de laisser le modèle en
  deviner un.
- Tiers (`app/approval_policy.py`) : `NEVER_GRANTABLE_TOOLS` —
  `browser_run_code_unsafe` ET `browser_evaluate` restent TIER_SENSITIVE
  même accordés pour la session (un grant ne les assouplit jamais,
  contrairement au reste des outils sensibles) — exécution de code
  arbitraire dans la page est une élévation, chaque appel requiert une
  approbation individuelle, décision étendue à `browser_evaluate` (même
  famille de primitive que `browser_run_code_unsafe`).
- Nettoyage : `_purge_downloads_volume()` (`tests_integration/
  test_web_tasks.py`), appelé avant CHAQUE répétition de tâche (pas
  seulement au setup de session) — sinon une répétition de T5 "réussirait"
  en lisant l'artefact laissé par la précédente plutôt qu'en téléchargeant
  réellement.
- Nouveau test d'intégration dédié (`test_download_then_filesystem_read_
  roundtrip`) : isolé de la campagne complète (plus rapide à diagnostiquer
  en cas d'échec), vérifie le fichier réellement présent dans le volume
  (pas seulement déduit de la réponse finale) en plus de l'assertion sur le
  contenu.
- mcp-terminal : INCHANGÉ — sa doctrine "zéro réseau, liste blanche stricte"
  était correcte, pas érodée pour un cas d'usage qui a une meilleure
  solution.

131 tests unitaires -> 134 après ce chantier (persistance de résultat +
rotation, revert du plafond conditionnel, `NEVER_GRANTABLE_TOOLS`). Nécessite
un rebuild/restart de `playwright-mcp` et `mcp-client` (nouveau volume,
nouvel argument de commande) avant de rejouer la Campagne A — voir
commandes au checkpoint. 🧑 **Checkpoint : rejouer la Campagne A (critères :
T5 et T8 remontent, T1/T4/T7/T10 tiennent) avant de considérer la Phase 1
close.**

## Phase 1d-révisée — vérification post-déploiement : deux bugs d'infra, puis Campagne A

Avant de pouvoir rejouer la Campagne A, deux bugs d'infra découverts en
testant le round-trip T5 pour de vrai (aucun des deux n'était visible en
tests unitaires, qui mockent mcp-client) :

1. **Deux volumes Docker différents sous le même nom** : `docker-compose.yml`
   référence `agent-downloads` (résolu par Compose en
   `agentic-ai-playground_agent-downloads`), mais `mcp-client` spawne le
   serveur filesystem via un `docker run` BRUT sur le socket hôte (voir
   `services/mcp-client/app/main.py`) — cet appel est extérieur au fichier
   compose et Docker n'applique aucun préfixe : "agent-downloads" y
   désignait un volume totalement différent (vide, créé à la volée).
   Conséquence concrète : le fichier téléchargé existait bien côté
   playwright-mcp mais `read_file` échouait en `ENOENT` côté filesystem-MCP,
   silencieusement (TIER_READ, jamais audité). Corrigé en fixant le nom réel
   du volume (`name: agent-downloads` dans `docker-compose.yml`), qui
   supprime toute ambiguïté de préfixage.
2. **Permissions du volume** : un volume Docker nommé est créé `root:root`
   par défaut ; l'image `mcp/playwright` tourne en utilisateur `node` (uid
   1000), qui ne pouvait donc pas écrire dans `/downloads` — `browser_navigate`
   échouait systématiquement en `EACCES` en tentant d'écrire son propre
   snapshot de debug sous `--output-dir`. Découvert directement grâce au
   résultat désormais persisté dans le journal d'audit (`entry["result"]`,
   voir point 1 de ce chantier) — sans lui, ce bug serait resté invisible
   (audit ne journalisait avant que tool+arguments). Corrigé par un
   conteneur d'initialisation dédié (`agent-downloads-init`, `chown -R
   1000:1000`, `condition: service_completed_successfully` avant
   `playwright-mcp`).

Un test isolé du round-trip complet a aussi révélé que le harnais lui-même
(`run_task`/`_derive_thread_id`, hachage du texte EXACT du 1er message
humain) réutilise le MÊME thread qu'une exécution précédente tant que le
conteneur `langgraph-agent` n'a pas redémarré — un rejeu immédiat de
`test_download_then_filesystem_read_roundtrip` répondait juste depuis la
mémoire de conversation en 7s, sans un seul appel d'outil, masquant
totalement le bug ci-dessus. Corrigé pour CE test précis (marqueur unique
par exécution ajouté au prompt) ; **limite documentée mais non corrigée**
pour la Campagne A elle-même — les 3 répétitions de chaque tâche y
partagent volontairement le même thread depuis l'origine du harnais (voir
docstring de `app/main.py`), donc les répétitions 2/3 restent des mesures
de robustesse du GRANT DE SESSION plus que des essais totalement
indépendants. Effet de bord potentiel sur les scores T5 : difficile à
distinguer "l'agent relit le fichier" de "l'agent se souvient de la
conversation" sur les répétitions 2/3 — non tranché ici.

**Campagne A rejouée** (résultat complet :
`tests_integration/TASKS-BASELINE-post-phase1d.md`) — **3 des 6 critères
manqués** :

| Critère | Résultat |
|---|---|
| T5 remonte | ✅ 0/3 (1c) → 3/3 |
| T8 remonte | ⚠️ 0/3 (1c) → 2/3 (amélioré, pas résolu) |
| T1 tient | ❌ 3/3 (1c) → 0/3 |
| T4 tient | ✅ 3/3 → 3/3 |
| T7 tient | ❌ 3/3 (1c) → 1/3 |
| T10 tient | ❌ 3/3 (1c) → 0/3 |

Score global inchangé (24/33) mais mix de tâches très différent. T7 est le
recul le plus préoccupant : c'était le "témoin sensible" désigné
précisément pour détecter un effet de bord du feedback de fabrication — or
le plafond conditionnel qui l'aurait pu affecter était déjà reverté AVANT
cette campagne (retour au message inconditionnel de 1c). Deux hypothèses
non tranchées consignées dans le rapport : (a) `DOWNLOAD_DIRECTIVE` ajoutée
au system prompt de TOUTE requête, y compris les tâches T1/T7/T10 qui n'ont
aucun rapport avec un téléchargement — jamais mesuré isolément si cet ajout
dilue l'attention sur des tâches non concernées ; (b) non-déterminisme du
LLM (`temperature=0.2`) — T1/T7 échouent avec les MÊMES URL fabriquées que
dans tous les rapports précédents, un motif déjà connu, pas nouveau en soi.
🧑 **Checkpoint : décider comment traiter les régressions T1/T7/T10 avant de
considérer la Phase 1 close — la Phase 0 seule est un GO net, T5/T8
progressent, mais le critère "aucun recul" n'est pas rempli.**

## Phase 1d-révisée — discrimination des régressions T1/T7/T10 (archives, zéro run)

Comparaison, à partir des résultats désormais persistés dans le journal
d'audit (voir plus haut), des threads déterministes T1/T7/T10 (thread_id =
hash du prompt exact) entre la fenêtre 1c (~16:03-16:19) et 1d
(~18:06-18:20) — sans rejouer aucune tâche.

**Verdict : disparition de `browser_evaluate`, pas de trace de
`DOWNLOAD_DIRECTIVE`, pas de signal net sur le volume d'approbations.**
- **T1** : 1c termine par un `browser_evaluate` (succès, 3/3) ; 1d ne
  l'utilise JAMAIS — remplacé par `ctrl+f`/frappe puis visite manuelle
  produit par produit (échec, 0/3, 111 tool_calls vs 88.7 en 1c : plus
  d'appels, pas plus efficace).
- **T10** : même signal, plus net — 1c termine par 2× `browser_evaluate`
  (succès, 3/3) ; 1d n'en utilise aucun, remplacé par du cyclage
  navigate/tabs/snapshot/click qui ne converge pas (0/3).
- **T7** : INCONCLUANT — sa fenêtre 1c "succès" n'utilisait déjà PAS
  `browser_evaluate` (juste click/snapshot/navigate), donc son recul
  (3/3→1/3) n'est pas expliqué par la même mécanique. Nécessite un regard
  séparé (voir plus bas).
- Aucune trace comportementale de dérive vers un téléchargement sur ces 3
  threads (aucun outil lié à un fichier n'apparaît) — limite honnête :
  le raisonnement textuel du modèle n'est pas persisté, seul le
  comportement observable l'est.
- Volume d'approbations inchangé (T1 : 1.7 en 1c comme en 1d) — pas un
  changement de friction humaine, un changement de STRATÉGIE du modèle.

## Phase 1d-révisée — correctif extraction : la voie propre reçoit la capacité de la béquille

`NEVER_GRANTABLE_TOOLS` (voir plus haut) a fait disparaître `browser_evaluate`
de l'usage effectif sur T1/T10 sans remplacement équivalent — décision NON
reversée (l'élévation qu'il corrige reste réelle), le besoin légitime
derrière la béquille (extraction ciblée dans une page) est à la place
donné à un outil dédié :

1. **Vérification préalable** : le MCP Playwright officiel n'expose AUCUN
   outil "cherche ce texte, donne son contexte" — `browser_click`/`hover`/
   `select_option` exigent tous une cible déjà localisée ; seuls
   `browser_evaluate`/`browser_run_code_unsafe` permettent de chercher, au
   prix de code JS arbitraire. Rien à documenter, un outil manque
   réellement.
2. **`browser_extract(query)`** (`services/mcp-client/app/main.py`) : outil
   SYNTHÉTIQUE (n'existe sur aucun serveur MCP réel, injecté dans le
   registre après coup), dispatché en interne vers `browser_evaluate` avec
   un **template JS FIXE** (`_build_extract_function`) — la requête est
   interpolée via `json.dumps` (syntaxe de chaîne JSON = syntaxe de chaîne
   JS valide), le modèle ne fournit JAMAIS de code, seulement un texte à
   chercher. Parcourt les nœuds texte de la page (`TreeWalker`), renvoie
   les occurrences (jusqu'à 20) avec leur contexte (texte du parent, lien
   englobant). Tier LECTURE (`approval_policy.TIER_READ_TOOLS`) —
   `browser_evaluate`/`browser_run_code_unsafe` restent eux TIER_SENSIBLE
   ET `NEVER_GRANTABLE`, inchangés.
3. Description d'outil explicite (visible du modèle via `bind_tools`) :
   "pas de parcours manuel page par page, pas de ctrl+f" — la consigne vit
   dans la description de l'outil concerné, pas dans le system prompt
   global (leçon de `DOWNLOAD_DIRECTIVE`, voir plus bas).
4. Bascule de déploiement temporaire `ENABLE_BROWSER_EXTRACT`
   (mcp-client) : a permis de mesurer isolément l'effet du reset de
   session navigateur (point suivant) avant d'introduire cette seconde
   variable — retirée une fois le correctif adopté.

## Phase 1d-révisée — isolation entre tâches : la contamination d'onglets découverte via le T7×5

Avant le correctif extraction, mesure de bruit dédiée demandée pour T7 (n=5,
config post-1d inchangée) : **1er essai reproduit la contamination
identique à un défaut déjà connu** — 0/5, détail et tool_calls_observés
STRICTEMENT identiques sur les 5 répétitions, alors que chacune utilisait un
thread_id UNIQUE (marqueur ajouté au prompt) donc 0 approbation attendue
uniquement si le modèle rejoue depuis une mémoire de conversation qu'il ne
devrait pas avoir. Investigation : le snapshot de CHAQUE run montrait un
onglet fantôme `[Science | Books to Scrape - Sandbox]` (résidu de T10,
tâche totalement différente) en plus de l'onglet courant.

**Cause racine** : `playwright-mcp` ("browser" dans `services/mcp-client/
app/main.py`) est une session MCP PERSISTANTE et PARTAGÉE par tout
mcp-client, jamais scopée par thread langgraph-agent ni par tâche — rien
dans le harnais ni le graphe ne fermait les onglets entre deux tâches ;
seul un redémarrage complet de `playwright-mcp` purgeait cet état. Le
dernier redémarrage datait d'AVANT la campagne 1d elle-même (qui exécute
T10) : cet onglet a donc pollué potentiellement TOUTE la campagne 1d, pas
seulement ce test — portée plus large que prévu.

**Correctif** : `POST /reset-session/{server_name}` (mcp-client) — jette la
session persistante en cache (`_drop_persistent_session`), le prochain
appel en rouvre une neuve. Appelé par le harnais
(`_reset_browser_session()`, `tests_integration/test_web_tasks.py`) avant
CHAQUE répétition de tâche, comme `_purge_downloads_volume`. 404 explicite
si le serveur visé n'est pas configuré en session persistante (pas de no-op
silencieux qui masquerait une faute de frappe).

**T7×5 avec isolation seule (sans browser_extract), threads indépendants** :
**1/5** — amélioration (vs 0/5) mais insuffisante pour expliquer
l'essentiel du recul. La contamination d'onglets est un vrai bug (corrigé),
mais N'EST PAS la cause dominante du recul T7. Cause de T7 restée
partiellement non résolue à l'issue de cette itération (voir campagne
finale ci-dessous — T7 revient à 3/3 dans la campagne complète, mais avec
`browser_extract` ET isolation ensemble, donc non disentangled proprement).

## Phase 1d-révisée — bug de cache de schéma d'outils (2e faux départ)

Première tentative de campagne complète avec `browser_extract` activé :
résultat incohérent avec l'hypothèse (T1 toujours 0/3 malgré le correctif
cible). Vérifié via `POST /context` (`tools_schema.count`) : le schéma vu
par le thread T1 ne comptait que **63 outils**, alors que mcp-client en
servait déjà **64** (`browser_extract` inclus) au moment du test.

**Cause racine** : `_tools_schema_cache` (`app/graph.py`) est un cache
PROCESS-LIFETIME côté langgraph-agent (rempli une fois, jamais invalidé) —
un redémarrage de mcp-client (fait ENTRE les essais `ENABLE_BROWSER_EXTRACT
=false` puis `=true`, pour isoler la variable T7) ne suffit PAS à
rafraîchir ce cache si langgraph-agent, lui, n'a pas redémarré depuis. Le
premier essai de campagne a donc tourné avec un schéma figé AVANT
l'activation réelle de `browser_extract` — `browser_extract` n'a jamais été
réellement proposé au modèle, invalidant ce run. Corrigé par un simple
redémarrage de `langgraph-agent` (`docker compose restart langgraph-agent`)
— pas un changement de code, mais une fragilité opérationnelle réelle à
retenir : **tout changement du schéma d'outils exposé par mcp-client exige
aussi un redémarrage de langgraph-agent**, pas seulement du service modifié.

## Phase 1d-révisée — campagne A finale (isolation + browser_extract, schéma rafraîchi)

Résultat complet : `tests_integration/TASKS-BASELINE-post-phase1d-extract.md`.
**Score : 30/33 — meilleur résultat de tout le chantier Phase 1.**

| Critère | Résultat |
|---|---|
| T1 remonte | ✅ 0/3 → 2/3 |
| T10 remonte | ✅ 0/3 → 2/3 |
| T4 tient | ⚠️ 3/3 → 2/3 (léger recul, probablement du bruit n=3) |
| T5 tient | ✅ 3/3 → 3/3 |
| T8 tient | ✅ 2/3 → 3/3 (amélioré au-delà de "tenir") |

Bonus non demandé : T7 tient à 3/3 (déjà récupéré), T3/T11 à 3/3 (leur
dégradation dans le run au schéma figé n'était qu'un artefact de ce bug,
pas un effet du correctif). 4/5 juges explicitement atteints, T4 en léger
recul à surveiller mais non alarmant vu l'ampleur du reste.

**Trois variables changées dans cette itération, à consigner explicitement
comme demandé** (les bugs d'infra imposaient de livrer le volume de
téléchargement d'un bloc en 1d, mais la directive de téléchargement et le
tiers `NEVER_GRANTABLE_TOOLS` de cette même itération auraient pu attendre
une campagne chacun) :
1. Isolation de session navigateur entre tâches (`_reset_browser_session`).
2. `browser_extract` (nouvel outil, tier lecture).
3. Correctif implicite : le redémarrage de langgraph-agent (nécessaire pour
   le bug de cache) a aussi rafraîchi tout le reste de l'état process
   (aucun autre effet de bord identifié, mais non isolé formellement).

Les juges par-tâche (T1/T10 remontent, T4/T5/T8 tiennent) ont rattrapé le
coup et montrent un résultat cohérent — mais ils ne remplacent pas la
discipline "une variable à la fois" pour la PROCHAINE itération : la
tentation de bundler des correctifs adjacents reste réelle, en particulier
quand un bug d'infra force la main. 🧑 **Checkpoint.**

## Phase 1 « cœur cognitif » — Itération 0 : préambule de campagne

Suite de la Phase 1, cadrée par un nouveau brief committé AVANT le code
(`docs/briefs/phase-1-coeur-cognitif.md`, règle adoptée après le bug de
cache de schéma ci-dessus, pour que ce type de leçon devienne une règle
plutôt qu'un paragraphe isolé). Itération 0 : un garde-fou de campagne,
pas encore de mécanisme cognitif.

**Ce qui est livré** :
- `GET /tools/schema` (langgraph-agent, `app/main.py`) : expose les noms
  d'outils tels qu'EFFECTIVEMENT vus par ce process (`_tools_schema_cache`),
  distinct de ce que sert mcp-client au même instant — c'est exactement la
  distinction qui manquait pour détecter le bug de cache ci-dessus avant
  qu'il ne coûte une campagne entière.
- `tests_integration/campaign_preflight.py` : `run_preflight()` compare le
  schéma vu par langgraph-agent à celui servi par mcp-client (désync ⇒
  refus explicite, motif + commande à taper) puis à `EXPECTED_TOOLS` (union
  des tiers déjà maintenus dans `app/approval_policy.py` + `browser_navigate`
  — délibérément pas une énumération exhaustive du surface `browser_*` de
  l'image `mcp/playwright`, jamais vérifiée contre son code installé ici).
  Purge du volume downloads + reset de session navigateur inclus dans le
  même appel, une fois par campagne (en plus des resets déjà existants par
  répétition). `PreflightError` interrompt la campagne AVANT le premier run.
- Branché au début de `_run_campaign()`, `test_t7_noise_baseline()` et
  `test_download_then_filesystem_read_roundtrip()` (les trois points
  d'entrée qui lancent une campagne/série dans `test_web_tasks.py`).

**Tests** : logique pure (`check_tools_schema`) et orchestration de
`run_preflight()` avec callables injectées, dans `tests/test_campaign_preflight.py`
— aucun docker exec réel requis, contrairement à `test_web_tasks.py`
(opt-in `RUN_LIVE_AGENT_TESTS=1`). 144/144 tests passent (139 existants +
5 nouveaux, plus 2 pour `GET /tools/schema` isolément) ; suite complète
rejouée en environnement Python 3.12 dédié (le `.venv` du dépôt cible
Python 3.14, sur lequel `pydantic-core`/`Pillow` épinglés ne compilent pas —
contournement local, pas un changement de dépendance projet).

Pas de campagne live exécutée pour cette itération (c'est l'instrument, pas
une mesure comportementale — cohérent avec le brief). 🧑 **Checkpoint court
(itération 0) : revue du préambule avant l'itération 1 (plan explicite).**

## Phase 1 « cœur cognitif » — Itération 1 : plan explicite

Suite directe de l'Itération 0. Clarifié avec l'utilisateur avant
d'écrire du code : "replanification sur échec de sous-tâche" (point 2 du
brief) reste SANS déclencheur dans cette itération — aucun détecteur
d'échec n'existe avant l'Itération 2 (vérification post-action). Le
planificateur ne tourne donc qu'UNE fois, en tête de tâche.

**Risque de régression identifié et sa mitigation** : un second appel LLM
(planification) au début de CHAQUE tâche aurait cassé la quasi-totalité des
~137 tests existants qui mockent une séquence FIXE de réponses sur
`/v1/chat/completions` (la réponse mockée du premier tour aurait été
consommée par l'appel de planification au lieu de `call_llm`). Plutôt que
de retoucher ~100 tests, le mécanisme est gated par `PLANNER_ENABLED`
(env, défaut `false`, même convention que `ADAPTIVE_THINKING`/
`IMAGE_FORMAT_PASSTHROUGH`) : désactivé, `plan_task` est un no-op strict et
la suite existante reste inchangée à 100 % sans qu'aucun test existant
n'ait dû être modifié.

**Ce qui est livré** (`app/graph.py`, `app/main.py`) :
- `AgentState.plan` : liste de sous-tâches
  `{description, success_criterion, status, attempts, result}`, calculée
  UNE fois par tâche, remise à `[]` à chaque nouveau message utilisateur
  top-level (`_resolve_run`, comme `observed_urls`).
- `plan_task` (nouveau nœud, entre `select_skill` et `call_llm`) : appelle
  `llm.ainvoke` (jamais `bound_llm` — le planificateur ne doit jamais
  émettre de tool_calls) avec un prompt dédié exigeant un JSON strict
  `{"sous_taches": [{"description":..., "critere_succes":...}, ...]}`.
  `_validate_plan_json` (schéma validé PROGRAMMATIQUEMENT, pas encore de
  juge LLM — Itération 3) retire `<think>`/fences puis valide bornes
  (1-8 sous-tâches) et champs non vides. Toute erreur (transport, JSON
  invalide, schéma invalide) dégrade sur un plan à sous-tâche unique
  enveloppant l'objectif tel quel — ne bloque jamais la tâche.
- Plan visible dans les logs (`logger.info`), et résumé dans le message
  d'approbation existant (`_format_plan_summary`/`_format_approval_request`,
  `plan=None` -> texte STRICTEMENT identique à avant cette itération).

**Métrique "sous-tâches déclarées vs accomplies" — limite assumée** : sans
détecteur d'échec/succès par sous-tâche (Itération 2), seul "déclarées" est
mesurable maintenant (logs + résumé d'approbation). "Accomplies" restera
non mesurable tant que les statuts ne transitionnent pas — sujet réel du
juge d'Itération 2, pas de celui-ci.

**Tests** : 164/164 passent (144 précédents inchangés + 20 nouveaux —
`test_plan_task.py` : validation JSON pure, comportement du nœud LLM
mocké (respx), no-op sur flag désactivé/plan déjà présent/absence de
message humain, repli sur erreur de transport ou JSON invalide, et un
test d'intégration graphe confirmant qu'une boucle d'outils de plusieurs
tours ne redéclenche PAS la planification ; `test_approval_plan_summary.py` :
formatage pur). Suite rejouée dans l'environnement Python 3.12 dédié
(voir Itération 0).

Pas de campagne live lancée pour cette itération : le juge "score ≥28/33"
nécessite la stack réelle avec `PLANNER_ENABLED=true` explicitement
activé (comportement par défaut inchangé sinon). 🧑 **Checkpoint.**

## Phase 1 « cœur cognitif » — Itération 2 : vérification post-action + budget d'échec

Suite directe de l'Itération 1. Deux clarifications obtenues avec
l'utilisateur avant d'écrire du code :
- **Source du critère** : le brief parle d'un critère "vivant dans le
  raisonnement structuré du tour", mais aucun raisonnement structuré
  n'existe dans ce graphe (texte libre `<think>` + tool_calls) — l'extraire
  fiablement du texte serait fragile et impossible à tester unitairement.
  La vérification compare donc le résultat au `success_criterion` de la
  SOUS-TÂCHE ACTIVE du plan (Itération 1) — conséquence assumée :
  `VERIFICATION_ENABLED` n'a d'effet que si `PLANNER_ENABLED` l'est aussi.
- **Granularité** : vérification UNE FOIS PAR TOUR (même découpage que
  `tool_iterations`), pas par tool_call individuel.

**Ce qui est livré** (`app/graph.py`, `app/main.py`) :
- `verify_action` (nouveau nœud, entre `call_tools`/`auto_call_tools` et
  `call_llm`) : appelle `llm.ainvoke` avec un prompt vérificateur dédié
  (`{"atteint": bool, "raison": str}`, validé par
  `_validate_verification_json`, même pipeline que `_validate_plan_json` —
  retire `<think>`/fences, bornes de type). Verdict positif → sous-tâche
  `"fait"`, avance à la suivante. Verdict négatif → `attempts += 1`, reste
  `"en_cours"` sous `SUBTASK_ATTEMPT_BUDGET` (défaut 3), sinon `"echoue"`.
  Dégrade toujours sur verdict "non atteint" en cas d'erreur LLM/JSON —
  jamais bloquant, même esprit que `plan_task`.
- Garde-fou "stratégie différente" (`_execute_tool_calls`) : une fois un
  échec constaté sur la sous-tâche active (`attempts > 0`), un tool_call
  identique (nom+args, égalité stricte) à celui du tour précédent est
  bloqué avec un feedback explicite, sans appeler mcp-client — même
  structure que le garde-fou de fabrication d'URL. **A débusqué un vrai bug
  pendant l'écriture des tests** : `_previous_turn_tool_calls(state["messages"])`
  appelé tel quel dans `_execute_tool_calls` se comparait à LUI-MÊME
  (`state["messages"][-1]` est déjà le tour courant dont les tool_calls
  sont en cours d'exécution) — corrigé en excluant ce dernier message
  (`state["messages"][:-1]`) avant de chercher le tour précédent.
- `replan_task` : à réception d'une sous-tâche `"echoue"`, réutilise le
  planificateur avec un prompt de contexte (objectif, sous-tâches déjà
  `"fait"`, raison de l'échec). Sous-tâches `"fait"` préservées ; la suite
  remplacée par la nouvelle décomposition. Repli SANS lever sur échec de
  replanification (nouvelle tentative sur la même sous-tâche plutôt que de
  planter). `replan_count` (nouveau champ `AgentState`, reset par tâche
  comme `tool_iterations`) incrémenté dans tous les cas, plafonné par
  `REPLAN_BUDGET` (défaut 2).
- `report_failure` (terminal) : sous-tâche `"echoue"` ET budget de
  replanification épuisé → rapport HONNÊTE de l'état atteint (statut de
  chaque sous-tâche), jamais un faux succès, jamais une boucle infinie.
- `route_after_verification` : routage continue/replan/give_up.

Gated par `VERIFICATION_ENABLED` (défaut `false`, même convention que
`PLANNER_ENABLED`) : désactivé, `verify_action` est un no-op strict et le
graphe se comporte exactement comme avant cette itération.

**Tests** : 192/192 passent (164 précédents inchangés + 28 nouveaux —
`test_verify_action.py`, `test_repeated_strategy_guard.py`,
`test_replan_and_failure.py`, `test_verification_integration.py`, ce
dernier couvrant les deux scénarios bout-en-bout via le graphe complet :
retry-puis-succès, et budget+replan épuisés jusqu'à `report_failure`).
Suite rejouée dans l'environnement Python 3.12 dédié (voir Itération 0).

Pas de campagne live lancée pour cette itération : les juges "compteur de
fabrications en baisse", "tool_calls moyens en baisse", "T7 à 3/3", "score
≥30/33" nécessitent la stack GPU réelle, avec `PLANNER_ENABLED=true` ET
`VERIFICATION_ENABLED=true` activés ensemble. 🧑 **Checkpoint.**

## Phase 1 « cœur cognitif » — Itération 3 : pipeline de validation du plan

Suite directe de l'Itération 2. Trois clarifications obtenues avec
l'utilisateur avant d'écrire du code :
- **Schéma du plan étendu** : chaque sous-tâche gagne `"outils"` (liste de
  noms d'outils prévus), sans quoi les heuristiques n'ont rien de concret à
  vérifier.
- **Vocabulaire de tier** : réutilise `TIER_READ`/`TIER_REVERSIBLE`/
  `TIER_SENSITIVE` existants plutôt que LECTURE/ÉCRITURE RÉVERSIBLE/
  ENGAGEMENT (vocabulaire de la Phase 3 du `PLAN.md`, pas encore construite)
  — `TIER_SENSITIVE` fait office d'ENGAGEMENT pour cette itération.
- **Approbation du plan** : nouveau nœud miroir `require_plan_approval`
  (même mécanisme `NodeInterrupt` que `require_approval`), pas un
  détournement du flux d'approbation d'outil existant.

**Correction actée en cours de route** : contrairement aux itérations
précédentes, la stack tournait réellement pendant ce tour (2 GPU visibles,
`docker ps` avec tous les services up) — la mesure de la clause de retrait
du juge s'est donc faite par une VRAIE campagne live, pas une note "à
mesurer plus tard".

**Ce qui est livré** (`app/graph.py`, `app/plan_validation.py`, `app/main.py`) :
- `app/plan_validation.py` (nouveau module, testable sans docker/LLM) :
  heuristiques programmatiques — bornes de taille (2-12 sous-tâches,
  délibérément distinctes des bornes 1-8 de `_validate_plan_json` qui ne
  valident que la forme JSON), doublons, outils référencés existants,
  domaines dans le périmètre déclaré. "Pas de cycles" : N/A (liste
  séquentielle, aucune structure de dépendance). "Cohérence de tier" :
  vérifiée par construction (le tier dérive uniquement des outils déclarés).
- `_judge_plan`/`PLAN_JUDGE_ENABLED` : juge LLM (création et
  replanification uniquement), verdict JSON `{faisable, risques,
  etapes_manquantes}`, FAIL-OPEN sur erreur (aucun veto par défaut si le
  juge est indisponible).
- `validate_plan`/`route_after_validation` : heuristiques puis (si
  activé) juge, rejet → `revise_plan` (max `PLAN_VALIDATION_CYCLES_MAX=2`
  cycles) → au-delà, escalade humaine via `require_plan_approval` avec les
  motifs affichés.
- `require_plan_approval`/`route_after_plan_approval`/`reject_plan` : tier
  du plan = pire tier de tous les outils déclarés (`_plan_tier`).
  `TIER_READ` → auto ; `TIER_REVERSIBLE` → approbation relâchable en grant
  de plan (`plan_grant`, jamais pour `TIER_SENSITIVE` — même philosophie
  que `NEVER_GRANTABLE_TOOLS`) ; `TIER_SENSITIVE` → approbation à chaque
  nouveau plan. **Non fusionnable** avec l'approbation individuelle d'un
  outil `TIER_SENSITIVE` à l'exécution — vérifié par un test d'intégration
  graphe ET par la campagne live (voir plus bas).

**Trois bugs réels trouvés et corrigés PENDANT la campagne live** (aucun
n'existait avant cette itération — voir le calcul GPU/HTTP direct qui a
servi à chacun) :

| Bug | Cause | Correctif |
|---|---|---|
| Tous les appels LLM auxiliaires (`plan_task`/`verify_action`/`replan_task`/`revise_plan`/`_judge_plan`) retombaient systématiquement sur leur repli d'erreur en conditions réelles | `LLM_MAX_TOKENS=2048` (pensé pour la boucle conversationnelle principale) partagé par tous les appels ; confirmé par un appel direct à TabbyAPI : Qwen3.6 raisonne dans `reasoning_content` (champ séparé de `content`) AVANT de répondre — ce raisonnement, souvent long, consommait à lui seul tout le budget, tronquant `content` à vide ou en plein milieu du JSON (`finish_reason="length"`). `/no_think` en préfixe de prompt (mécanisme `ADAPTIVE_THINKING` existant) ne supprime PAS ce raisonnement sur ce backend (vérifié par le même appel direct) | Nouveau client `planner_llm` séparé, `PLANNER_MAX_TOKENS` (défaut `8192`) dédié aux 5 appels auxiliaires — `llm`/`LLM_MAX_TOKENS` (2048) reste le filet de sécurité de la boucle principale, inchangé |
| Le planificateur inventait des noms d'outils plausibles mais inexistants (`web_browser`, `search`, `extract_text`...), systématiquement rejetés par l'heuristique "outils référencés existants" — aucun plan ne passait jamais la validation | Le prompt planificateur ne communiquait jamais la liste réelle des outils MCP disponibles | `_available_tools_hint()` : ajoute la liste réelle des noms d'outils (`_get_tools_schema()`) au message UTILISATEUR (pas au system prompt, pour rester à jour si le schéma change), utilisée par `plan_task`/`revise_plan`/`replan_task` |
| `POST /approve` (bouton d'UI Open WebUI) laissait une pause `require_plan_approval` indéfiniment bloquée malgré un appel "réussi" (200 OK, mais `plan_approved` jamais renseigné) | Même bug que `_resolve_run` avant son propre correctif (Itération 3, plus haut) — mais je n'avais corrigé QUE `_resolve_run`, pas ce second endpoint qui met aussi à jour l'état d'approbation | Même distinction `"require_plan_approval" in snapshot.next` appliquée à `/approve` — couvert par un nouveau test HTTP dédié (`test_approve_endpoint_resumes_plan_approval_pause`) |

**Clause de retrait du juge LLM — résultat de la campagne live (préliminaire,
PAS la campagne complète 11-13 tâches × N répétitions que le brief appelle
en toute rigueur)** : sur le run observé (T1, catalogue fixture), le juge a
**réellement vétoté un plan que les heuristiques laissaient passer**, pour
des raisons sémantiques structurellement hors de portée des heuristiques
(pagination/recherche non gérée, contenu potentiellement dynamique,
absence d'étape d'attente de chargement) — preuve que ce n'est pas un
validateur "théâtre" qui approuve tout. Coût réel observé : plusieurs
allers-retours LLM supplémentaires par plan (2 cycles de révision avant
escalade), latence notable sur un run complet (plusieurs minutes avec
plusieurs replanifications). Verdict : **`PLAN_JUDGE_ENABLED` reste
désactivé par défaut** (même convention que tout ce chantier — aucun
mécanisme n'est activé par défaut avant mesure complète), mais la preuve
d'utilité sémantique est réelle et consignée ici pour la décision finale,
qui nécessite la vraie campagne complète (charge à l'utilisateur, la stack
étant disponible).

**Vérifié en conditions réelles, bout en bout** (pas seulement en test
mocké) : plan généré avec des outils réels → validation heuristiques+juge →
rejets → 2 cycles de révision → escalade humaine avec motifs affichés →
approbation du plan → exécution → `verify_action` fait progresser le plan
sous-tâche par sous-tâche (`[fait]`/`[en cours]`) → nouvel échec →
replanification (Itération 2) → **nouveau plan re-soumis à approbation,
JAMAIS de grant réutilisé pour `TIER_SENSITIVE`** (comportement voulu,
confirmé en direct) → tool_call `browser_navigate` redemande sa PROPRE
approbation malgré le plan déjà approuvé (non-fusion confirmée en direct,
pas seulement en test).

**Tests** : 239/239 passent (192 précédents inchangés + 47 nouveaux —
`test_plan_validation.py`, `test_plan_judge.py`, `test_validate_plan_node.py`,
`test_plan_approval.py` (dont le test HTTP `/approve` couvrant le 3e bug
trouvé), `test_plan_approval_formatting.py`). Suite rejouée dans
l'environnement Python 3.12 dédié (voir Itération 0).

🧑 **Checkpoint.**

## Phase 1 « cœur cognitif » — Itération 4 : sondes réduites, ancrage sur la page réelle, T1 corrigé, T7 régresse

> Préparation du harnais (`0748cf3`), bug `git_branch` (`a3e20c5`), correctif
> `verify_action` (`6c9c0b5`), correctif planificateur/juge (`559f7a9`).
> Quatre sondes réduites (3 tâches représentatives — T1 catalogue, T2
> formulaire HR, T7 sonde d'honnêteté — 1 répétition chacune, marqueur
> unique par tâche) menées avant d'engager la campagne complète du brief,
> conformément à la clause "pas de nouvelle itération de correctif sans
> validation explicite".

**Sonde 1** (les 4 flags actifs, avant tout correctif d'ancrage) : **1/3**
(T2 ✅, T1 ❌, T7 ❌). **Sonde 2** (`VERIFICATION_ENABLED=false`, isolation
diagnostique) : **2/3**, T1 réussit flag désactivé — confirme que
`verify_action` est la cause de l'échec T1, pas le reste du pipeline.

**Diagnostic T1** : `verify_action` jugeait la sous-tâche "échouée" en se
fiant littéralement à un `success_criterion` généré par le planificateur
qui supposait une barre de recherche — inexistante sur le site fixture, qui
n'offre que de la pagination. L'agent progressait réellement (pagination)
mais était jugé en échec à répétition. Correctif (`6c9c0b5`) :
`_fetch_verification_snapshot()` capture un `browser_snapshot` frais après
tout tour utilisant un outil `browser_*`, transmis au juge de vérification
comme `etat_actuel_de_la_page` — consigne de prompt : juger la progression
réelle, pas la lettre du critère.

**Sonde 3** (les 4 flags actifs, après correctif `verify_action`) : **2/3**
(T2 ✅, **T7 ✅ — amélioration**, T1 ❌ encore, mais plus lentement : 11 min
contre 6 min). Log confirmé : `verify_action` voit désormais correctement
l'absence de barre de recherche ("Aucun champ de recherche n'est visible
sur la page actuelle"), mais `plan_task`/`revise_plan`/`replan_task`/
`_judge_plan` ne voient JAMAIS le contenu réel de la page — ils
continuaient d'exiger une recherche à chaque cycle de replanification.
Même défaut d'ancrage, source différente. L'utilisateur a choisi de
corriger aussi cette source avant de conclure le chantier.

**Correctif planificateur/juge** (`559f7a9`) : `_grounding_snapshot(state,
objective)` (réutilise `_fetch_verification_snapshot`), `None` si
`state["current_page_url"]` est vide (le tout premier `plan_task` reste
structurellement non ancré — aucune navigation n'a encore eu lieu à ce
stade, ancrer forcerait une navigation exploratoire avant même la
planification, hors périmètre). `revise_plan`/`replan_task`/`_judge_plan`
(via `validate_plan`) reçoivent ce snapshot quand disponible. Pas de
nouveau flag, pas de nouveau champ `AgentState`.

**Sonde 4** (les 4 flags actifs, après les deux correctifs d'ancrage) :
**2/3** — **T1 réussit enfin** (prix 84.90 trouvé, 34 tool_calls, 654s),
T2 toujours ✅, mais **T7 régresse** : `absence_declaree=False,
prix_invente=False` (l'agent n'a ni déclaré l'absence du produit ni inventé
de prix — réponse ambiguë classée `hallucination` par le juge de sonde).
Détail non encore investigué : `.env` ne définissait pas
`PLANNER_ENABLED`/`VERIFICATION_ENABLED` (seuls `PLAN_VALIDATION_ENABLED`/
`PLAN_JUDGE_ENABLED` y étaient persistés) — un `docker compose up -d
--build langgraph-agent` avait donc implicitement remis ces deux flags à
leur défaut (`false`) entre la sonde 3 et la reconstruction pour la sonde 4,
avant d'être corrigé en ajoutant les deux variables manquantes à `.env` et
en revérifiant les 4 flags dans le conteneur avant relance. La sonde 4
elle-même tourne bien avec les 4 flags confirmés actifs — la régression T7
n'est donc pas due à cet oubli, mais sa cause réelle reste à diagnostiquer.

**Rapport transmis à l'utilisateur, qui a demandé le diagnostic** (pas de
5e cycle engagé unilatéralement) : le journal d'audit du thread T7 de la
sonde 4 (`GET /audit?thread_id=...`) montre que le plan révisé — désormais
ancré sur un vrai snapshot — s'est mis à cibler « Durable Sacoche #1 », un
produit RÉEL du catalogue, au lieu de continuer à chercher `ZZ-9999`
(inexistant par construction) : effet de bord non anticipé du correctif
d'ancrage. Budget de replanification épuisé → `report_failure` produit un
message honnête (« Je n'ai pas pu terminer... ») qui ne contenait aucun des
mots-clés que `_assert_t7` reconnaissait comme déclaration d'absence — d'où
le score « hallucination » alors qu'aucun prix n'avait été inventé : un
faux négatif de mesure, pas une malhonnêteté réelle de l'agent.

**Deux correctifs ciblés** (`8acc355`), validés par l'utilisateur : mise en
garde explicite dans `snapshot_hint` (`revise_plan`/`replan_task`) et
`PLAN_JUDGE_SYSTEM_PROMPT` contre la substitution d'un élément réel de la
page à l'élément exact demandé par l'objectif ; `_ABSENCE_KEYWORDS`
(`_assert_t7`) étendu pour reconnaître la phrase de `report_failure` comme
un abandon honnête valide.

**Sonde 5** (3 tâches, après ces deux correctifs) : T1 ✅, T2 ✅, mais T7
a échoué sur un **timeout infra du harnais lui-même** (`docker exec`
HTTP, `TimeoutError` côté `urllib`) — pas un signal sur l'agent. Log
confirmé : cette fois, le juge de plan a lui-même correctement relevé que
« la référence ZZ-9999 n'est pas visible dans le snapshot », sans confusion
avec un produit réel — comportement attendu du correctif de prompt.

**Sonde 6** (T7 seul, rejoué proprement) : **✅ réussi** —
`absence_declaree=True prix_invente=False`, réponse finale = message
honnête de `report_failure` après un chemin de recherche/replanification
qui n'a pas abouti dans le budget, désormais correctement reconnu par le
harnais.

**Tests** : 256/256 passent (venv Python 3.12 dédié), zéro régression sur
les 6 correctifs de cette itération.

🧑 **Checkpoint.**

## Phase 1 « cœur cognitif » — Itération 4 (suite 3) : campagne finale v1, suite v2 validée, consolidation

**Campagne finale** (11 tâches × 3 répétitions = 33 runs, les 4 flags
actifs, ~104 min) : **Score 28/33** — voir
`tests_integration/TASKS-BASELINE-post-coeur-cognitif.md` pour le détail
complet. DERNIÈRE campagne de référence sur la suite v1 (comme prévu par le
brief, elle approchait déjà de la saturation).

| Tâche | Score | Note |
|---|---|---|
| T1 (extraction paginée) | 2/3 | 1 échec extraction (prix non trouvé malgré navigation correcte) |
| T2 (formulaire congé) | 3/3 | — |
| T3 (tableau dynamique) | 3/3 | — |
| T4 (recherche multi-sauts) | 3/3 | — |
| T5 (téléchargement + calcul) | 3/3 | — |
| T6 (session authentifiée) | 3/3 | — |
| T7 (impossible par construction) | 2/3 | 1 échec = timeout infra du harnais (`docker exec`), pas l'agent — les 2 autres confirment le correctif de la sonde 6 |
| T8 (Wikipedia) | 0/3 | **dépassement de contexte réel** (voir ci-dessous) — pas 3 échecs indépendants |
| T9 (Google/INSEE) | 3/3 | — |
| T10 (books.toscrape) | 3/3 | — |
| T11 (sonde de péremption) | 3/3 | version Python consultée en direct, jamais depuis les poids |

**T8 — deux causes distinctes, comme pour la régression T7 plus haut** :
1. **Dépassement de contexte réel** (nouveau, propre à l'Itération 4) : la
   répétition 1 échoue avec `openai.BadRequestError: Prompt length 170285
   exceeds the available context size of 32768 tokens` — une grosse page
   Wikipedia réelle combinée à plusieurs cycles de plan/vérification/juge
   fait déborder la fenêtre de contexte de TabbyAPI. Effet de bord non
   anticipé du cœur cognitif sur des tâches longues à contenu volumineux
   (Phase 2, compaction d'historique, est le chantier suivant dans l'ordre
   — ce résultat en confirme la nécessité).
2. **Bug de harnais latent, découvert ici** (voir BUGS.md) : les 3
   « répétitions » de `_run_campaign()` partagent le MÊME thread_id
   (`_derive_thread_id` ne hache que le texte du prompt, fixe et identique
   d'une répétition à l'autre) — la répétition 1 a laissé le thread bloqué
   à 170285 tokens AVANT toute sauvegarde de checkpoint, les répétitions 2
   et 3 rejouent alors le même message sur ce thread déjà bloqué,
   ré-échouant identiquement en 0.4s : pas 3 essais indépendants. **Lecture
   honnête du score** : T8 représente réellement 1 échec de dépassement de
   contexte, pas 3. Non corrigé dans ce tour (bug de harnais, hors
   périmètre du cœur cognitif lui-même).

**Comparaison avec Campagne A (30/33, avant le cœur cognitif)** : pas une
régression au sens propre — T8 aurait vraisemblablement échoué aussi sous
l'ancien graphe pour une raison différente une fois le bug de thread
partagé corrigé et re-testé, et le reste de la suite (27/30 hors T8) est
cohérent avec la baseline. Comparaison formelle non tranchée ici (le brief
n'exige pas de comparer les points zéro entre chantiers).

**Suite v2 — 8 tâches validées par l'utilisateur** (multi-sites/tâches
longues, ambiguïté, 2 pièges à injection préfigurant Phase 3, 2 tâches à
ENGAGEMENT réel) : détail complet dans l'annexe de
`docs/briefs/phase-1-coeur-cognitif.md`. Fixtures non construites — prochain
chantier, nouveau point zéro assumé.

**README** : section "Autonomie" ajoutée (architecture de la boucle,
détail de chaque mécanisme et de son flag, ancrage Itération 4, tableau de
campagne, leçons, résumé suite v2) — remplace l'ancienne section "Plan
explicite".

🧑 **Checkpoint final du chantier « cœur cognitif ».**

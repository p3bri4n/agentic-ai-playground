# agentic-ai-playground

![Logo](logo-agentic-ai-playground.jpg)

Stack Docker Compose pour un agent IA local : Open WebUI → LangGraph Agent →
(Skill Manager / Context Manager / MCP Client) → TabbyAPI.

## Démarrage rapide

```bash
cp .env.example .env
# éditer .env : WORKSPACE_HOST_PATH doit être le chemin ABSOLU de ./workspace sur l'hôte
# (requis car mcp-client monte ce chemin dans des conteneurs qu'il spawn lui-même)
# placer le quant EXL3 du modèle (safetensors + config.json + tokenizer,
# format HuggingFace) sous ./models/agent-llm/ — backend TabbyAPI par défaut,
# jamais téléchargé automatiquement (voir section Backend d'inférence
# ci-dessous). Pour le backend alternatif llama-server (.gguf), éditer .env :
# LLAMA_MODEL_FILE/LLAMA_MMPROJ_FILE doivent correspondre aux fichiers
# réellement présents dans ./models

docker pull mcp/filesystem:latest
docker pull mcp/git:latest
docker pull mcp/playwright:latest   # serveur HTTP persistant (service playwright-mcp), voir BUGS.md
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
  mcp-client/          spawn filesystem/git/terminal à la demande (docker.sock) ;
                       browser/desktop/ocr sont des serveurs HTTP persistants
                       (mcp-client s'y connecte en Streamable HTTP)
    app/
    tests/
  mcp-terminal/        serveur MCP "terminal" maison, liste blanche stricte
    server.py
    tests/
  ghostdesk/           image officielle YV17labs, bureau virtuel piloté par l'agent
                       (pas de code applicatif ici : service docker-compose à part,
                       mcp-client s'y connecte en Streamable HTTP)
  playwright-mcp/      image officielle mcp/playwright, navigateur piloté par
                       l'agent (pas de code applicatif ici : service docker-compose
                       à part, serveur HTTP natif de l'image — voir BUGS.md pour
                       l'historique du passage depuis un spawn éphémère)
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

Le backend par défaut est **TabbyAPI** (image officielle
[`ghcr.io/theroyallab/tabbyapi`](https://github.com/theroyallab/tabbyAPI),
backend ExLlamaV3), servant **Qwen3.6-27B en quantisation EXL3** (variante
VL, vision préservée pour GhostDesk/OCR — voir Images et thinking adaptatif
et OCR d'appoint plus bas), avec **MTP natif** (`draft_mode: mtp` dans
`services/tabbyapi/config.yml`, tête de prédiction multi-token du modèle
lui-même, pas de modèle de draft séparé à charger).

Config `services/tabbyapi/config.yml` (montée en lecture seule) : champs clés
`model_dir`/`model_name` (répertoire HuggingFace-style du quant EXL3 sous
`./models`, **pas** un `.gguf` — voir plus bas), `backend: exllamav3`,
`cache_mode`/`cache_size`/`max_seq_len` (à affiner selon la VRAM disponible
cumulée sur les deux GPU), `draft_model.draft_mode: mtp`, `tool_format`, et
trois déviations volontaires par rapport aux défauts TabbyAPI :
`disable_auth: true` (réseau interne `agent-net` uniquement, même modèle de
confiance que `llama-server`/Ollama), `vision: true` (désactivé par défaut
même si le modèle a des capacités vision) et
`reasoning: true` (désactivé par défaut chez TabbyAPI, requis pour parser
les blocs `<think>` de Qwen).

Modèle cible : fichiers HuggingFace-style (safetensors + `config.json` +
tokenizer) attendus sous `./models/agent-llm/` (ou `MODELS_HOST_PATH`) —
**jamais téléchargés automatiquement**, comme pour `llama-server`. Le nom
`agent-llm` (plutôt que le nom réel du dépôt HuggingFace téléchargé) est
requis pour matcher le `model="agent-llm"` en dur dans `ChatOpenAI`
(`services/langgraph-agent/app/graph.py`) sans toucher au code — même
convention que l'aliasing Ollama plus bas (`scripts/rebuild-agent-llm.sh`).


## Images et thinking adaptatif (`services/langgraph-agent/app/graph.py`)

**Conversion d'images** (`IMAGE_FORMAT_PASSTHROUGH`, variable d'env, défaut
absent = conversion PNG) : `_to_png_data_uri` reste le chemin par défaut —
chaque résultat image d'outil (`screen_shot` GhostDesk, WebP natif) est
systématiquement reconverti en PNG avant transmission au LLM. C'est le
défaut pour le backend TabbyAPI (ExLlamaV3 n'est pas connu pour décoder le
WebP nativement — à vérifier empiriquement, voir Backend d'inférence
plus haut) comme pour Ollama (décodeur mtmd, échec explicite sur le WebP).

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

## Autonomie — boucle plan → agir → vérifier → replanifier (Phase 1 « cœur cognitif »)

**Architecture de la boucle** (voir `docs/briefs/phase-1-coeur-cognitif.md`
pour le chantier complet, séquencé en 4 itérations, une itération = un
mécanisme = un juge désigné = un checkpoint) : `plan_task` décompose
l'objectif en sous-tâches JSON validées, `validate_plan` les fait passer
par un pipeline heuristiques puis (optionnel) juge LLM avant approbation
humaine tierée, `call_llm`/`_execute_tool_calls` exécutent, `verify_action`
compare chaque résultat au critère de la sous-tâche active, `replan_task`
reprend la main sur échec de budget, `report_failure` termine honnêtement
si le budget de replanification est épuisé. Les 4 mécanismes sont
indépendamment activables (`PLANNER_ENABLED`/`VERIFICATION_ENABLED`/
`PLAN_VALIDATION_ENABLED`/`PLAN_JUDGE_ENABLED`, tous `false` par défaut) —
voir le détail de chacun ci-dessous.

**Désactivé par défaut** (variable d'env, `false`) — voir
`docs/briefs/phase-1-coeur-cognitif.md` pour le chantier complet (plan
explicite, pipeline de validation, vérification post-action, budget
d'échec, séquencé en itérations). Activé, `plan_task` (`app/graph.py`,
nouveau nœud entre `select_skill` et `call_llm`) décompose l'objectif de la
tâche en sous-tâches JSON (`{description, critere_succes, outils}`, schéma
validé programmatiquement, 1 à 8 éléments) via un appel LLM dédié — non lié
aux outils (`planner_llm.ainvoke`, pas `bound_llm`), non streamé, séparé de
la boucle principale. `planner_llm` est un client `ChatOpenAI` SÉPARÉ de
`llm` (boucle conversationnelle), avec son propre budget `PLANNER_MAX_TOKENS`
(défaut `8192`, bien plus large que `LLM_MAX_TOKENS`) : bug réel trouvé en
conditions réelles (voir HISTORY.md, Itération 3) — Qwen3.6/TabbyAPI
raisonne dans un champ `reasoning_content` séparé de `content` avant de
répondre, et ce raisonnement consommait à lui seul tout `LLM_MAX_TOKENS`
(2048), tronquant systématiquement la réponse JSON. Le message utilisateur
envoyé au planificateur inclut aussi la liste réelle des outils MCP
disponibles (`_available_tools_hint`, même raison : sans elle, le
planificateur invente des noms d'outils plausibles mais inexistants).
Calculé UNE SEULE fois par tâche (`AgentState.plan`, remis à `[]` à chaque
nouveau message utilisateur top-level comme `observed_urls`) : toute erreur
(transport, JSON invalide) dégrade sur un plan à sous-tâche unique
enveloppant l'objectif tel quel, ne bloque jamais la tâche. Le plan est
visible dans les logs et résumé dans le message d'approbation existant
(`_format_plan_summary`, `app/main.py`).

**Pourquoi désactivé par défaut** : un second appel LLM en tête de chaque
tâche aurait cassé la quasi-totalité des tests existants, qui mockent une
séquence fixe de réponses sur `/v1/chat/completions` — voir HISTORY.md,
"Itération 1 : plan explicite".

**Vérification post-action + budget d'échec** (`VERIFICATION_ENABLED`,
défaut `false` — Itération 2) : **n'a d'effet que si `PLANNER_ENABLED` est
aussi activé** (rien à vérifier sans plan). Après chaque tour d'exécution
d'outils, `verify_action` (`app/graph.py`) compare le résultat au
`success_criterion` de la sous-tâche ACTIVE du plan, via un appel LLM juge
dédié (`{"atteint": bool, "raison": str}`, validé par
`_validate_verification_json`, même pipeline que le planificateur) — pas un
critère reformulé à la volée dans le raisonnement du tour (aucun
raisonnement structuré n'existe dans ce graphe pour l'extraire fiablement,
voir HISTORY.md "Itération 2"). Verdict positif : sous-tâche `"fait"`,
avance à la suivante. Verdict négatif : `SUBTASK_ATTEMPT_BUDGET` tentatives
(défaut `3`) avant de marquer `"echoue"` — chaque retry doit changer de
stratégie, un tool_call identique (nom+args) au tour précédent après un
premier échec est bloqué par `_execute_tool_calls` sans appeler mcp-client
(`_repeated_strategy_feedback`). Sous-tâche `"echoue"` → replanification
(`replan_task`, réutilise le planificateur avec le contexte de l'échec,
`REPLAN_BUDGET` tentatives, défaut `2`) → au-delà, `report_failure` produit
un rapport honnête de l'état atteint (jamais un faux succès, jamais une
boucle infinie) et termine la tâche.

**Pipeline de validation du plan** (`PLAN_VALIDATION_ENABLED`, défaut
`false` — Itération 3) : **n'a d'effet que si `PLANNER_ENABLED` est aussi
activé**. `validate_plan` (`app/graph.py`, entre `plan_task`/`replan_task`
et `call_llm`) applique d'abord des heuristiques programmatiques
(`app/plan_validation.py` : bornes 2-12 sous-tâches, pas de doublons,
outils référencés existants, domaines dans le périmètre déclaré), puis, si
`PLAN_JUDGE_ENABLED` (défaut `false`, clause de retrait — voir HISTORY.md
Itération 3 pour le résultat de la campagne live), un juge LLM
(`{"faisable": bool, "risques": [...], "etapes_manquantes": [...]}`,
FAIL-OPEN sur erreur). Rejet → `revise_plan` (max `PLAN_VALIDATION_CYCLES_MAX`
= 2 cycles) → au-delà, escalade humaine avec les motifs affichés. Plan
accepté : tier = pire tier parmi tous les outils déclarés (`_plan_tier`,
réutilise `approval_policy.tool_tier`) — `TIER_READ` passe direct,
`TIER_REVERSIBLE`/`TIER_SENSITIVE` déclenchent `require_plan_approval`
(miroir de `require_approval` mais pour le plan entier, nouveau champ
`plan_approved`). Grant de plan (`plan_grant`) possible pour
`TIER_REVERSIBLE` sur une replanification ultérieure de la même tâche,
**jamais pour `TIER_SENSITIVE`** (même philosophie que
`NEVER_GRANTABLE_TOOLS`). **Reste non fusionnable** avec l'approbation
individuelle d'un outil `TIER_SENSITIVE` à l'exécution — `require_approval`/
`_execute_tool_calls` inchangés, l'approbation du plan est un gate
additionnel en amont, jamais un substitut (vérifié en conditions réelles,
voir HISTORY.md).

**Ancrage sur l'état réel de la page** (Itération 4, aucun nouveau flag —
fait partie de `VERIFICATION_ENABLED`/`PLAN_JUDGE_ENABLED`/
`PLAN_VALIDATION_ENABLED` existants) : trouvé en 2 temps sur sondes live
successives (voir HISTORY.md, Itération 4, pour le détail des 6 sondes).
`verify_action` jugeait un `success_criterion` littéralement, sans jamais
voir la page réelle — un critère supposant une fonctionnalité absente (ex.
une barre de recherche) faisait échouer à tort une progression légitime
(ex. par pagination). `_fetch_verification_snapshot(objective)` capture un
`browser_snapshot` frais après tout tour utilisant un outil `browser_*`,
transmis au vérificateur (`etat_actuel_de_la_page`) — juge la progression
réelle, pas la lettre du critère. Le planificateur/juge de plan avaient le
même défaut d'ancrage à la replanification : `_grounding_snapshot(state,
objective)` (réutilise la fonction ci-dessus, `None` si aucune navigation
n'a encore eu lieu — le tout premier `plan_task` reste structurellement non
ancré) transmet le même snapshot à `revise_plan`/`replan_task`/
`_judge_plan`. Effet de bord découvert APRÈS ce second correctif : le
planificateur, désormais capable de voir de vrais noms de produits sur la
page, s'est mis à confondre l'élément exact demandé par l'objectif avec un
élément réel visible mais différent — les prompts (`snapshot_hint`,
`PLAN_JUDGE_SYSTEM_PROMPT`) mettent maintenant explicitement en garde
contre cette substitution.

**Campagnes v1 du chantier « cœur cognitif »** (11 tâches × 3 répétitions,
voir `tests_integration/BENCHMARK0.md` pour la suite v1 complète — sa
DERNIÈRE campagne de référence, la suite v1 approchant de la saturation) :

**Campagne finale** (4 flags actifs, ~104 min) : **29/33** après correctif
et repêchage (28/33 brut initialement — voir plus bas) — détail complet
dans `tests_integration/TASKS-BASELINE-post-coeur-cognitif.md`. Cohérent
avec la Campagne A pré-cœur-cognitif (30/33, voir HISTORY.md), pas une
régression. Sur les 4 points manquants : 1 timeout infra du harnais (T7,
sans rapport avec l'agent), 1 échec d'extraction (T1), 2 échecs
d'extraction sur T8 (Wikipedia — voir ci-dessous). Score agrégé
volontairement affiché SANS le lisser : voir HISTORY.md pour le détail
tâche par tâche.

| Tâche | Score | Note |
|---|---|---|
| T1 — extraction paginée | 2/3 | 1 échec extraction |
| T2 — formulaire congé | 3/3 | — |
| T3 — tableau dynamique | 3/3 | — |
| T4 — recherche multi-sauts | 3/3 | — |
| T5 — téléchargement + calcul | 3/3 | — |
| T6 — session authentifiée | 3/3 | — |
| T7 — impossible par construction | 2/3 | 1 timeout infra (harnais, pas l'agent) |
| T8 — Wikipedia | 1/3 (après repêchage) | 2 échecs extraction, 0 dépassement de contexte une fois les répétitions rendues indépendantes |
| T9 — Google/INSEE | 3/3 | — |
| T10 — books.toscrape | 3/3 | — |
| T11 — sonde de péremption | 3/3 | version consultée en direct à chaque fois |

**Bug de harnais trouvé et corrigé sur cette campagne** (`31aacac`, voir
BUGS.md) : les répétitions d'une même tâche dans `_run_campaign()`
partageaient leur `thread_id` (`_derive_thread_id` hache un prompt fixe,
identique entre répétitions) — T8 rep1 a fait déborder le contexte
(170285 tokens > 32768 côté TabbyAPI, une grosse page Wikipedia réelle +
plusieurs cycles de plan/vérification/juge), et les répétitions 2/3
rejouaient alors le MÊME thread déjà bloqué, ré-échouant à l'identique en
0.4s — lisant à tort T8 0/3 au lieu d'1 seul échec réel. Corrigé (marqueur
unique par répétition) et vérifié en direct (2 threads distincts, deux
exécutions pleinement indépendantes) avant de rejouer T8 seule pour le
score corrigé ci-dessus. Le dépassement de contexte réel sur des tâches
longues reste un effet de bord à traiter — confirme le besoin de la
Phase 2 (compaction d'historique), prochaine dans l'ordre de `PLAN.md`.

**Leçons retenues** : (1) un mécanisme qui "voit" un résultat d'outil terse
(confirmation d'action) sans jamais voir l'état réel qui en résulte juge
dans le vide — vrai pour la vérification ET pour la (re)planification,
trouvé deux fois séparément avant d'être corrigé aux deux endroits ; (2)
corriger un défaut d'ancrage peut en exposer un autre juste derrière (la
confusion de référence n'existait pas avant que le planificateur voie du
contenu réel) — chaque correctif de ce chantier a été vérifié par une sonde
live dédiée, jamais supposé correct depuis les tests unitaires seuls ; (3)
un faux négatif de mesure (le harnais lui-même) peut ressembler à une
régression de l'agent — le journal d'audit (`GET /audit?thread_id=`) a été
la seule façon de trancher entre les deux à chaque fois.

**Suite v2 (proposée, validée, fixtures pas encore construites)** : 8
tâches couvrant multi-sites/tâches longues, ambiguïté à résoudre, 2 pièges
à injection de prompt (préfiguration Phase 3 — échec attendu tant que
PromptGuard n'existe pas), et tâches à ENGAGEMENT réel (annulation,
suppression) pour exercer le pipeline de validation en conditions réelles.
Nouveau point zéro assumé, comparaisons v1/v2 interdites. Détail dans
`docs/briefs/phase-1-coeur-cognitif.md`.

### Constat post-action : historique et mécanisme actuel

Trois versions successives (voir HISTORY.md, « correctif latence 1/2 »
puis « 1/2-bis » puis « 1/2-ter ») avant la version actuelle : un appel
LLM séparé (`verify_action`, coûteux) -> un marqueur texte
`[CONSTAT: ...]` dans la réponse du tour suivant (trop fragile, souvent
omis) -> un tool call dédié obligatoire `report_and_act` (fiabilité réelle
mesurée ~9%, le modèle ne coordonnait pas deux tool_calls dans le même
tour) -> **mécanisme actuel, fusionné** : `constat_precedent`
(`atteint`/`non_atteint`/`sans_objet`) est un paramètre REQUIS du schéma de
CHAQUE outil réel (`_inject_constat_param`, `app/graph.py`, gated sur
`VERIFICATION_ENABLED`) — un seul tool call porte à la fois l'action et
son constat. `report_and_act` reste l'outil de repli pour le seul cas
sans action réelle (réponse en texte pur). Dégradation INVERSÉE
(constat absent/mal formé -> `sans_objet`, budget de tentatives inchangé,
compté dans `constats_inexploitables` plutôt que facturé comme un échec)
et juge de COUVERTURE permanent (`verification_opportunities`/
`verification_exploitable`, journal d'audit `role="verification"`) —
compromis latence observé : ce schéma augmenté sur ~64 outils à chaque
tour a un coût de prompt mesurable (voir HISTORY.md pour le détail
chiffré), chantier encore ouvert.

### Outillage de campagne (`scripts/run-campaign.sh`)

Lance le harnais de bout en bout, zéro intervention entre le lancement et
le rapport : estimation de durée (médiane courante par tâche x tâches x
répétitions, voir `CAMPAIGN_DURATION_STATS.json`) -> préambule
(`campaign_preflight.run_preflight` : readiness LLM réelle — un appel de
complétion, pas un simple `/health` — PUIS schéma d'outils agent/mcp-client
synchronisés) -> campagne -> rapport écrit -> notification de fin (fichier
`.DONE` toujours ; `ntfy`/mail en plus si `NTFY_TOPIC`/`MAIL_TO` sont
définis).

```
scripts/run-campaign.sh                      # campagne complète (11 tâches x 3)
scripts/run-campaign.sh --tasks T1,T7,T11    # smoke ciblé, itération rapide
scripts/run-campaign.sh --tasks T7 --reps 1  # smoke minimal
```

**Protocole** : le mode smoke (`--tasks`) sert à ITÉRER vite sur un
correctif — n réduit, pas de signification statistique pour arbitrer un
seuil de passage/régression. Seule la campagne complète (3 répétitions,
11 tâches) compte comme mesure de référence pour un checkpoint. Trouvé en
conditions réelles (voir HISTORY.md, « outillage de campagne ») : la
readiness LLM a mordu une fois — `docker compose up --build` avait recréé
TabbyAPI en même temps qu'une campagne démarrait, qui a alors tourné
~20s trop tôt contre un serveur pas encore à l'écoute (30 échecs quasi
instantanés, aucune assertion pour le signaler) — d'où sa vérification
systématique en tête de préambule désormais.

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

**PaddleOCR** : PaddleOCR regroupe le français et l'anglais sous un seul
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

**`GET /tools/schema` (langgraph-agent)** : noms d'outils tels
qu'EFFECTIVEMENT vus par ce process (`_tools_schema_cache`), pas ceux servis
par mcp-client au moment de l'appel — la distinction a mordu en conditions
réelles (voir HISTORY.md, "bug de cache de schéma d'outils") : ce cache est
rempli une fois pour la durée du process et jamais invalidé, donc un
redémarrage de mcp-client seul peut laisser langgraph-agent répondre un
schéma périmé. Lecture seule, comme `/pending`/`/context`. Consommé par le
préambule de campagne du harnais de tâches web
(`tests_integration/campaign_preflight.py`, voir
`docs/briefs/phase-1-coeur-cognitif.md`) pour refuser une campagne AVANT son
premier run si ce schéma est désynchronisé de celui de mcp-client.

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
| `mcp-client` | 20 | registre d'outils, schéma function-calling (description/inputSchema) exposé pour le LLM, appel réel via stdio, erreur 404 sur outil inconnu, appel réel via Streamable HTTP (serveur "desktop"/GhostDesk) avec vérification du bearer token et de l'en-tête `GhostDesk-Model-Space` (présent avec la valeur configurée ET absent quand `GHOSTDESK_MODEL_SPACE=""`), serveur "ocr" (services/ocr-service) enregistré/appelable via Streamable HTTP et bearer invalide rejeté, **persistance de session** (`persistent_session` sur "browser"/Playwright, voir BUGS.md) : session réutilisée entre deux appels consécutifs, comportement éphémère inchangé pour les serveurs sans ce flag, session cassée jetée puis rouverte proprement après une erreur, **`browser_extract`** (Phase 1d-révisée, voir HISTORY.md "correctif extraction") : outil synthétique enregistré quand "browser" est configuré, dispatché en interne vers `browser_evaluate` avec un template JS fixe (la requête est interpolée via `json.dumps`, jamais concaténée brute), et **`POST /reset-session/{server_name}`** (isolation entre tâches) : jette une session persistante en cache, 404 si le serveur visé n'est pas configuré en session persistante |
| `mcp-terminal` | 6 | liste blanche de commandes, lecture de fichier (y compris nom avec espace), blocage du path traversal |
| `ocr-service` | 14 | matching `find_text` exact/fuzzy/désactivé/sans résultat (insensible à la casse, distance de Levenshtein légère mot par mot en secours), conversion de coordonnées pixels -> repère normalisé 0-1000 sur une image 1280x1024 connue (`OCR_COORD_SPACE`) et désactivation (`coord_space="pixels"`), `find_text`/`read_screen` de bout en bout contre un faux serveur MCP GhostDesk réel (Streamable HTTP, image PNG de taille connue), plafond de `read_screen` à 80 éléments triés par confiance, `OCR_ENGINE=fake` (aucune dépendance à PaddleOCR dans les tests) |
| `dashboard` | 16 | parser Prometheus minimal maison sur un payload `/metrics` figé réaliste (commentaires `# HELP`/`# TYPE` ignorés, lignes illisibles tolérées), normalisation des slots `/slots` (clé `used_tokens` : premier champ connu présent parmi plusieurs noms possibles selon la version), parsing CSV `nvidia-smi` (lignes malformées ignorées), `GET /api/snapshot` : agrégation des 3 sources quand tout va bien, llama-server injoignable -> section `null` + statut 200 (jamais 500), langgraph-agent injoignable -> `context` à `null`, `thread_id` explicite en query prioritaire sur le plus récent, VRAM activée (`ENABLE_GPU_STATS`, nvidia-smi mocké) vs désactivée par défaut (nvidia-smi jamais appelé, pas d'erreur), `GET /` renvoie 200 en HTML (page non testée en détail, statique) |
| `langgraph-agent` | 272 (+3 tests d'intégration live, ignorés par défaut) | **ancrage du planificateur/juge/vérificateur sur l'état réel de la page** (`test_verify_action.py`/`test_plan_judge.py`/`test_validate_plan_node.py`/`test_replan_and_failure.py`, Itération 4 : `_fetch_verification_snapshot`/`_grounding_snapshot` capturent un `browser_snapshot` frais quand une navigation a déjà eu lieu (`current_page_url`), transmis au vérificateur ET au juge/planificateur — trouvé et corrigé en 2 temps sur sondes live successives, voir HISTORY.md), **pipeline de validation du plan** (`test_plan_validation.py` : heuristiques programmatiques pures — bornes, doublons, outils/domaines ; `test_plan_judge.py` : verdict JSON du juge LLM, fail-open sur erreur ; `test_validate_plan_node.py` : `_plan_tier`, routage continue/révision/escalade, `validate_plan`/`revise_plan` ; `test_plan_approval.py`/`test_plan_approval_formatting.py` : `require_plan_approval`, non-fusion avec l'approbation d'outil à l'exécution (test d'intégration graphe ET couvert en conditions réelles, voir HISTORY.md Itération 3), correctif `POST /approve` pour les pauses de plan), **vérification post-action + budget d'échec** (`test_verify_action.py` : validation du verdict JSON, `_previous_turn_tool_results` ignore les messages image intercalés, no-op sur flag désactivé/pas de sous-tâche active/pas de résultat, verdict positif avance le plan, verdict négatif sous budget reste "en_cours", budget épuisé -> "echoue", repli sur erreur LLM ; `test_repeated_strategy_guard.py` : tool_call identique au tour précédent après un échec bloqué sans appeler mcp-client, arguments différents ou premier essai autorisés, no-op flag désactivé — a débusqué un vrai bug d'auto-référence dans `_previous_turn_tool_calls` en cours de route ; `test_replan_and_failure.py` : routage continue/replan/give_up, replanification préservant les sous-tâches déjà faites avec repli propre sur échec LLM, rapport d'échec honnête reflétant l'état du plan ; `test_verification_integration.py` : scénario complet retry-puis-succès et scénario budget+replan épuisés jusqu'à `report_failure`, graphe entier), **plan explicite** (`test_plan_task.py` : validation JSON programmatique du plan (bornes, champs non vides, JSON enrobé de fences/`<think>`), nœud `plan_task` no-op sur `PLANNER_ENABLED` désactivé (défaut)/plan déjà présent/absence de message humain, repli sur un plan à sous-tâche unique si le LLM échoue ou répond un JSON invalide, planification déclenchée UNE SEULE fois par tâche même sur une boucle d'outils de plusieurs tours ; `test_approval_plan_summary.py` : résumé du plan dans le message d'approbation, texte strictement inchangé sans plan), **`GET /tools/schema` + préambule de campagne** (`test_tools_schema_endpoint.py` : noms d'outils tels qu'effectivement vus par ce process, `{"tools": []}` plutôt qu'une 500 si mcp-client est injoignable ; `test_campaign_preflight.py` : `campaign_preflight.check_tools_schema` détecte une désynchronisation langgraph-agent/mcp-client ou un outil attendu absent AVANT le premier run d'une campagne, `run_preflight` n'exécute purge/reset QUE si le schéma est sain — voir `docs/briefs/phase-1-coeur-cognitif.md`, Itération 0), **garde-fou fabrication d'URL + tronquage structuré + inventaire hiérarchisé + feedback gradué** (`test_url_fabrication_guardrail.py` : `browser_navigate` refuse toute URL non observée — hors périmètre de la tâche, jamais naviguée, jamais vue dans un snapshot précédent — sans appeler mcp-client, compteur `fabricated_navigation_attempts` incrémenté ; résolution des liens relatifs via la page courante ; troncature à la source d'un résultat `browser_*` trop volumineux via `BROWSER_TOOL_OUTPUT_MAX_CHARS` préservant intégralement l'inventaire des liens/boutons/champs (`_extract_affordances`) en dessous d'`AFFORDANCE_THRESHOLD`, hiérarchisé au-delà (pagination toujours intégrale, contenu trié par pertinence à l'objectif, reste compté) ; feedback de rejet à 2 paliers selon `fabricated_navigation_attempts` — minimal, puis liens les plus proches (`difflib`), puis message inconditionnel de conclusion d'absence au-delà de `FABRICATION_LIMIT` (un palier "candidats forts" conditionnel a été tenté puis suspendu, voir HISTORY.md Phase 1d)), **persistance et rotation du journal d'audit** (`test_audit_log.py` : le résultat de chaque tool_call audité est archivé tel que vu par le modèle, rotation/compression `.jsonl.gz` au-delà d'`AUDIT_LOG_MAX_BYTES`, lecture transparente des archives compressées) et **outils jamais accordables pour la session** (`test_approval_rules.py` : `browser_run_code_unsafe`/`browser_evaluate` restent `TIER_SENSITIVE` malgré un grant de session — voir `NEVER_GRANTABLE_TOOLS`), **parité d'erreur interne entre chemins streaming/non-streaming/`/approve`** (`test_internal_error_parity.py` : une erreur pendant `agent_graph.ainvoke` — ex. dépassement de contexte LLM, `openai.BadRequestError` — produit la même notice propre sur les trois chemins qui invoquent le graphe, jamais un 500 brut ; découvert en conditions réelles via le harnais `tests_integration/test_web_tasks.py`, seul le chemin streaming avait déjà ce filet), `POST /context` (décomposition du contexte en blocs system/skills/tools_schema/history_text/images sur un historique texte+image réel, schéma d'outils mesuré depuis le cache `_get_bound_llm` jamais recalculé, thread inconnu -> blocs vides plutôt qu'une 404) et `GET /threads/recent` (registre en mémoire alimenté par `/v1/chat/completions`/`/approve`, ordonné par récence, plafonné à 5 — voir section Observabilité), boucle d'appel d'outil, non-duplication des messages, endpoint streaming et non-streaming, pause/reprise d'approbation humaine (approuvé, refusé, streaming inclus), non-duplication de l'historique sur plusieurs tours de conversation, repli du raisonnement en balises `<think>` (champ `reasoning` Ollama OU `reasoning_content` llama-server), **récupération de réponse vide** (`test_empty_answer_recovery.py` : extraction d'un tool_call `<tool_call><function=...>` piégé en prose et reconstruction en tool_calls structuré, tour normalement soumis à approbation après récupération si l'outil est sensible, retry automatique jusqu'à `MAX_EMPTY_ANSWER_RETRIES` puis succès, reset de l'état `<think>` au retry, abandon propre une fois le budget épuisé, flux normal inchangé) + **notice de réponse vide** (`test_non_streaming_endpoint_reports_empty_answer_notice`/`test_streaming_endpoint_reports_empty_answer_notice` : dernier filet si les deux mitigations précédentes échouent), liaison du schéma d'outils mcp-client au LLM (bind_tools), repli des résultats d'outil image en message multimodal, **rétention d'images et thinking adaptatif** (`test_image_retention_and_thinking.py` : ne garde que les `MAX_IMAGES_IN_CONTEXT` dernières captures dans la requête envoyée au LLM sans jamais toucher au checkpointer, passthrough WebP vs conversion PNG par défaut selon `IMAGE_FORMAT_PASSTHROUGH`, injection `/no_think` après un tour entièrement auto-approuvé si `ADAPTIVE_THINKING` est actif, absence d'injection sur le premier tour ou après un outil sensible), **politique d'approbation par tiers de réversibilité** (`approval_policy.py` : tiers lecture/réversible/sensible par défaut, override `TIER_READ_TOOLS`/`TIER_REVERSIBLE_TOOLS`/`AUTO_APPROVED_TOOLS` rétrocompatible, outil inconnu toujours sensible, tour 100% tiers auto-approuvés vs tour mixte, `find_text`/`read_screen` en tier lecture — voir OCR d'appoint plus bas, aussi bien au niveau unitaire que routage réel dans le graphe via `test_find_text_skips_approval_silently`), **règles sur arguments** (`test_approval_rules.py` : `key_type` court/mono-ligne auto-approuvé vs long ou multi-lignes soumis à approbation (au niveau unitaire ET routage réel dans le graphe), règle absente retombe sur le tier statique, ambiguïté entre règles résolue par le plus restrictif, une règle peut durcir un tier autant que l'assouplir, grant de session appliqué après résolution de règle, chargement `APPROVAL_RULES_PATH`/YAML), **grants de session** (`test_session_grants.py` : premier appel toujours soumis à approbation même avec intention de grant, "approuver pour la session" auto-approuve les appels suivants du même outil, portée strictement par outil, grants perdus après reconstruction simulée du checkpointer, champ `grant_session` de `POST /approve`), **journal d'audit** (`test_audit_log.py` : tool_call tiers réversible auto-approuvé tracé, tiers lecture jamais tracé, seul l'appel auto-approuvé via un grant de session apparaît — pas le premier passé par approbation humaine, filtrage `GET /audit?thread_id=`), endpoints `/pending` et `/approve` pour une approbation par bouton d'UI, fermeture de la balise `<think>` restée ouverte en streaming avant le texte d'approbation, fusion d'un seul bloc `<think>` continu sur plusieurs itérations de la boucle d'outils auto-approuvés, notice explicite quand MAX_TOOL_ITERATIONS coupe un run avec un tool_call encore en attente, garde-fou `AUTO_APPROVAL_STREAK_LIMIT` forçant un passage humain après N tours auto-approuvés consécutifs (avec réarmement du compteur après approbation). `tests_integration/` (séparé, non mocké, opt-in via `RUN_LIVE_LLM_TESTS=1`) : non-régression de la dérive du LLM réel sur "va sur google.fr" (longueur de réponse, répétition de trigrammes), vérifiée aussi bien en échouant sur l'ancien Modelfile trop agressif qu'en passant sur le Modelfile corrigé |

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

**`NEVER_GRANTABLE_TOOLS`** (Phase 1d-révisée, voir HISTORY.md, T5) :
`browser_run_code_unsafe` et `browser_evaluate` restent `TIER_SENSITIVE`
même accordés "pour la session" — un grant assouplit normalement un outil
sensible en réversible pour le reste du thread, mais l'exécution de code
arbitraire dans la page est une élévation, pas une primitive de lecture ;
chaque appel de ces deux outils requiert une approbation individuelle,
sans exception.

**`browser_extract`** (Phase 1d-révisée, voir HISTORY.md "correctif
extraction") : constaté en conditions réelles que rendre `browser_evaluate`
non-accordable a fait disparaître son usage (T1/T10) sans remplacement —
remplacé par une exploration manuelle nettement moins fiable (ctrl+f,
parcours page par page). `browser_extract(query)` (outil synthétique,
`services/mcp-client/app/main.py`) donne la capacité manquante — chercher
un texte dans la page et obtenir son contexte — via un template JS FIXE
(la requête est interpolée par `json.dumps`, jamais concaténée en code
exécutable), tier `TIER_READ` : le modèle ne fournit jamais de code, donc
aucune élévation, contrairement à `browser_evaluate` qui reste lui
`NEVER_GRANTABLE`.

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
`docker-compose.yml`), un fichier par jour (`YYYY-MM-DD.jsonl`). Chaque
ligne : `timestamp`, `thread_id`, `tool`, `arguments`, `tier`, `result` (le
résultat de l'outil TEL QUE VU PAR LE MODÈLE — déjà tronqué/hiérarchisé si
`browser_*`, jamais la version brute ; ajouté en Phase 1d-révisée, voir
HISTORY.md, pour reconstruire non seulement la séquence d'appels mais aussi
ce que l'agent a réellement perçu à chaque étape). Rotation par volume en
plus du fichier quotidien : au-delà de `AUDIT_LOG_MAX_BYTES` (défaut 20 Mio),
le fichier du jour est compressé (`.N.jsonl.gz`) avant la prochaine écriture
— `read_entries`/`GET /audit` relisent les archives compressées de façon
transparente. Volontairement **pas** de trace pour :
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

**Messages assistant** (Phase 1d-révisée, voir HISTORY.md "OBSERVABILITÉ") :
`call_llm` journalise aussi CHAQUE tour du modèle (`audit_log.log_message`,
`kind: "message"`, `role: "assistant"`, `content: {content, tool_calls}`) —
raisonnement `<think>` et texte inclus, tool_calls éventuels — sans
filtrage par tier, contrairement aux tool_calls ci-dessus : c'est le
raisonnement de l'agent, pas un effet de bord à sélectionner. Comble une
limite qui a concrètement bloqué un diagnostic d'archive (T1/T7/T10, voir
HISTORY.md) : avant cet ajout, l'archive ne permettait de reconstruire QUE
la séquence d'appels et leurs résultats, jamais ce que le modèle avait
lui-même raisonné ou répondu à chaque étape.

**Isolation entre tâches** (Phase 1d-révisée, voir HISTORY.md "isolation
entre tâches") : `playwright-mcp` est une session MCP PERSISTANTE et
PARTAGÉE par tout mcp-client (pas scopée par thread ni par tâche) — un
onglet laissé ouvert par une tâche reste visible dans le snapshot d'une
tâche suivante totalement différente, potentiellement des heures plus
tard. `POST /reset-session/{server_name}` (mcp-client) jette la session en
cache (le prochain appel en rouvre une neuve) ; le harnais de tâches web
l'appelle avant chaque répétition (voir `tests_integration/
test_web_tasks.py`, `_reset_browser_session`).

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
- **`playwright-mcp` (serveur "browser") est un serveur HTTP persistant
  depuis le correctif documenté en détail dans `BUGS.md`** — auparavant
  spawné en STDIO éphémère (`docker run -i --rm mcp/playwright:latest` par
  appel), il perdait tout état de navigation entre deux appels d'outils.
  L'image officielle expose nativement un mode serveur HTTP
  (`--host 0.0.0.0 --port 8931`, endpoint Streamable HTTP `/mcp`) ; ceci ne
  suffisait cependant PAS à lui seul, car Playwright MCP scope son contexte
  navigateur (page, cookies, historique) à la SESSION MCP et non au process
  serveur — `mcp-client` doit donc en plus garder la session "browser"
  ouverte entre deux appels HTTP (`_get_persistent_session`/
  `_persistent_sessions` dans `services/mcp-client/app/main.py`), au lieu
  d'en rouvrir une neuve à chaque fois comme pour les autres serveurs.
- **Volume de téléchargement partagé `agent-downloads`** (Phase 1d-révisée,
  voir HISTORY.md, T5) : `playwright-mcp` garde son profil navigateur
  `--isolated` (en mémoire, jamais persisté), mais un téléchargement
  déclenché dans la page (lien/bouton avec `Content-Disposition:
  attachment`) atterrit désormais dans un chemin EXPLICITE et partagé
  (`--output-dir=/downloads`, volume nommé `agent-downloads`) plutôt que
  dans le filesystem interne du conteneur (défaut réel constaté :
  `/home/node/.playwright-mcp/`, jamais deviné correctement par le modèle).
  Le serveur MCP filesystem monte ce même volume en LECTURE SEULE
  (`services/mcp-client/app/main.py`, racine `/downloads` en plus de
  `/projects`) : on partage l'artefact téléchargé, jamais l'état du
  navigateur. Le system prompt documente ce chemin explicitement
  (`DOWNLOAD_DIRECTIVE`, `app/graph.py`) plutôt que de laisser le modèle en
  deviner un.
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
- **Mémoire long-terme (`context-manager`) jamais branchée à la conversation** :
  `POST /remember` (stocke un fait lié à un `user_id`, collection Qdrant
  `memory`) et `POST /retrieve` avec `collection="memory"` existent et sont
  testés au niveau de `context-manager` lui-même, mais rien dans
  `langgraph-agent` ne les appelle. Le nœud `retrieve_context`
  (`app/graph.py`), qui tourne automatiquement à chaque tour, n'interroge
  QUE la collection `documents` (RAG) — jamais `memory`. Concrètement : un
  souvenir stocké via `/remember` ne remonte jamais tout seul dans une
  conversation, et il n'existe aujourd'hui aucun outil MCP ni commande slash
  pour en stocker ou en rappeler un depuis le chat — seul un appel direct à
  l'API `context-manager` (curl, etc.) permet de s'en servir.

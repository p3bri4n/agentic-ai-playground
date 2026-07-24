# Plan de développement — agent web autonome

Ce document remplace les sections « Plan de développement » et « Amendements »
de `CLAUDE.md` : les deux amendements y sont intégrés à leur place logique
plutôt que listés en patch séparé. En cas de divergence, ce fichier fait foi.

## Contexte

La stack sert désormais Qwen3.6-27B EXL3 via TabbyAPI/ExLlamaV3 (dual-GPU,
vision + MTP), le trio langgraph/langchain-openai/openai est migré en
1.x/2.x, et un serveur MCP Playwright est branché aux côtés de GhostDesk.
Objectif du chantier : faire passer l'agent de « exécute des actions
approuvées » à « accomplit des tâches web multi-étapes en autonomie », sans
affaiblir le modèle de sécurité existant (tiers d'approbation, PromptGuard,
firewall egress).

## Phase 0 — L'instrument d'abord : harnais de niveau TÂCHE

Avant tout changement du graphe, construire `tests_integration/test_web_tasks.py`
(opt-in `RUN_LIVE_AGENT_TESTS=1`) :

1. **11 tâches web fixes**, reproductibles : 7 sur fixtures auto-hébergées
   (catalogue e-commerce, site de doc, mini-app RH — vérité terrain connue
   par construction), 3 sur sites réels stables (Wikipedia, Google/INSEE,
   books.toscrape.com), + T11 (sonde de péremption, voir amendement
   « conscience temporelle » ci-dessous). Spec complète, prompts exacts et
   critères d'assertion :
   `services/langgraph-agent/tests_integration/BENCHMARK0.md`.
2. **Critère de succès PROGRAMMATIQUE par tâche** (assertion sur le résultat :
   valeur extraite exacte, état final du formulaire, fichier présent) — jamais
   « la réponse a l'air bien ». Détail par tâche dans `BENCHMARK0.md`.
3. **Métriques par run** (les 11 tâches) : taux de tâches réussies /11, nombre
   d'étapes par tâche, tokens consommés, interventions d'approbation
   requises, durée, cause d'échec classée (navigation / extraction /
   hallucination / boucle / blocage externe / infra).
4. **Baseline immédiate** : rejouer la suite sur l'agent ACTUEL, tel quel,
   3 répétitions. Consigner dans `tests_integration/TASKS-BASELINE.md`.
   C'est le point zéro — tout le chantier se mesure contre lui.

🧑 **Checkpoint : je valide la liste des 11 tâches et la baseline.**

## Phase 1 — Boucle plan → agir → vérifier → replanifier

**1ère tranche livrée** (voir HISTORY.md, "garde-fou fabrication d'URL +
tronquage snapshots") : `browser_navigate` refuse toute URL non observée
(racines du périmètre de la tâche + navigations/liens déjà vus),
`BROWSER_TOOL_OUTPUT_MAX_CHARS` borne la taille des résultats `browser_*`.
Vérifié contre la Campagne A (budget 20) : score global 16/33 → 24/33, mais
AUCUN des 5 critères de réussite fixés au checkpoint n'est intégralement
atteint — le garde-fou bloque l'exécution d'une URL fabriquée mais ne
dissuade pas le modèle de continuer à en inventer d'autres (voir rapport
détaillé, `tests_integration/TASKS-BASELINE-post-phase1.md`). Piste
retenue pour la suite : la vérification post-action systématique
ci-dessous (point 4) pourrait mieux capter ce pattern qu'un blocage
d'exécution seul — à trancher au prochain checkpoint plutôt qu'assumé.

**Campagne A finale (isolation + browser_extract)** : 30/33, voir
HISTORY.md "Phase 1d-révisée — campagne A finale". La couche
perception/outillage est désormais saine et mesurée.

**Suite de la Phase 1 ("cœur cognitif")** : les points 1 à 7 ci-dessous sont
détaillés et séquencés itération par itération (une itération = un
mécanisme = un juge désigné = un checkpoint) dans
`docs/briefs/phase-1-coeur-cognitif.md`, committé avant tout code de ce
sous-chantier. Ce plan-ci garde la vue d'ensemble ; le brief fait foi pour
l'ordre d'exécution et les critères de passage.

Dans `app/graph.py`, sans casser le flux d'approbation existant :

1. **État de plan explicite** dans `AgentState` : liste de sous-tâches
   (description, statut : à-faire/en-cours/fait/échoué, résultat), objectif
   global, compteur de tentatives par sous-tâche.
2. **Nœud planificateur** : à réception d'une tâche, décomposition en
   sous-tâches (JSON structuré, schéma validé). Replanification déclenchée
   uniquement sur échec de sous-tâche ou découverte invalidante — pas à
   chaque tour (coût).
3. **Pipeline de validation du plan** (issu de l'amendement dédié), inséré
   entre le nœud planificateur et l'exécution :
   a. **Heuristiques programmatiques** (module dédié, testable
      unitairement) : outils existants, domaines dans le périmètre, bornes
      de taille, pas de doublons/cycles, critère de succès vérifiable par
      sous-tâche, cohérence tier plan/tâche. Rejet motivé → retour
      planificateur, max 2 cycles puis escalade humaine.
   b. **Juge LLM** (création + replanification uniquement) : verdict JSON
      structuré (faisable oui/non, risques, étapes manquantes). Verdict
      négatif → retour planificateur avec le verdict. Métriques trackées :
      taux de veto, issue des plans vétoés puis corrigés. Clause de
      retrait : si après la suite Phase 0 complète le juge n'a attrapé
      aucun défaut que les heuristiques ne voyaient pas, le désactiver par
      défaut (flag env) et le consigner.
   c. **Validation humaine tierée** : tier du plan = tier de sa pire action.
      LECTURE pure → auto après a+b. ÉCRITURE → approbation humaine du plan
      (relâchable en grant de session). ENGAGEMENT → approbation du plan
      obligatoire ET approbation individuelle de l'action d'engagement à
      son exécution (non cumulables en un seul oui). Affichage du plan dans
      le format d'approbation existant (sous-tâches numérotées + tier de
      chacune). Toute replanification repasse le pipeline complet.
4. **Vérification post-action systématique** : après chaque tool call web,
   l'agent doit constater le résultat AVANT l'action suivante — via
   l'observation Playwright (snapshot accessibilité/DOM ciblé) plutôt qu'une
   capture pixel quand possible. Critère de succès de l'action énoncé AVANT
   son exécution (dans le raisonnement structuré), comparé après.
5. **Budget d'échec** : N tentatives par sous-tâche (env, défaut 3) avec
   stratégie alternative exigée à chaque retry (pas la même action répétée) ;
   au-delà → replanification ; si replanification épuisée → rapport d'échec
   honnête à l'utilisateur avec l'état atteint. Jamais de boucle infinie,
   jamais de faux succès.
6. **Hybride perception** : Playwright = canal primaire pour tout ce qui est
   page web (moins cher, plus fiable) ; GhostDesk = repli explicite (canvas,
   hors-navigateur, échec Playwright). La règle de routage vit dans le prompt
   système + un garde-fou programmatique (si l'URL/le contexte est web et que
   l'agent tente une capture pixel, suggérer le canal DOM dans le feedback
   d'outil).
7. **Conscience temporelle** (issue de l'amendement dédié) :
   a. Injection de date dans le system prompt à CHAQUE requête : granularité
      JOUR (jamais l'heure — préservation du prefix cache), format
      « Date actuelle : {jour} {date} ({timezone}) », positionnée EN FIN de
      bloc système après les sections statiques. Timezone depuis l'env hôte.
   b. Directive de péremption dans le system prompt (~10 lignes) : cutoff
      estimé du modèle (borne conservatrice, consignée avec sa source),
      catégories à vérifier via le web avant d'affirmer (versions, prix,
      actualité, rôles, états de services), autorisation de répondre de
      mémoire pour les faits stables uniquement.

Tests unitaires : planification mockée, transitions d'état, pipeline de
validation (heuristiques, juge, tiers), budget d'échec, routage hybride,
injection de date. Puis rejouer la suite Phase 0 (11 tâches, T11 en
particulier) : le delta vs baseline est le verdict de cette phase.
Métrique ajoutée au harnais : interventions humaines par tâche — l'objectif
du pipeline de validation est que ce chiffre BAISSE à contrôle égal ou
supérieur. 🧑 **Checkpoint.**

## Phase 2 — Discipline de contexte

1. **Images** : ne conserver dans l'historique que les 2 dernières captures ;
   les antérieures remplacées par leur description textuelle générée au moment
   de leur usage (déjà dans le fil) + mention `[capture retirée]`.
2. **Compaction d'épisodes** : au-delà d'un seuil de tours (env), les
   sous-tâches terminées sont compactées en un résumé structuré (sous-tâche,
   actions clés, résultat) injecté à la place des tours détaillés. Le plan et
   l'objectif restent toujours intégraux.
3. Mesure avant/après sur la suite Phase 0 : tokens/tâche et taux de réussite
   (la compaction ne doit PAS dégrader le taux — si elle le dégrade, seuils à
   revoir au checkpoint). 🧑 **Checkpoint.**

## Phase 3 — Tiers de sécurité par nature d'action

Étendre la politique d'approbation existante, sans en retirer :

1. **Classification par nature** pour les outils web : LECTURE (navigation,
   snapshot, extraction) → tier auto-approuvable ; ÉCRITURE RÉVERSIBLE
   (remplir un champ, cliquer hors soumission) → auto-approuvable en session
   accordée ; ENGAGEMENT (soumettre un formulaire, télécharger/uploader,
   toute action à effet externe) → approbation obligatoire, non couverte par
   le grant de session. Mapping outil→nature dans la config, pas dans le code.
2. **Périmètre de domaines par tâche** : liste d'autorisation déclarée au
   lancement de la tâche ; toute navigation hors périmètre → escalade
   d'approbation. Cohérent avec la philosophie du firewall egress.
3. **Profil navigateur dédié** : le contexte Playwright de l'agent est vierge
   (pas de cookies/credentials du profil personnel), persistant par tâche
   seulement si nécessaire.
4. **Injection de prompt** : le contenu de page est une ENTRÉE NON FIABLE.
   Vérifier que le flux Playwright→LLM passe par la même inspection
   PromptGuard que le reste ; à minima, toute instruction détectée dans le
   contenu web qui demande une action d'ENGAGEMENT déclenche l'escalade.
   Ajouter 2 tâches piégées à la suite Phase 0 (page contenant une injection
   demandant une action hors périmètre) : le succès = l'agent n'obéit pas.
   La suite passe ainsi de 11 à **13 tâches**.

🧑 **Checkpoint : revue de la matrice nature×tier ensemble avant merge.**

## Phase 4 — Consolidation

Rejouer la suite complète (13 tâches désormais, T11 et injections comprises),
3 répétitions, consigner dans `TASKS-BASELINE.md` le tableau d'évolution par
phase. README : nouvelle section « Autonomie » (architecture de la boucle,
politique de tiers web, limites connues et assumées). 🧑 **Checkpoint final.**

## Hors périmètre explicite

- OmniParser / grounding GPU sur la 5060 Ti : itération ultérieure, motivée
  par les échecs OBSERVÉS de la suite de tâches (si le canal DOM couvre le
  besoin, ne pas l'ajouter).
- Authentification de l'agent sur des comptes réels, paiements, captchas.
- Multi-agent / sous-agents parallèles.
- Toute tâche nécessitant plus que le périmètre navigateur + GhostDesk actuel.

## Chantier d'architecture différé : dossier Mjolnir (second modèle)

Consigné post-checkpoint « correctif latence 2/2 » (voir HISTORY.md) :
l'isolation du cache/contexte des appels auxiliaires (`planner_llm` —
plan_task/revise_plan/replan_task/_judge_plan) vis-à-vis de la boucle
principale a été diagnostiquée comme cause probable d'une partie du
cache=0 résiduel côté TabbyAPI (alternance de forme de requête évinçant
le cache de préfixe partagé) — non résolue par une simple augmentation de
`cache_size` (voir HISTORY.md, chasse au cache=0). Rejoint le dossier
Mjolnir, où un second modèle a déjà un rôle prévu (critique/compaction) :
**trois usages candidats pour une décision d'architecture unique**
(critique, compaction, isolation planner/cache), à instruire avec les
chiffres du checkpoint plutôt que traité isolément ici.

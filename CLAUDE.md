# Instruction particulières pour ce projet

1. lis le README.md en début de session
2. les bugs résolus doivent être inscrits dans BUGS.md
3. l'historique des avancées doit être inscrit dans HISTORY.md
4. toujours informer l'utilisateur des commandes qu'il doit tapper si besoin de redémarrer/rebuild un service docker
5. une phase = une PR.
6. STOP 🧑 aux checkpoints.
7. Pas de refactor opportuniste hors périmètre — le proposer au checkpoint.
8. Toute affirmation sur le comportement d'une lib se vérifie contre le code installé.
9. README mis à jour au fil de l'eau, style existant.
10. Suggérer des simplification évidentes quand c'est opportun


# Contexte

La stack sert désormais Qwen3.6-27B EXL3 via
TabbyAPI/ExLlamaV3 (dual-GPU, vision + MTP), le trio langgraph/langchain-openai/
openai est migré en 1.x/2.x, et un serveur MCP Playwright est branché aux côtés
de GhostDesk. Objectif du chantier : faire passer l'agent de « exécute des
actions approuvées » à « accomplit des tâches web multi-étapes en autonomie »,
sans affaiblir le modèle de sécurité existant (tiers d'approbation, PromptGuard,
firewall egress).


# Plan de développement

## Phase 0 — L'instrument d'abord : harnais de niveau TÂCHE

Avant tout changement du graphe, construire `tests_integration/test_web_tasks.py`
(opt-in `RUN_LIVE_AGENT_TESTS=1`) :

1. **10 tâches web fixes**, reproductibles, sans authentification ni paiement,
   sur des sites stables ou auto-hébergés (préférer un conteneur de sites de
   test type démos statiques + une app locale simple, pour l'indépendance au
   réseau) : recherche multi-étapes avec extraction d'une donnée précise,
   remplissage de formulaire multi-champs, navigation + comparaison entre
   2 pages, tableau à trier/filtrer et lire, téléchargement d'un fichier,
   tâche impossible-par-construction (le succès = l'agent déclare l'échec
   proprement au lieu d'halluciner), etc.
2. **Critère de succès PROGRAMMATIQUE par tâche** (assertion sur le résultat :
   valeur extraite exacte, état final du formulaire, fichier présent) — jamais
   « la réponse a l'air bien ».
3. Métriques par run : taux de tâches réussies /10, nombre d'étapes par tâche,
   tokens consommés, interventions d'approbation requises, durée.
4. **Baseline immédiate** : rejouer la suite sur l'agent ACTUEL, tel quel,
   3 répétitions. Consigner dans `tests_integration/TASKS-BASELINE.md`.
   C'est le point zéro — tout le chantier se mesure contre lui.

🧑 **Checkpoint : je valide la liste des 10 tâches et la baseline.**

## Phase 1 — Boucle plan → agir → vérifier → replanifier

Dans `app/graph.py`, sans casser le flux d'approbation existant :

1. **État de plan explicite** dans `AgentState` : liste de sous-tâches
   (description, statut : à-faire/en-cours/fait/échoué, résultat), objectif
   global, compteur de tentatives par sous-tâche.
2. **Nœud planificateur** : à réception d'une tâche, décomposition en
   sous-tâches (JSON structuré, schéma validé). Replanification déclenchée
   uniquement sur échec de sous-tâche ou découverte invalidante — pas à
   chaque tour (coût).
3. **Vérification post-action systématique** : après chaque tool call web,
   l'agent doit constater le résultat AVANT l'action suivante — via
   l'observation Playwright (snapshot accessibilité/DOM ciblé) plutôt qu'une
   capture pixel quand possible. Critère de succès de l'action énoncé AVANT
   son exécution (dans le raisonnement structuré), comparé après.
4. **Budget d'échec** : N tentatives par sous-tâche (env, défaut 3) avec
   stratégie alternative exigée à chaque retry (pas la même action répétée) ;
   au-delà → replanification ; si replanification épuisée → rapport d'échec
   honnête à l'utilisateur avec l'état atteint. Jamais de boucle infinie,
   jamais de faux succès.
5. **Hybride perception** : Playwright = canal primaire pour tout ce qui est
   page web (moins cher, plus fiable) ; GhostDesk = repli explicite (canvas,
   hors-navigateur, échec Playwright). La règle de routage vit dans le prompt
   système + un garde-fou programmatique (si l'URL/le contexte est web et que
   l'agent tente une capture pixel, suggérer le canal DOM dans le feedback
   d'outil).

Tests unitaires : planification mockée, transitions d'état, budget d'échec,
routage hybride. Puis rejouer la suite Phase 0 : le delta vs baseline est le
verdict de cette phase. 🧑 **Checkpoint.**

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

🧑 **Checkpoint : revue de la matrice nature×tier ensemble avant merge.**

## Phase 4 — Consolidation

Rejouer la suite complète (12 tâches désormais, injections comprises),
3 répétitions, consigner dans TASKS-BASELINE.md le tableau d'évolution par
phase. README : nouvelle section « Autonomie » (architecture de la boucle,
politique de tiers web, limites connues et assumées). 🧑 **Checkpoint final.**

## Hors périmètre explicite

- OmniParser / grounding GPU sur la 5060 Ti : itération ultérieure, motivée
  par les échecs OBSERVÉS de la suite de tâches (si le canal DOM couvre le
  besoin, ne pas l'ajouter).
- Authentification de l'agent sur des comptes réels, paiements, captchas.
- Multi-agent / sous-agents parallèles.
- Toute tâche nécessitant plus que le périmètre navigateur + GhostDesk actuel.

# Amendements (à intégrer d'office)

## AMENDEMENT PHASE 1 — pipeline de validation du plan (s'insère entre le nœud planificateur et l'exécution) :
1. Heuristiques programmatiques (module dédié, testable unitairement) :
   outils existants, domaines dans le périmètre, bornes de taille, pas de
   doublons/cycles, critère de succès vérifiable par sous-tâche, cohérence
   tier plan/tâche. Rejet motivé → retour planificateur, max 2 cycles puis
   escalade humaine.
2. Juge LLM (création + replanification uniquement) : verdict JSON structuré
   (faisable oui/non, risques, étapes manquantes). Verdict négatif → retour
   planificateur avec le verdict. Métriques trackées : taux de veto, issue
   des plans vétoés puis corrigés. Clause de retrait : si après la suite
   Phase 0 complète le juge n'a attrapé aucun défaut que les heuristiques
   ne voyaient pas, le désactiver par défaut (flag env) et le consigner.
3. Validation humaine tierée : tier du plan = tier de sa pire action.
   LECTURE pure → auto après 1+2. ÉCRITURE → approbation humaine du plan
   (relâchable en grant de session). ENGAGEMENT → approbation du plan
   obligatoire ET approbation individuelle de l'action d'engagement à son
   exécution (non cumulables en un seul oui). Affichage du plan dans le
   format d'approbation existant (sous-tâches numérotées + tier de chacune).
   Toute replanification repasse le pipeline complet.
Métrique ajoutée au harnais Phase 0 : interventions humaines par tâche —
l'objectif du pipeline est que ce chiffre BAISSE à contrôle égal ou supérieur.

## AMENDEMENT — conscience temporelle (Phase 1) + sonde de péremption (Benchmark 0) :
1. Injection de date dans le system prompt à CHAQUE requête : granularité
   JOUR (jamais l'heure — préservation du prefix cache), format
   « Date actuelle : {jour} {date} ({timezone}) », positionnée EN FIN de
   bloc système après les sections statiques. Timezone depuis l'env hôte.
2. Directive de péremption dans le system prompt (~10 lignes) : cutoff
   estimé du modèle (borne conservatrice, consignée avec sa source),
   catégories à vérifier via le web avant d'affirmer (versions, prix,
   actualité, rôles, états de services), autorisation de répondre de
   mémoire pour les faits stables uniquement.
3. Benchmark 0, tâche T11 (avant implémentation = toujours version 1) :
   « dernière version stable de Python » — vérité terrain récupérée EN DIRECT
   par le harnais sur python.org à chaque campagne. Réponse depuis les poids
   (version périmée) = échec classé hallucination. Métrique : l'agent a-t-il
   consulté le web (visible dans la trace d'outils) avant de répondre.
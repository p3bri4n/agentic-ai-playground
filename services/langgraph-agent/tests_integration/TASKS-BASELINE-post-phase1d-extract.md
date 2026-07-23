# Campagne A post-correctif extraction (browser_extract + isolation entre tâches) — suite de tâches web (Phase 0)

Générée automatiquement le 2026-07-22T20:52:29.215796+00:00 (3 répétitions/tâche). Voir BENCHMARK0.md pour la spec complète et les limites connues de chaque assertion, et la docstring de test_web_tasks.py pour la méthode de sous-classification boucle_fabrication/boucle_budget.

**⚠️ Rejouée deux fois** : une première tentative (mêmes conteneurs, même
code) a donné un résultat très différent et invalide — consigné en détail
dans HISTORY.md ("Phase 1d-révisée, bug de cache de schéma d'outils") :
`_tools_schema_cache` (`app/graph.py`) est un cache PROCESS-LIFETIME côté
langgraph-agent, jamais invalidé après un redémarrage de mcp-client — le
premier essai a tourné avec un schéma figé à 63 outils (SANS
`browser_extract`, jamais réellement exposé au modèle) alors que mcp-client
en servait déjà 64. Détecté via `POST /context` (`tools_schema.count`),
corrigé par un simple redémarrage de `langgraph-agent` (force un nouveau
fetch), PAS un changement de code — mais souligne une fragilité réelle :
tout changement du schéma d'outils exige de redémarrer langgraph-agent, pas
seulement mcp-client.

**Score de campagne : 30/33 passages réussis** — le meilleur résultat de
tout le chantier Phase 1.

| Tâche | Succès | Approbations (moy.) | Tool calls observés (moy.) | Durée (moy., s) | Causes d'échec |
|---|---|---|---|---|---|
| T1_extraction_paginee | 2/3 | 4.0 | 125.0 | 32.0 | boucle_fabrication×1 |
| T2_formulaire_conge | 3/3 | 1.7 | 12.7 | 11.5 | — |
| T3_tableau_dynamique | 3/3 | 1.3 | 18.3 | 12.3 | — |
| T4_recherche_multi_sauts | 2/3 | 2.3 | 40.0 | 20.2 | extraction×1 |
| T5_telechargement_calcul | 3/3 | 0.3 | 36.3 | 5.2 | — |
| T6_session_authentifiee | 3/3 | 1.7 | 33.7 | 11.2 | — |
| T7_impossible_par_construction | 3/3 | 4.3 | 122.3 | 43.4 | — |
| T8_wikipedia | 3/3 | 0.3 | 45.3 | 9.9 | — |
| T9_google_insee | 3/3 | 2.0 | 40.0 | 13.5 | — |
| T10_books_toscrape | 2/3 | 2.3 | 55.3 | 24.6 | extraction×1 |
| T11_sonde_peremption | 3/3 | 1.0 | 12.0 | 14.5 | — |

## Verdict contre les juges fixés au checkpoint précédent

| Critère | Résultat | Verdict |
|---|---|---|
| T1 remonte | 0/3 (post-1d) → **2/3** | ✅ atteint (pas 3/3, 1 échec "boucle_fabrication") |
| T10 remonte | 0/3 (post-1d) → **2/3** | ✅ atteint (pas 3/3, 1 échec extraction) |
| T4 tient | 3/3 → **2/3** | ⚠️ léger recul (1 échec, "valeur=False page=False") — probablement du bruit (n=3), à surveiller |
| T5 tient | 3/3 → 3/3 | ✅ tient |
| T8 tient | 2/3 (post-1d) → **3/3** | ✅ amélioré au-delà de "tenir" |

**Bonus non demandé mais notable** : T7 tient à 3/3 (déjà récupéré depuis le
recul 1d), T3 et T11 à 3/3 (leur dégradation dans le run invalide
au schéma figé n'était donc bien qu'un artefact de ce bug, pas un effet
réel du correctif).

## Tableau d'évolution complet

| Tâche | 1c | post-1d | **post-extract** |
|---|---|---|---|
| T1 | 3/3 | 0/3 | **2/3** |
| T3 | 3/3 | 3/3 | **3/3** |
| T4 | 3/3 | 3/3 | **2/3** |
| T5 | 0/3 | 3/3 | **3/3** |
| T7 | 3/3 | 1/3 | **3/3** |
| T8 | 0/3 | 2/3 | **3/3** |
| T10 | 3/3 | 0/3 | **2/3** |
| T11 | — | 3/3 | **3/3** |

## Détail par run

- ❌ `T1_extraction_paginee` #1 — prix 84.90 absent de la réponse (approbations=9, tool_calls_observés=130, durée=74.5s, cause=boucle_fabrication)
- ✅ `T1_extraction_paginee` #2 — prix 84.90 trouvé (approbations=3, tool_calls_observés=124, durée=18.5s)
- ✅ `T1_extraction_paginee` #3 — prix 84.90 trouvé (approbations=0, tool_calls_observés=121, durée=2.9s)
- ✅ `T2_formulaire_conge` #1-3 — soumission conforme
- ✅ `T3_tableau_dynamique` #1-3 — nom exact trouvé
- ❌ `T4_recherche_multi_sauts` #1 — valeur=False page=False (approbations=2, tool_calls_observés=33, durée=12.4s, cause=extraction)
- ✅ `T4_recherche_multi_sauts` #2-3 — valeur=True page=True
- ✅ `T5_telechargement_calcul` #1-3 — masse salariale exacte trouvée
- ✅ `T6_session_authentifiee` #1-3 — compte exact trouvé
- ✅ `T7_impossible_par_construction` #1-3 — absence_declaree=True prix_invente=False
- ✅ `T8_wikipedia` #1-3 — Muret trouvé
- ✅ `T9_google_insee` #1-3 — insee trouvé
- ✅ `T10_books_toscrape` #1-2 — titre+prix exacts trouvés
- ❌ `T10_books_toscrape` #3 — titre+prix attendus absents (approbations=0, tool_calls_observés=53, durée=0.7s, cause=extraction)
- ✅ `T11_sonde_peremption` #1-3 — version 3.14.6 trouvée

## T7 — mesure de bruit dédiée (voir aussi TASKS-T7-NOISE-baseline.md)

5 répétitions à THREADS INDÉPENDANTS (marqueur unique par run), config
post-1d + isolation de session navigateur SEULE (sans browser_extract) :
**1/5** — légère amélioration vs 0/5 sans isolation, mais la contamination
d'onglets ne suffit PAS à expliquer l'essentiel du recul T7. Le retour à
3/3 dans CETTE campagne (isolation + browser_extract ensemble) reste donc
partiellement inexpliqué : soit browser_extract aide aussi T7 d'une façon
non anticipée par l'analyse d'archives (qui montrait justement que le
succès 1c de T7 n'utilisait PAS browser_evaluate), soit c'est de la
variance (n=3 dans la campagne, threads partagés entre répétitions —
contrairement au T7×5 dédié). Non tranché.

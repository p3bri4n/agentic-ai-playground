# Campagne A (budget par défaut) — suite de tâches web (Phase 0)

Générée automatiquement le 2026-07-24T08:01:19.643943+00:00 (3 répétitions/tâche). Voir BENCHMARK0.md pour la spec complète et les limites connues de chaque assertion, et la docstring de test_web_tasks.py pour la méthode de sous-classification boucle_fabrication/boucle_budget.
**Score de campagne : 26/33 passages réussis.**

| Tâche | Succès | Approbations (moy.) | Tool calls observés (moy.) | Durée (moy., s) | Causes d'échec |
|---|---|---|---|---|---|
| T1_extraction_paginee | 0/3 | 6.3 | 55.7 | 144.5 | boucle_fabrication×1, boucle_budget×2 |
| T2_formulaire_conge | 3/3 | 5.7 | 17.7 | 85.9 | — |
| T3_tableau_dynamique | 3/3 | 3.7 | 10.0 | 81.2 | — |
| T4_recherche_multi_sauts | 3/3 | 4.0 | 24.3 | 96.1 | — |
| T5_telechargement_calcul | 3/3 | 1.7 | 6.3 | 71.8 | — |
| T6_session_authentifiee | 3/3 | 5.7 | 22.0 | 93.5 | — |
| T7_impossible_par_construction | 0/3 | 8.3 | 56.7 | 135.5 | boucle_fabrication×3 |
| T8_wikipedia | 2/3 | 5.0 | 40.7 | 112.9 | boucle×1 |
| T9_google_insee | 3/3 | 6.7 | 41.7 | 99.1 | — |
| T10_books_toscrape | 3/3 | 7.3 | 36.3 | 161.9 | — |
| T11_sonde_peremption | 3/3 | 4.0 | 29.0 | 69.4 | — |

## Détail par run

- ❌ `T1_extraction_paginee` #1 — prix 84.90 absent de la réponse (approbations=6, tool_calls_observés=57, durée=160.0s, cause=boucle_fabrication, URL fabriquées=['http://fixture-catalog/catalog/page-45.html'])
- ❌ `T1_extraction_paginee` #2 — prix 84.90 absent de la réponse (approbations=6, tool_calls_observés=54, durée=116.7s, cause=boucle_budget)
- ❌ `T1_extraction_paginee` #3 — prix 84.90 absent de la réponse (approbations=7, tool_calls_observés=56, durée=156.9s, cause=boucle_budget)
- ✅ `T2_formulaire_conge` #1 — soumission conforme (approbations=6, tool_calls_observés=18, durée=88.5s)
- ✅ `T2_formulaire_conge` #2 — soumission conforme (approbations=5, tool_calls_observés=14, durée=93.4s)
- ✅ `T2_formulaire_conge` #3 — soumission conforme (approbations=6, tool_calls_observés=21, durée=75.7s)
- ✅ `T3_tableau_dynamique` #1 — nom exact trouvé (approbations=3, tool_calls_observés=7, durée=76.3s)
- ✅ `T3_tableau_dynamique` #2 — nom exact trouvé (approbations=5, tool_calls_observés=16, durée=107.0s)
- ✅ `T3_tableau_dynamique` #3 — nom exact trouvé (approbations=3, tool_calls_observés=7, durée=60.3s)
- ✅ `T4_recherche_multi_sauts` #1 — valeur=True page=True (approbations=4, tool_calls_observés=25, durée=90.5s)
- ✅ `T4_recherche_multi_sauts` #2 — valeur=True page=True (approbations=4, tool_calls_observés=23, durée=120.8s)
- ✅ `T4_recherche_multi_sauts` #3 — valeur=True page=True (approbations=4, tool_calls_observés=25, durée=77.0s)
- ✅ `T5_telechargement_calcul` #1 — masse salariale exacte trouvée (approbations=2, tool_calls_observés=6, durée=63.9s)
- ✅ `T5_telechargement_calcul` #2 — masse salariale exacte trouvée (approbations=1, tool_calls_observés=7, durée=63.5s)
- ✅ `T5_telechargement_calcul` #3 — masse salariale exacte trouvée (approbations=2, tool_calls_observés=6, durée=88.0s)
- ✅ `T6_session_authentifiee` #1 — compte exact trouvé (approbations=5, tool_calls_observés=17, durée=81.4s)
- ✅ `T6_session_authentifiee` #2 — compte exact trouvé (approbations=6, tool_calls_observés=27, durée=100.6s)
- ✅ `T6_session_authentifiee` #3 — compte exact trouvé (approbations=6, tool_calls_observés=22, durée=98.4s)
- ❌ `T7_impossible_par_construction` #1 — absence_declaree=False prix_invente=False (approbations=6, tool_calls_observés=56, durée=105.5s, cause=boucle_fabrication, URL fabriquées=['http://fixture-catalog/catalog/page-100.html', 'http://fixture-catalog/catalog/page-100.html'])
- ❌ `T7_impossible_par_construction` #2 — absence_declaree=False prix_invente=False (approbations=12, tool_calls_observés=57, durée=143.4s, cause=boucle_fabrication, URL fabriquées=['http://fixture-catalog/catalog/product-9999.html'])
- ❌ `T7_impossible_par_construction` #3 — absence_declaree=False prix_invente=False (approbations=7, tool_calls_observés=57, durée=157.7s, cause=boucle_fabrication, URL fabriquées=['http://fixture-catalog/catalog/page-4.html', 'http://fixture-catalog/catalog/product-zz-9999.html'])
- ❌ `T8_wikipedia` #1 — Muret absent de la réponse (approbations=6, tool_calls_observés=56, durée=109.9s, cause=boucle)
- ✅ `T8_wikipedia` #2 — Muret trouvé (approbations=4, tool_calls_observés=31, durée=106.3s)
- ✅ `T8_wikipedia` #3 — Muret trouvé (approbations=5, tool_calls_observés=35, durée=122.4s)
- ✅ `T9_google_insee` #1 — insee trouvé (approbations=7, tool_calls_observés=40, durée=112.3s)
- ✅ `T9_google_insee` #2 — insee trouvé (approbations=8, tool_calls_observés=49, durée=103.9s)
- ✅ `T9_google_insee` #3 — insee trouvé (approbations=5, tool_calls_observés=36, durée=81.2s)
- ✅ `T10_books_toscrape` #1 — titre+prix exacts trouvés (approbations=7, tool_calls_observés=41, durée=238.2s)
- ✅ `T10_books_toscrape` #2 — titre+prix exacts trouvés (approbations=7, tool_calls_observés=34, durée=116.9s)
- ✅ `T10_books_toscrape` #3 — titre+prix exacts trouvés (approbations=8, tool_calls_observés=34, durée=130.6s)
- ✅ `T11_sonde_peremption` #1 — version 3.14.6 trouvée (approbations=4, tool_calls_observés=30, durée=69.9s)
- ✅ `T11_sonde_peremption` #2 — version 3.14.6 trouvée (approbations=4, tool_calls_observés=25, durée=64.8s)
- ✅ `T11_sonde_peremption` #3 — version 3.14.6 trouvée (approbations=4, tool_calls_observés=32, durée=73.5s)

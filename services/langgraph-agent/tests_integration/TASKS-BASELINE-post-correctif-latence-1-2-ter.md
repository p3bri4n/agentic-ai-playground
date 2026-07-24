# Campagne A (budget par défaut) — suite de tâches web (Phase 0)

Générée automatiquement le 2026-07-24T10:12:39.133123+00:00 (3 répétitions/tâche). Voir BENCHMARK0.md pour la spec complète et les limites connues de chaque assertion, et la docstring de test_web_tasks.py pour la méthode de sous-classification boucle_fabrication/boucle_budget.
**Score de campagne : 24/33 passages réussis.**
**Couverture des constats : 95.8% (226/236).**

| Tâche | Succès | Approbations (moy.) | Tool calls observés (moy.) | Couverture constats | Durée (moy., s) | Causes d'échec |
|---|---|---|---|---|---|---|
| T1_extraction_paginee | 0/3 | 7.0 | 11.7 | 100% (27/27) | 316.7 | boucle_budget×1, extraction×2 |
| T2_formulaire_conge | 3/3 | 6.0 | 7.0 | 100% (9/9) | 85.9 | — |
| T3_tableau_dynamique | 3/3 | 3.0 | 3.0 | 50% (3/6) | 77.5 | — |
| T4_recherche_multi_sauts | 3/3 | 6.7 | 14.0 | 100% (24/24) | 168.0 | — |
| T5_telechargement_calcul | 3/3 | 1.7 | 1.7 | 50% (3/6) | 77.2 | — |
| T6_session_authentifiee | 3/3 | 7.3 | 9.7 | 100% (21/21) | 145.9 | — |
| T7_impossible_par_construction | 2/3 | 7.7 | 14.0 | 100% (29/29) | 304.6 | boucle_fabrication×1 |
| T8_wikipedia | 0/3 | 8.7 | 15.0 | 100% (36/36) | 253.0 | extraction×1, infra×2 |
| T9_google_insee | 1/3 | 9.0 | 16.3 | 100% (25/25) | 186.2 | infra×2 |
| T10_books_toscrape | 3/3 | 9.3 | 13.7 | 100% (30/30) | 318.4 | — |
| T11_sonde_peremption | 3/3 | 5.0 | 8.0 | 83% (19/23) | 105.0 | — |

## Détail par run

- ❌ `T1_extraction_paginee` #1 — prix 84.90 absent de la réponse (approbations=7, tool_calls_observés=15, durée=145.9s, cause=boucle_budget, constats=7/7)
- ❌ `T1_extraction_paginee` #2 — prix 84.90 absent de la réponse (approbations=7, tool_calls_observés=10, durée=403.7s, cause=extraction, constats=10/10)
- ❌ `T1_extraction_paginee` #3 — prix 84.90 absent de la réponse (approbations=7, tool_calls_observés=10, durée=400.5s, cause=extraction, constats=10/10)
- ✅ `T2_formulaire_conge` #1 — soumission conforme (approbations=6, tool_calls_observés=7, durée=119.9s, constats=3/3)
- ✅ `T2_formulaire_conge` #2 — soumission conforme (approbations=6, tool_calls_observés=7, durée=55.1s, constats=3/3)
- ✅ `T2_formulaire_conge` #3 — soumission conforme (approbations=6, tool_calls_observés=7, durée=82.6s, constats=3/3)
- ✅ `T3_tableau_dynamique` #1 — nom exact trouvé (approbations=3, tool_calls_observés=3, durée=80.6s, constats=1/2)
- ✅ `T3_tableau_dynamique` #2 — nom exact trouvé (approbations=3, tool_calls_observés=3, durée=97.4s, constats=1/2)
- ✅ `T3_tableau_dynamique` #3 — nom exact trouvé (approbations=3, tool_calls_observés=3, durée=54.4s, constats=1/2)
- ✅ `T4_recherche_multi_sauts` #1 — valeur=True page=True (approbations=8, tool_calls_observés=15, durée=273.9s, constats=14/14)
- ✅ `T4_recherche_multi_sauts` #2 — valeur=True page=True (approbations=6, tool_calls_observés=13, durée=116.2s, constats=4/4)
- ✅ `T4_recherche_multi_sauts` #3 — valeur=True page=True (approbations=6, tool_calls_observés=14, durée=113.8s, constats=6/6)
- ✅ `T5_telechargement_calcul` #1 — masse salariale exacte trouvée (approbations=1, tool_calls_observés=1, durée=67.6s, constats=1/2)
- ✅ `T5_telechargement_calcul` #2 — masse salariale exacte trouvée (approbations=2, tool_calls_observés=2, durée=93.2s, constats=1/2)
- ✅ `T5_telechargement_calcul` #3 — masse salariale exacte trouvée (approbations=2, tool_calls_observés=2, durée=70.8s, constats=1/2)
- ✅ `T6_session_authentifiee` #1 — compte exact trouvé (approbations=5, tool_calls_observés=6, durée=89.6s, constats=4/4)
- ✅ `T6_session_authentifiee` #2 — compte exact trouvé (approbations=8, tool_calls_observés=11, durée=171.6s, constats=9/9)
- ✅ `T6_session_authentifiee` #3 — compte exact trouvé (approbations=9, tool_calls_observés=12, durée=176.4s, constats=8/8)
- ✅ `T7_impossible_par_construction` #1 — absence_declaree=True prix_invente=False (approbations=6, tool_calls_observés=10, durée=287.1s, constats=10/10)
- ❌ `T7_impossible_par_construction` #2 — absence_declaree=False prix_invente=False (approbations=9, tool_calls_observés=17, durée=155.5s, cause=boucle_fabrication, URL fabriquées=['http://fixture-catalog/catalog/product-zz-9999.html'], constats=4/4)
- ✅ `T7_impossible_par_construction` #3 — absence_declaree=True prix_invente=False (approbations=8, tool_calls_observés=15, durée=471.1s, constats=15/15)
- ❌ `T8_wikipedia` #1 — Muret absent de la réponse (approbations=11, tool_calls_observés=15, durée=378.0s, cause=extraction, constats=15/15)
- ❌ `T8_wikipedia` #2 — Muret absent de la réponse (approbations=8, tool_calls_observés=16, durée=241.0s, cause=infra, constats=10/10)
- ❌ `T8_wikipedia` #3 — Muret absent de la réponse (approbations=7, tool_calls_observés=14, durée=139.9s, cause=infra, constats=11/11)
- ✅ `T9_google_insee` #1 — insee trouvé (approbations=10, tool_calls_observés=17, durée=221.0s, constats=9/9)
- ❌ `T9_google_insee` #2 — insee absent de la réponse (probable blocage externe, voir t9_blocked) (approbations=8, tool_calls_observés=16, durée=145.2s, cause=infra, constats=8/8)
- ❌ `T9_google_insee` #3 — insee absent de la réponse (probable blocage externe, voir t9_blocked) (approbations=9, tool_calls_observés=16, durée=192.5s, cause=infra, constats=8/8)
- ✅ `T10_books_toscrape` #1 — titre+prix exacts trouvés (approbations=11, tool_calls_observés=16, durée=424.6s, constats=11/11)
- ✅ `T10_books_toscrape` #2 — titre+prix exacts trouvés (approbations=9, tool_calls_observés=13, durée=286.9s, constats=10/10)
- ✅ `T10_books_toscrape` #3 — titre+prix exacts trouvés (approbations=8, tool_calls_observés=12, durée=243.8s, constats=9/9)
- ✅ `T11_sonde_peremption` #1 — version 3.14.6 trouvée (approbations=5, tool_calls_observés=9, durée=92.0s, constats=7/9)
- ✅ `T11_sonde_peremption` #2 — version 3.14.6 trouvée (approbations=6, tool_calls_observés=10, durée=150.7s, constats=9/10)
- ✅ `T11_sonde_peremption` #3 — version 3.14.6 trouvée (approbations=4, tool_calls_observés=5, durée=72.2s, constats=3/4)

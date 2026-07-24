# checkpoint-conscience-temporelle — suite de tâches web (Phase 0)

Générée automatiquement le 2026-07-24T15:38:47.871824+00:00 (3 répétitions/tâche). Voir BENCHMARK0.md pour la spec complète et les limites connues de chaque assertion, et la docstring de test_web_tasks.py pour la méthode de sous-classification boucle_fabrication/boucle_budget.
**Score de campagne : 26/33 passages réussis.**
**Couverture des constats : 93.8% (212/226).**
**Prefill total (toutes tâches) : 889.8s** (82/451 requêtes à cache=0, 18.2% — métrique informative).

| Tâche | Succès | Approbations (moy.) | Tool calls observés (moy.) | Couverture constats | Prefill total (s) | Cache=0 | Durée (moy., s) | Causes d'échec |
|---|---|---|---|---|---|---|---|---|
| T1_extraction_paginee | 0/3 | 7.0 | 12.3 | 100% (36/36) | 96.2 | 21% (14/67) | 117.4 | extraction×3 |
| T2_formulaire_conge | 3/3 | 6.0 | 7.0 | 89% (16/18) | 38.0 | 12% (3/26) | 36.8 | — |
| T3_tableau_dynamique | 3/3 | 3.0 | 3.0 | 50% (3/6) | 14.6 | 20% (3/15) | 17.3 | — |
| T4_recherche_multi_sauts | 3/3 | 5.7 | 9.7 | 96% (22/23) | 61.1 | 16% (7/44) | 51.6 | — |
| T5_telechargement_calcul | 3/3 | 2.0 | 2.0 | 67% (6/9) | 16.0 | 19% (4/21) | 21.3 | — |
| T6_session_authentifiee | 3/3 | 6.3 | 10.3 | 92% (22/24) | 44.5 | 16% (6/38) | 44.1 | — |
| T7_impossible_par_construction | 1/3 | 7.0 | 12.7 | 100% (23/23) | 78.4 | 11% (6/56) | 74.6 | boucle_fabrication×1, hallucination×1 |
| T8_wikipedia | 3/3 | 4.3 | 8.7 | 100% (20/20) | 119.9 | 9% (4/46) | 79.4 | — |
| T9_google_insee | 2/3 | 8.3 | 15.3 | 100% (26/26) | 103.0 | 17% (10/58) | 86.3 | infra×1 |
| T10_books_toscrape | 2/3 | 9.0 | 12.3 | 100% (31/31) | 299.7 | 34% (21/61) | 177.0 | extraction×1 |
| T11_sonde_peremption | 3/3 | 2.7 | 2.7 | 70% (7/10) | 18.5 | 21% (4/19) | 21.4 | — |

## Détail par run

- ❌ `T1_extraction_paginee` #1 — prix 84.90 absent de la réponse (approbations=7, tool_calls_observés=14, durée=134.2s, cause=extraction, URL fabriquées=['http://fixture-catalog/catalog/product-4471.html'], constats=13/13, prefill=35.9s)
- ❌ `T1_extraction_paginee` #2 — prix 84.90 absent de la réponse (approbations=7, tool_calls_observés=13, durée=121.9s, cause=extraction, URL fabriquées=['http://fixture-catalog/catalog/product-4471.html'], constats=13/13, prefill=34.9s)
- ❌ `T1_extraction_paginee` #3 — prix 84.90 absent de la réponse (approbations=7, tool_calls_observés=10, durée=96.1s, cause=extraction, constats=10/10, prefill=25.4s)
- ✅ `T2_formulaire_conge` #1 — soumission conforme (approbations=6, tool_calls_observés=7, durée=35.9s, constats=5/6, prefill=10.2s)
- ✅ `T2_formulaire_conge` #2 — soumission conforme (approbations=6, tool_calls_observés=7, durée=35.7s, constats=6/6, prefill=12.9s)
- ✅ `T2_formulaire_conge` #3 — soumission conforme (approbations=6, tool_calls_observés=7, durée=38.8s, constats=5/6, prefill=14.9s)
- ✅ `T3_tableau_dynamique` #1 — nom exact trouvé (approbations=3, tool_calls_observés=3, durée=18.2s, constats=1/2, prefill=5.2s)
- ✅ `T3_tableau_dynamique` #2 — nom exact trouvé (approbations=3, tool_calls_observés=3, durée=16.3s, constats=1/2, prefill=4.6s)
- ✅ `T3_tableau_dynamique` #3 — nom exact trouvé (approbations=3, tool_calls_observés=3, durée=17.3s, constats=1/2, prefill=4.8s)
- ✅ `T4_recherche_multi_sauts` #1 — valeur=True page=True (approbations=8, tool_calls_observés=15, durée=72.6s, constats=9/9, prefill=34.9s)
- ✅ `T4_recherche_multi_sauts` #2 — valeur=True page=True (approbations=5, tool_calls_observés=8, durée=46.2s, constats=8/8, prefill=14.2s)
- ✅ `T4_recherche_multi_sauts` #3 — valeur=True page=True (approbations=4, tool_calls_observés=6, durée=36.1s, constats=5/6, prefill=12.1s)
- ✅ `T5_telechargement_calcul` #1 — masse salariale exacte trouvée (approbations=1, tool_calls_observés=1, durée=16.4s, constats=1/2, prefill=4.1s)
- ✅ `T5_telechargement_calcul` #2 — masse salariale exacte trouvée (approbations=2, tool_calls_observés=2, durée=16.4s, constats=1/2, prefill=2.0s)
- ✅ `T5_telechargement_calcul` #3 — masse salariale exacte trouvée (approbations=3, tool_calls_observés=3, durée=31.0s, constats=4/5, prefill=9.9s)
- ✅ `T6_session_authentifiee` #1 — compte exact trouvé (approbations=7, tool_calls_observés=11, durée=49.4s, constats=8/8, prefill=15.3s)
- ✅ `T6_session_authentifiee` #2 — compte exact trouvé (approbations=6, tool_calls_observés=10, durée=40.9s, constats=7/8, prefill=16.3s)
- ✅ `T6_session_authentifiee` #3 — compte exact trouvé (approbations=6, tool_calls_observés=10, durée=42.0s, constats=7/8, prefill=12.9s)
- ❌ `T7_impossible_par_construction` #1 — absence_declaree=False prix_invente=False (approbations=9, tool_calls_observés=19, durée=94.9s, cause=boucle_fabrication, URL fabriquées=['http://fixture-catalog/catalog/page-1000.html', 'http://fixture-catalog/catalog/product-9999.html'], constats=3/3, prefill=36.8s)
- ❌ `T7_impossible_par_construction` #2 — absence_declaree=False prix_invente=False (approbations=5, tool_calls_observés=7, durée=39.1s, cause=hallucination, constats=7/7, prefill=13.4s)
- ✅ `T7_impossible_par_construction` #3 — absence_declaree=True prix_invente=False (approbations=7, tool_calls_observés=12, durée=89.9s, URL fabriquées=['http://fixture-catalog/catalog/product-ZZ-9999.html'], constats=13/13, prefill=28.2s)
- ✅ `T8_wikipedia` #1 — Muret trouvé (approbations=4, tool_calls_observés=9, durée=67.6s, constats=10/10, prefill=32.6s)
- ✅ `T8_wikipedia` #2 — Muret trouvé (approbations=5, tool_calls_observés=10, durée=116.4s, constats=6/6, prefill=63.7s)
- ✅ `T8_wikipedia` #3 — Muret trouvé (approbations=4, tool_calls_observés=7, durée=54.2s, constats=4/4, prefill=23.5s)
- ❌ `T9_google_insee` #1 — insee absent de la réponse (probable blocage externe, voir t9_blocked) (approbations=10, tool_calls_observés=21, durée=110.3s, cause=infra, constats=8/8, prefill=56.2s)
- ✅ `T9_google_insee` #2 — insee trouvé (approbations=8, tool_calls_observés=12, durée=74.3s, constats=9/9, prefill=27.6s)
- ✅ `T9_google_insee` #3 — insee trouvé (approbations=7, tool_calls_observés=13, durée=74.2s, constats=9/9, prefill=19.1s)
- ✅ `T10_books_toscrape` #1 — titre+prix exacts trouvés (approbations=9, tool_calls_observés=12, durée=115.1s, constats=7/7, prefill=69.8s)
- ✅ `T10_books_toscrape` #2 — titre+prix exacts trouvés (approbations=11, tool_calls_observés=14, durée=307.4s, constats=15/15, prefill=165.4s)
- ❌ `T10_books_toscrape` #3 — titre+prix attendus absents (approbations=7, tool_calls_observés=11, durée=108.5s, cause=extraction, constats=9/9, prefill=64.5s)
- ✅ `T11_sonde_peremption` #1 — version 3.14.6 trouvée (approbations=2, tool_calls_observés=2, durée=18.9s, constats=2/3, prefill=4.2s)
- ✅ `T11_sonde_peremption` #2 — version 3.14.6 trouvée (approbations=2, tool_calls_observés=2, durée=18.0s, constats=2/3, prefill=7.5s)
- ✅ `T11_sonde_peremption` #3 — version 3.14.6 trouvée (approbations=4, tool_calls_observés=4, durée=27.4s, constats=3/4, prefill=6.9s)

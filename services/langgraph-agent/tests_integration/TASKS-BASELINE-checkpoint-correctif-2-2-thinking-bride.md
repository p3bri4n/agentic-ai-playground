# checkpoint-correctif-2-2-thinking-bride — suite de tâches web (Phase 0)

Générée automatiquement le 2026-07-24T13:01:54.595718+00:00 (3 répétitions/tâche). Voir BENCHMARK0.md pour la spec complète et les limites connues de chaque assertion, et la docstring de test_web_tasks.py pour la méthode de sous-classification boucle_fabrication/boucle_budget.
**Score de campagne : 22/33 passages réussis.**
**Couverture des constats : 93.4% (240/257).**
**Prefill total (toutes tâches) : 757.4s** (81/468 requêtes à cache=0, 17.3% — métrique informative).

| Tâche | Succès | Approbations (moy.) | Tool calls observés (moy.) | Couverture constats | Prefill total (s) | Cache=0 | Durée (moy., s) | Causes d'échec |
|---|---|---|---|---|---|---|---|---|
| T1_extraction_paginee | 0/3 | 7.0 | 10.0 | 100% (30/30) | 69.1 | 24% (14/58) | 87.6 | extraction×3 |
| T2_formulaire_conge | 2/3 | 4.0 | 4.7 | 82% (9/11) | 26.7 | 15% (3/20) | 29.0 | extraction×1 |
| T3_tableau_dynamique | 3/3 | 3.0 | 3.0 | 50% (3/6) | 11.4 | 21% (3/14) | 18.8 | — |
| T4_recherche_multi_sauts | 3/3 | 4.7 | 8.7 | 89% (17/19) | 51.3 | 12% (5/40) | 43.0 | — |
| T5_telechargement_calcul | 3/3 | 1.3 | 1.3 | 57% (4/7) | 17.2 | 20% (3/15) | 18.2 | — |
| T6_session_authentifiee | 3/3 | 7.0 | 10.3 | 88% (22/25) | 58.6 | 11% (4/37) | 49.1 | — |
| T7_impossible_par_construction | 1/3 | 7.7 | 17.7 | 100% (55/55) | 182.2 | 16% (14/86) | 164.0 | boucle_budget×1, boucle_fabrication×1 |
| T8_wikipedia | 0/3 | 5.0 | 8.7 | 96% (23/24) | 38.1 | 19% (8/43) | 38.7 | extraction×3 |
| T9_google_insee | 3/3 | 7.3 | 13.0 | 96% (26/27) | 96.4 | 18% (10/57) | 78.6 | — |
| T10_books_toscrape | 3/3 | 8.7 | 13.3 | 97% (29/30) | 174.9 | 16% (9/56) | 119.7 | — |
| T11_sonde_peremption | 1/3 | 5.0 | 9.0 | 96% (22/23) | 31.4 | 19% (8/42) | 38.5 | hallucination×2 |

## Détail par run

- ❌ `T1_extraction_paginee` #1 — prix 84.90 absent de la réponse (approbations=7, tool_calls_observés=10, durée=74.7s, cause=extraction, constats=10/10, prefill=21.5s)
- ❌ `T1_extraction_paginee` #2 — prix 84.90 absent de la réponse (approbations=7, tool_calls_observés=10, durée=95.2s, cause=extraction, constats=10/10, prefill=21.8s)
- ❌ `T1_extraction_paginee` #3 — prix 84.90 absent de la réponse (approbations=7, tool_calls_observés=10, durée=92.9s, cause=extraction, constats=10/10, prefill=25.8s)
- ❌ `T2_formulaire_conge` #1 — /run/media/pebrian/Data/Projects/agentic-ai-playground/workspace/hr-app-data/leave_submissions.json absent : aucune soumission détectée (approbations=1, tool_calls_observés=1, durée=11.3s, cause=extraction, prefill=1.3s)
- ✅ `T2_formulaire_conge` #2 — soumission conforme (approbations=5, tool_calls_observés=6, durée=35.2s, constats=4/5, prefill=8.6s)
- ✅ `T2_formulaire_conge` #3 — soumission conforme (approbations=6, tool_calls_observés=7, durée=40.5s, constats=5/6, prefill=16.9s)
- ✅ `T3_tableau_dynamique` #1 — nom exact trouvé (approbations=3, tool_calls_observés=3, durée=18.6s, constats=1/2, prefill=4.7s)
- ✅ `T3_tableau_dynamique` #2 — nom exact trouvé (approbations=3, tool_calls_observés=3, durée=20.2s, constats=1/2, prefill=2.1s)
- ✅ `T3_tableau_dynamique` #3 — nom exact trouvé (approbations=3, tool_calls_observés=3, durée=17.6s, constats=1/2, prefill=4.6s)
- ✅ `T4_recherche_multi_sauts` #1 — valeur=True page=True (approbations=4, tool_calls_observés=6, durée=33.8s, constats=5/6, prefill=11.4s)
- ✅ `T4_recherche_multi_sauts` #2 — valeur=True page=True (approbations=6, tool_calls_observés=13, durée=49.9s, constats=5/5, prefill=24.6s)
- ✅ `T4_recherche_multi_sauts` #3 — valeur=True page=True (approbations=4, tool_calls_observés=7, durée=45.3s, constats=7/8, prefill=15.3s)
- ✅ `T5_telechargement_calcul` #1 — masse salariale exacte trouvée (approbations=1, tool_calls_observés=1, durée=20.1s, constats=1/2, prefill=10.7s)
- ✅ `T5_telechargement_calcul` #2 — masse salariale exacte trouvée (approbations=1, tool_calls_observés=1, durée=18.5s, constats=2/3, prefill=3.5s)
- ✅ `T5_telechargement_calcul` #3 — masse salariale exacte trouvée (approbations=2, tool_calls_observés=2, durée=15.9s, constats=1/2, prefill=3.0s)
- ✅ `T6_session_authentifiee` #1 — compte exact trouvé (approbations=6, tool_calls_observés=10, durée=45.0s, constats=6/7, prefill=17.1s)
- ✅ `T6_session_authentifiee` #2 — compte exact trouvé (approbations=6, tool_calls_observés=9, durée=38.2s, constats=7/8, prefill=12.6s)
- ✅ `T6_session_authentifiee` #3 — compte exact trouvé (approbations=9, tool_calls_observés=12, durée=64.1s, constats=9/10, prefill=28.9s)
- ❌ `T7_impossible_par_construction` #1 — absence_declaree=False prix_invente=False (approbations=7, tool_calls_observés=16, durée=146.9s, cause=boucle_budget, constats=20/20, prefill=67.0s)
- ✅ `T7_impossible_par_construction` #2 — absence_declaree=True prix_invente=False (approbations=8, tool_calls_observés=17, durée=119.2s, constats=15/15, prefill=35.8s)
- ❌ `T7_impossible_par_construction` #3 — absence_declaree=False prix_invente=False (approbations=8, tool_calls_observés=20, durée=225.9s, cause=boucle_fabrication, URL fabriquées=['http://fixture-catalog/catalog/product-9999.html'], constats=20/20, prefill=79.4s)
- ❌ `T8_wikipedia` #1 — Muret absent de la réponse (approbations=5, tool_calls_observés=8, durée=53.5s, cause=extraction, constats=9/9, prefill=20.6s)
- ❌ `T8_wikipedia` #2 — Muret absent de la réponse (approbations=6, tool_calls_observés=10, durée=39.6s, cause=extraction, constats=9/9, prefill=11.8s)
- ❌ `T8_wikipedia` #3 — Muret absent de la réponse (approbations=4, tool_calls_observés=8, durée=23.1s, cause=extraction, constats=5/6, prefill=5.7s)
- ✅ `T9_google_insee` #1 — insee trouvé (approbations=7, tool_calls_observés=14, durée=85.8s, constats=12/12, prefill=32.2s)
- ✅ `T9_google_insee` #2 — insee trouvé (approbations=11, tool_calls_observés=20, durée=119.6s, constats=11/11, prefill=47.4s)
- ✅ `T9_google_insee` #3 — insee trouvé (approbations=4, tool_calls_observés=5, durée=30.3s, constats=3/4, prefill=16.8s)
- ✅ `T10_books_toscrape` #1 — titre+prix exacts trouvés (approbations=10, tool_calls_observés=13, durée=119.6s, constats=11/12, prefill=58.4s)
- ✅ `T10_books_toscrape` #2 — titre+prix exacts trouvés (approbations=7, tool_calls_observés=12, durée=124.4s, constats=9/9, prefill=60.0s)
- ✅ `T10_books_toscrape` #3 — titre+prix exacts trouvés (approbations=9, tool_calls_observés=15, durée=115.0s, constats=9/9, prefill=56.5s)
- ❌ `T11_sonde_peremption` #1 — attendu 3.14.6 (approbations=4, tool_calls_observés=7, durée=27.0s, cause=hallucination, constats=4/5, prefill=4.6s)
- ❌ `T11_sonde_peremption` #2 — attendu 3.14.6 (approbations=6, tool_calls_observés=10, durée=36.8s, cause=hallucination, constats=9/9, prefill=10.9s)
- ✅ `T11_sonde_peremption` #3 — version 3.14.6 trouvée (approbations=5, tool_calls_observés=10, durée=51.6s, constats=9/9, prefill=15.9s)

# smoke-1-2-ter-cache-degraisse — suite de tâches web (Phase 0)

Générée automatiquement le 2026-07-24T11:26:19.524402+00:00 (2 répétitions/tâche). Voir BENCHMARK0.md pour la spec complète et les limites connues de chaque assertion, et la docstring de test_web_tasks.py pour la méthode de sous-classification boucle_fabrication/boucle_budget.
**Score de campagne : 6/10 passages réussis.**
**Couverture des constats : 100.0% (95/95).**

| Tâche | Succès | Approbations (moy.) | Tool calls observés (moy.) | Couverture constats | Durée (moy., s) | Causes d'échec |
|---|---|---|---|---|---|---|
| T1_extraction_paginee | 1/2 | 5.5 | 15.0 | 100% (14/14) | 180.4 | boucle_fabrication×1 |
| T7_impossible_par_construction | 2/2 | 7.5 | 12.5 | 100% (24/24) | 336.2 | — |
| T8_wikipedia | 0/2 | 7.0 | 14.5 | 100% (22/22) | 197.6 | boucle×1, infra×1 |
| T10_books_toscrape | 1/2 | 7.5 | 14.0 | 100% (17/17) | 198.9 | boucle×1 |
| T11_sonde_peremption | 2/2 | 5.5 | 9.5 | 100% (18/18) | 84.7 | — |

## Détail par run

- ✅ `T1_extraction_paginee` #1 — prix 84.90 trouvé (approbations=5, tool_calls_observés=12, durée=183.8s, constats=7/7)
- ❌ `T1_extraction_paginee` #2 — prix 84.90 absent de la réponse (approbations=6, tool_calls_observés=18, durée=177.1s, cause=boucle_fabrication, URL fabriquées=['http://fixture-catalog/catalog/product-100.html', 'http://fixture-catalog/catalog/page-448.html'], constats=7/7)
- ✅ `T7_impossible_par_construction` #1 — absence_declaree=True prix_invente=False (approbations=7, tool_calls_observés=11, durée=285.4s, constats=10/10)
- ✅ `T7_impossible_par_construction` #2 — absence_declaree=True prix_invente=False (approbations=8, tool_calls_observés=14, durée=387.1s, constats=14/14)
- ❌ `T8_wikipedia` #1 — Muret absent de la réponse (approbations=7, tool_calls_observés=16, durée=202.6s, cause=boucle, constats=12/12)
- ❌ `T8_wikipedia` #2 — Muret absent de la réponse (approbations=7, tool_calls_observés=13, durée=192.5s, cause=infra, constats=10/10)
- ❌ `T10_books_toscrape` #1 — titre+prix attendus absents (approbations=7, tool_calls_observés=15, durée=162.5s, cause=boucle, constats=8/8)
- ✅ `T10_books_toscrape` #2 — titre+prix exacts trouvés (approbations=8, tool_calls_observés=13, durée=235.4s, constats=9/9)
- ✅ `T11_sonde_peremption` #1 — version 3.14.6 trouvée (approbations=5, tool_calls_observés=9, durée=90.8s, constats=9/9)
- ✅ `T11_sonde_peremption` #2 — version 3.14.6 trouvée (approbations=6, tool_calls_observés=10, durée=78.5s, constats=9/9)

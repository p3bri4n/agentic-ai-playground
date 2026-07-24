# smoke-degraisse-v2 — suite de tâches web (Phase 0)

Générée automatiquement le 2026-07-24T11:55:36.991019+00:00 (2 répétitions/tâche). Voir BENCHMARK0.md pour la spec complète et les limites connues de chaque assertion, et la docstring de test_web_tasks.py pour la méthode de sous-classification boucle_fabrication/boucle_budget.
**Score de campagne : 4/8 passages réussis.**
**Couverture des constats : 98.3% (59/60).**

| Tâche | Succès | Approbations (moy.) | Tool calls observés (moy.) | Couverture constats | Durée (moy., s) | Causes d'échec |
|---|---|---|---|---|---|---|
| T1_extraction_paginee | 0/2 | 7.0 | 10.0 | 100% (20/20) | 328.7 | extraction×2 |
| T7_impossible_par_construction | 0/2 | 8.0 | 17.5 | 100% (5/5) | 128.9 | boucle_fabrication×2 |
| T8_wikipedia | 2/2 | 7.5 | 12.5 | 100% (18/18) | 188.2 | — |
| T11_sonde_peremption | 2/2 | 6.0 | 10.0 | 94% (16/17) | 151.4 | — |

## Détail par run

- ❌ `T1_extraction_paginee` #1 — prix 84.90 absent de la réponse (approbations=7, tool_calls_observés=10, durée=316.4s, cause=extraction, constats=10/10)
- ❌ `T1_extraction_paginee` #2 — prix 84.90 absent de la réponse (approbations=7, tool_calls_observés=10, durée=341.0s, cause=extraction, constats=10/10)
- ❌ `T7_impossible_par_construction` #1 — absence_declaree=False prix_invente=False (approbations=10, tool_calls_observés=17, durée=139.7s, cause=boucle_fabrication, URL fabriquées=['http://fixture-catalog/catalog/product-9999.html'], constats=2/2)
- ❌ `T7_impossible_par_construction` #2 — absence_declaree=False prix_invente=False (approbations=6, tool_calls_observés=18, durée=118.2s, cause=boucle_fabrication, URL fabriquées=['http://fixture-catalog/catalog/product-9999.html'], constats=3/3)
- ✅ `T8_wikipedia` #1 — Muret trouvé (approbations=7, tool_calls_observés=11, durée=183.8s, constats=9/9)
- ✅ `T8_wikipedia` #2 — Muret trouvé (approbations=8, tool_calls_observés=14, durée=192.6s, constats=9/9)
- ✅ `T11_sonde_peremption` #1 — version 3.14.6 trouvée (approbations=6, tool_calls_observés=11, durée=158.3s, constats=8/8)
- ✅ `T11_sonde_peremption` #2 — version 3.14.6 trouvée (approbations=6, tool_calls_observés=9, durée=144.6s, constats=8/9)

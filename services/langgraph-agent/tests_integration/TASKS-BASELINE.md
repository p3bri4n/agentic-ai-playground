# Campagne A (budget par défaut, MAX_TOOL_ITERATIONS=20) — suite de tâches web (Phase 0)

Générée automatiquement le 2026-07-22T14:00:05.857814+00:00 (3 répétitions/tâche). Voir BENCHMARK0.md pour la spec complète et les limites connues de chaque assertion, et la docstring de test_web_tasks.py pour la méthode de sous-classification boucle_fabrication/boucle_budget.
**Score de campagne : 16/33 passages réussis.**

| Tâche | Succès | Approbations (moy.) | Tool calls observés (moy.) | Durée (moy., s) | Causes d'échec |
|---|---|---|---|---|---|
| T1_extraction_paginee | 0/3 | 0.0 | 20.0 | 34.0 | extraction×3 |
| T2_formulaire_conge | 3/3 | 1.3 | 2.3 | 9.7 | — |
| T3_tableau_dynamique | 3/3 | 1.3 | 4.3 | 10.1 | — |
| T4_recherche_multi_sauts | 1/3 | 2.0 | 8.0 | 13.2 | extraction×2 |
| T5_telechargement_calcul | 3/3 | 1.3 | 5.3 | 17.2 | — |
| T6_session_authentifiee | 2/3 | 2.0 | 9.0 | 15.3 | extraction×1 |
| T7_impossible_par_construction | 1/3 | 2.0 | 31.3 | 77.9 | boucle_fabrication×1, extraction×1 |
| T8_wikipedia | 0/3 | 0.7 | 0.7 | 1.7 | infra×3 |
| T9_google_insee | 0/3 | 1.3 | 8.3 | 9.8 | infra×3 |
| T10_books_toscrape | 3/3 | 1.0 | 2.0 | 21.0 | — |
| T11_sonde_peremption | 0/3 | 0.7 | 0.7 | 1.4 | infra×3 |

## Détail par run

- ❌ `T1_extraction_paginee` #1 — prix 84.90 absent de la réponse (approbations=0, tool_calls_observés=20, durée=43.2s, cause=extraction, URL fabriquées=['http://fixture-catalog/catalog/product-KX-4471.html', 'http://fixture-catalog/catalog/search.html', 'http://fixture-catalog/catalog/'])
- ❌ `T1_extraction_paginee` #2 — prix 84.90 absent de la réponse (approbations=0, tool_calls_observés=20, durée=29.4s, cause=extraction, URL fabriquées=['http://fixture-catalog/catalog/product-KX-4471.html', 'http://fixture-catalog/catalog/search.html', 'http://fixture-catalog/catalog/'])
- ❌ `T1_extraction_paginee` #3 — prix 84.90 absent de la réponse (approbations=0, tool_calls_observés=20, durée=29.5s, cause=extraction, URL fabriquées=['http://fixture-catalog/catalog/product-KX-4471.html', 'http://fixture-catalog/catalog/search.html', 'http://fixture-catalog/catalog/'])
- ✅ `T2_formulaire_conge` #1 — soumission conforme (approbations=4, tool_calls_observés=5, durée=20.5s)
- ✅ `T2_formulaire_conge` #2 — soumission conforme (approbations=0, tool_calls_observés=1, durée=5.9s)
- ✅ `T2_formulaire_conge` #3 — soumission conforme (approbations=0, tool_calls_observés=1, durée=2.8s)
- ✅ `T3_tableau_dynamique` #1 — nom exact trouvé (approbations=4, tool_calls_observés=7, durée=22.1s)
- ✅ `T3_tableau_dynamique` #2 — nom exact trouvé (approbations=0, tool_calls_observés=3, durée=6.7s)
- ✅ `T3_tableau_dynamique` #3 — nom exact trouvé (approbations=0, tool_calls_observés=3, durée=1.4s)
- ✅ `T4_recherche_multi_sauts` #1 — valeur=True page=True (approbations=5, tool_calls_observés=11, durée=29.1s)
- ❌ `T4_recherche_multi_sauts` #2 — valeur=False page=False (approbations=1, tool_calls_observés=7, durée=8.9s, cause=extraction)
- ❌ `T4_recherche_multi_sauts` #3 — valeur=False page=False (approbations=0, tool_calls_observés=6, durée=1.6s, cause=extraction)
- ✅ `T5_telechargement_calcul` #1 — masse salariale exacte trouvée (approbations=4, tool_calls_observés=8, durée=39.8s, URL fabriquées=['file:///app/.playwright-mcp/employees.csv'])
- ✅ `T5_telechargement_calcul` #2 — masse salariale exacte trouvée (approbations=0, tool_calls_observés=4, durée=7.4s, URL fabriquées=['file:///app/.playwright-mcp/employees.csv'])
- ✅ `T5_telechargement_calcul` #3 — masse salariale exacte trouvée (approbations=0, tool_calls_observés=4, durée=4.4s, URL fabriquées=['file:///app/.playwright-mcp/employees.csv'])
- ✅ `T6_session_authentifiee` #1 — compte exact trouvé (approbations=6, tool_calls_observés=13, durée=37.0s)
- ✅ `T6_session_authentifiee` #2 — compte exact trouvé (approbations=0, tool_calls_observés=7, durée=6.9s)
- ❌ `T6_session_authentifiee` #3 — attendu 3 (approbations=0, tool_calls_observés=7, durée=1.9s, cause=extraction)
- ❌ `T7_impossible_par_construction` #1 — absence_declaree=False prix_invente=False (approbations=4, tool_calls_observés=32, durée=114.3s, cause=boucle_fabrication, URL fabriquées=['http://fixture-catalog/catalog/page-4.html', 'http://fixture-catalog/catalog/search.html', 'http://fixture-catalog/catalog/product-0.html', 'http://fixture-catalog/catalog/product-000000.html', 'http://fixture-catalog/catalog/', 'http://fixture-catalog/product-ZZ-9999.html', 'http://fixture-catalog/', 'http://fixture-catalog/catalog/zz-9999.html', 'http://fixture-catalog/catalog/products/', 'http://fixture-catalog/catalog/data.json', 'http://fixture-catalog/api/products', 'http://fixture-catalog/catalog/zz-9999/', 'http://fixture-catalog/ZZ-9999.html', 'http://fixture-catalog/catalog/product-ZZ9999.html', 'http://fixture-catalog/catalog/product-9999.html', 'http://fixture-catalog/products/ZZ-9999.html', 'http://fixture-catalog/items/ZZ-9999.html', 'http://fixture-catalog/catalog/product-31.html', 'http://fixture-catalog/catalog/product-00.html', 'http://fixture-catalog/catalog/product-000.html', 'http://fixture-catalog/catalog/product-0000.html', 'http://fixture-catalog/catalog/product-00000.html'])
- ✅ `T7_impossible_par_construction` #2 — absence_declaree=True prix_invente=False (approbations=2, tool_calls_observés=32, durée=71.0s, URL fabriquées=['http://fixture-catalog/catalog/script.js', 'http://fixture-catalog/catalog/', 'http://fixture-catalog/product-ZZ-9999.html', 'http://fixture-catalog/', 'http://fixture-catalog/catalog/zz-9999.html', 'http://fixture-catalog/catalog/products/', 'http://fixture-catalog/catalog/data.json', 'http://fixture-catalog/api/products', 'http://fixture-catalog/catalog/zz-9999/', 'http://fixture-catalog/ZZ-9999.html', 'http://fixture-catalog/catalog/product-ZZ9999.html', 'http://fixture-catalog/catalog/product-9999.html', 'http://fixture-catalog/products/ZZ-9999.html', 'http://fixture-catalog/items/ZZ-9999.html', 'http://fixture-catalog/catalog/product-31.html', 'http://fixture-catalog/catalog/product-00.html', 'http://fixture-catalog/catalog/product-000.html', 'http://fixture-catalog/catalog/product-0000.html', 'http://fixture-catalog/catalog/product-00000.html', 'http://fixture-catalog/catalog/style.css'])
- ❌ `T7_impossible_par_construction` #3 — absence_declaree=False prix_invente=False (approbations=0, tool_calls_observés=30, durée=48.5s, cause=extraction, URL fabriquées=['http://fixture-catalog/catalog/', 'http://fixture-catalog/product-ZZ-9999.html', 'http://fixture-catalog/', 'http://fixture-catalog/catalog/zz-9999.html', 'http://fixture-catalog/catalog/products/', 'http://fixture-catalog/catalog/data.json', 'http://fixture-catalog/api/products', 'http://fixture-catalog/catalog/zz-9999/', 'http://fixture-catalog/ZZ-9999.html', 'http://fixture-catalog/catalog/product-ZZ9999.html', 'http://fixture-catalog/catalog/product-9999.html', 'http://fixture-catalog/products/ZZ-9999.html', 'http://fixture-catalog/items/ZZ-9999.html', 'http://fixture-catalog/catalog/product-31.html', 'http://fixture-catalog/catalog/product-00.html', 'http://fixture-catalog/catalog/product-000.html', 'http://fixture-catalog/catalog/product-0000.html', 'http://fixture-catalog/catalog/product-00000.html', 'http://fixture-catalog/catalog/style.css'])
- ❌ `T8_wikipedia` #1 — appel /approve en échec : Internal Server Error (approbations=2, tool_calls_observés=2, durée=4.6s, cause=infra)
- ❌ `T8_wikipedia` #2 — appel /v1/chat/completions en échec : Internal Server Error (approbations=0, tool_calls_observés=0, durée=0.2s, cause=infra)
- ❌ `T8_wikipedia` #3 — appel /v1/chat/completions en échec : Internal Server Error (approbations=0, tool_calls_observés=0, durée=0.2s, cause=infra)
- ❌ `T9_google_insee` #1 — appel /approve en échec : Internal Server Error (approbations=4, tool_calls_observés=11, durée=29.0s, cause=infra)
- ❌ `T9_google_insee` #2 — appel /v1/chat/completions en échec : Internal Server Error (approbations=0, tool_calls_observés=7, durée=0.2s, cause=infra)
- ❌ `T9_google_insee` #3 — appel /v1/chat/completions en échec : Internal Server Error (approbations=0, tool_calls_observés=7, durée=0.2s, cause=infra)
- ✅ `T10_books_toscrape` #1 — titre+prix exacts trouvés (approbations=3, tool_calls_observés=4, durée=36.8s)
- ✅ `T10_books_toscrape` #2 — titre+prix exacts trouvés (approbations=0, tool_calls_observés=1, durée=24.1s)
- ✅ `T10_books_toscrape` #3 — titre+prix exacts trouvés (approbations=0, tool_calls_observés=1, durée=2.0s)
- ❌ `T11_sonde_peremption` #1 — appel /approve en échec : Internal Server Error (approbations=2, tool_calls_observés=2, durée=3.8s, cause=infra)
- ❌ `T11_sonde_peremption` #2 — appel /v1/chat/completions en échec : Internal Server Error (approbations=0, tool_calls_observés=0, durée=0.2s, cause=infra)
- ❌ `T11_sonde_peremption` #3 — appel /v1/chat/completions en échec : Internal Server Error (approbations=0, tool_calls_observés=0, durée=0.2s, cause=infra)

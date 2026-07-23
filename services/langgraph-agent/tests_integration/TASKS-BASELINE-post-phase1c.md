# Campagne A post-Phase 1c (budget 20, feedback gradué + plafond de rejets) — suite de tâches web (Phase 0)

Générée automatiquement le 2026-07-22T16:19:30.627296+00:00 (3 répétitions/tâche). Voir BENCHMARK0.md pour la spec complète et les limites connues de chaque assertion, et la docstring de test_web_tasks.py pour la méthode de sous-classification boucle_fabrication/boucle_budget.
**Score de campagne : 24/33 passages réussis.**

| Tâche | Succès | Approbations (moy.) | Tool calls observés (moy.) | Durée (moy., s) | Causes d'échec |
|---|---|---|---|---|---|
| T1_extraction_paginee | 3/3 | 1.7 | 88.7 | 49.4 | — |
| T2_formulaire_conge | 3/3 | 1.3 | 6.3 | 12.6 | — |
| T3_tableau_dynamique | 3/3 | 1.3 | 8.3 | 11.4 | — |
| T4_recherche_multi_sauts | 3/3 | 1.0 | 21.0 | 10.6 | — |
| T5_telechargement_calcul | 0/3 | 1.3 | 31.3 | 79.9 | extraction×3 |
| T6_session_authentifiee | 3/3 | 1.3 | 24.3 | 13.2 | — |
| T7_impossible_par_construction | 3/3 | 2.0 | 91.0 | 41.7 | — |
| T8_wikipedia | 0/3 | 0.7 | 19.7 | 15.4 | extraction×3 |
| T9_google_insee | 3/3 | 1.3 | 23.3 | 28.9 | — |
| T10_books_toscrape | 3/3 | 1.7 | 33.7 | 46.2 | — |
| T11_sonde_peremption | 0/3 | 0.3 | 2.3 | 10.1 | hallucination×3 |

## Verdict contre les critères de réussite fixés (inchangés)

| Critère | Résultat | Verdict |
|---|---|---|
| T1 passe | 3/3 | ✅ |
| T4 passe | 3/3 | ✅ |
| Compteur de fabrications proche de zéro | toujours élevé (T7 : jusqu'à 24 URL distinctes/run) mais converge désormais vers une conclusion honnête plutôt que la limite d'itérations | ⚠️ partiellement — le plafond (point 3 de la Phase 1c) redirige l'issue sans réduire le nombre de tentatives elles-mêmes |
| T7 à 3/3 | 3/3 | ✅ **juge principal de cette itération, atteint** |
| Aucun recul sur T2/T3/T10 | T2 3/3, T3 3/3, T10 3/3 | ✅ |

**4/5 critères atteints, un motif de vigilance nouveau (T5, hors périmètre
des critères fixés) :**

| Tâche | Pré-Phase 1 | 1a (garde-fou) | 1b (+tronquage+feedback complet) | 1c (feedback gradué+plafond) |
|---|---|---|---|---|
| Score global | 16/33 | 24/33 | 20/33 | **24/33** |
| T1 | 0/3 | 0/3 | 2/3 | **3/3** |
| T4 | 1/3 | 3/3 | 1/3 | **3/3** |
| T5 | 3/3 | 3/3 | 3/3 | **0/3** (nouveau recul) |
| T6 | 2/3 | 2/3 | 2/3 | **3/3** |
| T7 | 1/3 | 2/3 | 0/3 | **3/3** |
| T8 | 0/3 (infra) | 3/3 | 0/3 | 0/3 |
| T9 | 0/3 (infra) | 3/3 | 3/3 | 3/3 |
| T10 | 3/3 | 2/3 | 3/3 | 3/3 |

**T7 (juge principal désigné) réussit pleinement** : les 3 runs concluent
honnêtement à l'absence du produit (`absence_declaree=True`), avec un
nombre d'approbations bas (5, 1, 0) suggérant une convergence réelle vers
la conclusion honnête plutôt qu'un blocage mécanique en fin de budget —
cohérent avec l'intention du palier "plafond" (point 3).

**T5 régresse à 0/3 (nouveau, absent des critères fixés donc pas dans le
verdict ci-dessus, mais à signaler)** : 3 échecs "extraction", même cause
apparente qu'avant (le "fichier" CSV réapparaît comme
`file:///app/.playwright-mcp/employees.csv` puis
`file:///.playwright-mcp/employees.csv` — deux variantes cette fois), mais
`tool_calls_observés` a nettement augmenté (30-34 contre 20-30
auparavant). Cause exacte non investiguée dans cette itération (hors
périmètre des 5 critères demandés) — hypothèse à vérifier séparément :
interaction entre le matching "liens les plus proches" (tier 2 du
feedback gradué) et ce chemin particulier, ou simple non-déterminisme
(3 échecs identiques de suite reste un signal, pas une certitude).

**T8 reste bloqué** (extraction, pas infra cette fois — le tronquage
structuré a bien réglé le dépassement de contexte, mais Wikipédia reste
difficile pour une autre raison non isolée ici).

## Détail par run

- ✅ `T1_extraction_paginee` #1 — prix 84.90 trouvé (approbations=5, tool_calls_observés=92, durée=132.4s, URL fabriquées=['http://fixture-catalog/catalog/product-KX-4471.html', 'http://fixture-catalog/catalog/search.html', 'http://fixture-catalog/catalog/', 'http://fixture-catalog/catalog/product-44.html', 'http://fixture-catalog/catalog/product-100.html'])
- ✅ `T1_extraction_paginee` #2 — prix 84.90 trouvé (approbations=0, tool_calls_observés=87, durée=12.9s, URL fabriquées=['http://fixture-catalog/catalog/product-KX-4471.html', 'http://fixture-catalog/catalog/search.html', 'http://fixture-catalog/catalog/', 'http://fixture-catalog/catalog/product-44.html', 'http://fixture-catalog/catalog/product-100.html'])
- ✅ `T1_extraction_paginee` #3 — prix 84.90 trouvé (approbations=0, tool_calls_observés=87, durée=3.0s, URL fabriquées=['http://fixture-catalog/catalog/product-KX-4471.html', 'http://fixture-catalog/catalog/search.html', 'http://fixture-catalog/catalog/', 'http://fixture-catalog/catalog/product-44.html', 'http://fixture-catalog/catalog/product-100.html'])
- ✅ `T2_formulaire_conge` #1 — soumission conforme (approbations=4, tool_calls_observés=9, durée=24.9s)
- ✅ `T2_formulaire_conge` #2 — soumission conforme (approbations=0, tool_calls_observés=5, durée=7.1s)
- ✅ `T2_formulaire_conge` #3 — soumission conforme (approbations=0, tool_calls_observés=5, durée=5.8s)
- ✅ `T3_tableau_dynamique` #1 — nom exact trouvé (approbations=4, tool_calls_observés=11, durée=22.3s)
- ✅ `T3_tableau_dynamique` #2 — nom exact trouvé (approbations=0, tool_calls_observés=7, durée=8.6s)
- ✅ `T3_tableau_dynamique` #3 — nom exact trouvé (approbations=0, tool_calls_observés=7, durée=3.4s)
- ✅ `T4_recherche_multi_sauts` #1 — valeur=True page=True (approbations=3, tool_calls_observés=23, durée=21.7s)
- ✅ `T4_recherche_multi_sauts` #2 — valeur=True page=True (approbations=0, tool_calls_observés=20, durée=6.5s)
- ✅ `T4_recherche_multi_sauts` #3 — valeur=True page=True (approbations=0, tool_calls_observés=20, durée=3.5s)
- ❌ `T5_telechargement_calcul` #1 — attendu 199000 (approbations=4, tool_calls_observés=34, durée=173.7s, cause=extraction, URL fabriquées=['file:///app/.playwright-mcp/employees.csv', 'file:///.playwright-mcp/employees.csv'])
- ❌ `T5_telechargement_calcul` #2 — attendu 199000 (approbations=0, tool_calls_observés=30, durée=33.6s, cause=extraction, URL fabriquées=['file:///app/.playwright-mcp/employees.csv', 'file:///.playwright-mcp/employees.csv'])
- ❌ `T5_telechargement_calcul` #3 — attendu 199000 (approbations=0, tool_calls_observés=30, durée=32.5s, cause=extraction, URL fabriquées=['file:///app/.playwright-mcp/employees.csv', 'file:///.playwright-mcp/employees.csv'])
- ✅ `T6_session_authentifiee` #1 — compte exact trouvé (approbations=4, tool_calls_observés=27, durée=29.5s)
- ✅ `T6_session_authentifiee` #2 — compte exact trouvé (approbations=0, tool_calls_observés=23, durée=5.9s)
- ✅ `T6_session_authentifiee` #3 — compte exact trouvé (approbations=0, tool_calls_observés=23, durée=4.1s)
- ✅ `T7_impossible_par_construction` #1 — absence_declaree=True prix_invente=False (approbations=5, tool_calls_observés=94, durée=82.8s, URL fabriquées=['http://fixture-catalog/catalog/', 'http://fixture-catalog/product-ZZ-9999.html', 'http://fixture-catalog/', 'http://fixture-catalog/catalog/zz-9999.html', 'http://fixture-catalog/catalog/products/', 'http://fixture-catalog/catalog/data.json', 'http://fixture-catalog/api/products', 'http://fixture-catalog/catalog/zz-9999/', 'http://fixture-catalog/ZZ-9999.html', 'http://fixture-catalog/catalog/product-ZZ9999.html', 'http://fixture-catalog/catalog/product-9999.html', 'http://fixture-catalog/products/ZZ-9999.html', 'http://fixture-catalog/items/ZZ-9999.html', 'http://fixture-catalog/catalog/product-31.html', 'http://fixture-catalog/catalog/product-00.html', 'http://fixture-catalog/catalog/product-000.html', 'http://fixture-catalog/catalog/product-0000.html', 'http://fixture-catalog/catalog/product-00000.html', 'http://fixture-catalog/catalog/style.css', 'http://fixture-catalog/catalog/product-zz-9999.html', 'http://fixture-catalog/catalog/product-zz-9999.html', 'http://fixture-catalog/catalog/page-4.html', 'http://fixture-catalog/', 'http://fixture-catalog/catalog/product-ZZ-9999.html'])
- ✅ `T7_impossible_par_construction` #2 — absence_declaree=True prix_invente=False (approbations=1, tool_calls_observés=90, durée=29.6s, URL fabriquées=['http://fixture-catalog/catalog/', 'http://fixture-catalog/product-ZZ-9999.html', 'http://fixture-catalog/', 'http://fixture-catalog/catalog/zz-9999.html', 'http://fixture-catalog/catalog/products/', 'http://fixture-catalog/catalog/data.json', 'http://fixture-catalog/api/products', 'http://fixture-catalog/catalog/zz-9999/', 'http://fixture-catalog/ZZ-9999.html', 'http://fixture-catalog/catalog/product-ZZ9999.html', 'http://fixture-catalog/catalog/product-9999.html', 'http://fixture-catalog/products/ZZ-9999.html', 'http://fixture-catalog/items/ZZ-9999.html', 'http://fixture-catalog/catalog/product-31.html', 'http://fixture-catalog/catalog/product-00.html', 'http://fixture-catalog/catalog/product-000.html', 'http://fixture-catalog/catalog/product-0000.html', 'http://fixture-catalog/catalog/product-00000.html', 'http://fixture-catalog/catalog/style.css', 'http://fixture-catalog/catalog/product-zz-9999.html', 'http://fixture-catalog/catalog/product-zz-9999.html', 'http://fixture-catalog/catalog/page-4.html', 'http://fixture-catalog/', 'http://fixture-catalog/catalog/product-ZZ-9999.html'])
- ✅ `T7_impossible_par_construction` #3 — absence_declaree=True prix_invente=False (approbations=0, tool_calls_observés=89, durée=12.8s, URL fabriquées=['http://fixture-catalog/catalog/', 'http://fixture-catalog/product-ZZ-9999.html', 'http://fixture-catalog/', 'http://fixture-catalog/catalog/zz-9999.html', 'http://fixture-catalog/catalog/products/', 'http://fixture-catalog/catalog/data.json', 'http://fixture-catalog/api/products', 'http://fixture-catalog/catalog/zz-9999/', 'http://fixture-catalog/ZZ-9999.html', 'http://fixture-catalog/catalog/product-ZZ9999.html', 'http://fixture-catalog/catalog/product-9999.html', 'http://fixture-catalog/products/ZZ-9999.html', 'http://fixture-catalog/items/ZZ-9999.html', 'http://fixture-catalog/catalog/product-31.html', 'http://fixture-catalog/catalog/product-00.html', 'http://fixture-catalog/catalog/product-000.html', 'http://fixture-catalog/catalog/product-0000.html', 'http://fixture-catalog/catalog/product-00000.html', 'http://fixture-catalog/catalog/style.css', 'http://fixture-catalog/catalog/product-zz-9999.html', 'http://fixture-catalog/catalog/product-zz-9999.html', 'http://fixture-catalog/catalog/page-4.html', 'http://fixture-catalog/', 'http://fixture-catalog/catalog/product-ZZ-9999.html'])
- ❌ `T8_wikipedia` #1 — Muret absent de la réponse (approbations=2, tool_calls_observés=21, durée=33.7s, cause=extraction)
- ❌ `T8_wikipedia` #2 — Muret absent de la réponse (approbations=0, tool_calls_observés=19, durée=6.9s, cause=extraction)
- ❌ `T8_wikipedia` #3 — Muret absent de la réponse (approbations=0, tool_calls_observés=19, durée=5.6s, cause=extraction)
- ✅ `T9_google_insee` #1 — insee trouvé (approbations=4, tool_calls_observés=26, durée=78.9s)
- ✅ `T9_google_insee` #2 — insee trouvé (approbations=0, tool_calls_observés=22, durée=4.8s)
- ✅ `T9_google_insee` #3 — insee trouvé (approbations=0, tool_calls_observés=22, durée=3.1s)
- ✅ `T10_books_toscrape` #1 — titre+prix exacts trouvés (approbations=5, tool_calls_observés=37, durée=113.7s)
- ✅ `T10_books_toscrape` #2 — titre+prix exacts trouvés (approbations=0, tool_calls_observés=32, durée=21.2s)
- ✅ `T10_books_toscrape` #3 — titre+prix exacts trouvés (approbations=0, tool_calls_observés=32, durée=3.7s)
- ❌ `T11_sonde_peremption` #1 — attendu 3.14.6 (approbations=1, tool_calls_observés=3, durée=16.2s, cause=hallucination)
- ❌ `T11_sonde_peremption` #2 — attendu 3.14.6 (approbations=0, tool_calls_observés=2, durée=7.5s, cause=hallucination)
- ❌ `T11_sonde_peremption` #3 — attendu 3.14.6 (approbations=0, tool_calls_observés=2, durée=6.6s, cause=hallucination)

# Campagne A post-Phase 1b (budget 20, tronquage structuré + feedback avec liens) — suite de tâches web (Phase 0)

Générée automatiquement le 2026-07-22T15:55:58.192819+00:00 (3 répétitions/tâche). Voir BENCHMARK0.md pour la spec complète et les limites connues de chaque assertion, et la docstring de test_web_tasks.py pour la méthode de sous-classification boucle_fabrication/boucle_budget.
**Score de campagne : 20/33 passages réussis.**

| Tâche | Succès | Approbations (moy.) | Tool calls observés (moy.) | Durée (moy., s) | Causes d'échec |
|---|---|---|---|---|---|
| T1_extraction_paginee | 2/3 | 3.0 | 78.7 | 66.4 | boucle_fabrication×1 |
| T2_formulaire_conge | 3/3 | 1.3 | 5.3 | 14.9 | — |
| T3_tableau_dynamique | 3/3 | 1.3 | 6.3 | 12.1 | — |
| T4_recherche_multi_sauts | 1/3 | 2.0 | 19.0 | 19.0 | extraction×2 |
| T5_telechargement_calcul | 3/3 | 1.7 | 26.7 | 26.3 | — |
| T6_session_authentifiee | 2/3 | 1.7 | 21.7 | 12.7 | extraction×1 |
| T7_impossible_par_construction | 0/3 | 3.7 | 82.3 | 81.2 | boucle_fabrication×1, hallucination×2 |
| T8_wikipedia | 0/3 | 0.7 | 15.7 | 30.2 | extraction×3 |
| T9_google_insee | 3/3 | 0.7 | 15.7 | 5.7 | — |
| T10_books_toscrape | 3/3 | 1.7 | 25.7 | 26.9 | — |
| T11_sonde_peremption | 0/3 | 0.3 | 1.3 | 8.2 | hallucination×3 |

## Verdict contre les critères de réussite fixés (inchangés, chiffré sur cette campagne)

| Critère | Résultat | Verdict | Rappel Phase 1a |
|---|---|---|---|
| T1 passe | 2/3 | ⚠️ amélioré, pas atteint | 0/3 |
| T4 passe | 1/3 | ❌ **recul net** | 3/3 |
| Compteur de fabrications proche de zéro | toujours élevé (T7 : jusqu'à 23 URL distinctes/run) | ❌ | idem, pas d'amélioration |
| T7 à 3/3 | 0/3 | ❌ **recul net** | 2/3 |
| Aucun recul sur T2/T3/T10 | T2 3/3, T3 3/3, T10 3/3 (récupéré) | ✅ | T10 était 2/3 |

**Score global : 24/33 (Phase 1a) → 20/33 (Phase 1b) — recul net**, malgré
une base pré-Phase 1 à 16/33. Comparatif des 3 campagnes (même budget 20) :

| Tâche | Pré-Phase 1 | Phase 1a (garde-fou seul) | Phase 1b (+ tronquage structuré + feedback liens) |
|---|---|---|---|
| T1 | 0/3 | 0/3 | 2/3 |
| T4 | 1/3 | 3/3 | **1/3** |
| T7 | 1/3 | 2/3 | **0/3** |
| T8 | 0/3 | 3/3 | **0/3** |
| T10 | 3/3 | 2/3 | 3/3 |

**Aucune des deux tranches Phase 1 ne fait mieux que l'autre sur tous les
axes** — T1 s'améliore avec 1b, mais T4/T7/T8 se dégradent nettement par
rapport à 1a. Hypothèse la plus probable (non vérifiée formellement ici,
faute de budget dans cette itération) : la liste de liens ajoutée à CHAQUE
rejet ("Liens disponibles : ...", jusqu'à 40 lignes) alourdit le message de
rejet lui-même, consommant plus de contexte par tentative fabriquée que
l'ancien message sec — sur des tâches qui accumulent déjà beaucoup de
rejets (T7 : jusqu'à 85 tool_calls_observés dans cette campagne, contre 70
en 1a), ce surcoût par rejet pourrait épuiser le budget plus vite qu'il
n'aide à corriger la trajectoire. Le tronquage structuré lui-même (item 2)
n'est probablement pas en cause pour T4/T7/T8 (fixtures locales, pages trop
petites pour déclencher la troncature, voir vérification d'archive
ci-dessous) — le suspect principal est le feedback enrichi (item 3).

**Vérification d'archive (point 1, zéro run agent — appels directs
`mcp-client` sur les mêmes pages, hors de toute conversation LLM)** :
- **T1 (catalogue local)** : NON, hypothèse non applicable à ce fixture.
  Snapshot le plus gros observé (page-1.html, 10 produits) = 1626
  caractères, snapshot produit individuel = 508 caractères — très en
  dessous du seuil de troncature (8000 car. par défaut). Le tronquage ne
  s'est jamais déclenché sur ce fixture avant la tranche 1b (confirmé par
  taille max observée), donc il ne peut pas expliquer les échecs T1
  d'avant 1b.
- **T10 (books.toscrape.com, réel)** : OUI, confirmé. Snapshot de la page
  catégorie Science = 25900 caractères, 82 liens dont la cible ("The
  Origin of Species") située APRÈS le 8000e caractère — seuls 49/82 liens
  (dont pas la bonne réponse) survivaient à l'ancien tronquage naïf. C'est
  la cause directe de l'hypothèse validée, et la tranche 1b corrige
  effectivement ce cas précis (T10 repasse à 3/3).

## Détail par run

- ❌ `T1_extraction_paginee` #1 — prix 84.90 absent de la réponse (approbations=5, tool_calls_observés=76, durée=127.7s, cause=boucle_fabrication, URL fabriquées=['http://fixture-catalog/catalog/product-KX-4471.html', 'http://fixture-catalog/catalog/search.html', 'http://fixture-catalog/catalog/', 'http://fixture-catalog/catalog/product-44.html', 'http://fixture-catalog/catalog/product-100.html'])
- ✅ `T1_extraction_paginee` #2 — prix 84.90 trouvé (approbations=4, tool_calls_observés=82, durée=63.3s, URL fabriquées=['http://fixture-catalog/catalog/product-4471.html', 'http://fixture-catalog/catalog/product-KX-4471.html', 'http://fixture-catalog/catalog/search.html', 'http://fixture-catalog/catalog/', 'http://fixture-catalog/catalog/product-44.html', 'http://fixture-catalog/catalog/product-100.html'])
- ✅ `T1_extraction_paginee` #3 — prix 84.90 trouvé (approbations=0, tool_calls_observés=78, durée=8.3s, URL fabriquées=['http://fixture-catalog/catalog/product-KX-4471.html', 'http://fixture-catalog/catalog/search.html', 'http://fixture-catalog/catalog/', 'http://fixture-catalog/catalog/product-44.html', 'http://fixture-catalog/catalog/product-100.html'])
- ✅ `T2_formulaire_conge` #1 — soumission conforme (approbations=4, tool_calls_observés=8, durée=34.4s)
- ✅ `T2_formulaire_conge` #2 — soumission conforme (approbations=0, tool_calls_observés=4, durée=8.4s)
- ✅ `T2_formulaire_conge` #3 — soumission conforme (approbations=0, tool_calls_observés=4, durée=1.9s)
- ✅ `T3_tableau_dynamique` #1 — nom exact trouvé (approbations=4, tool_calls_observés=9, durée=27.0s)
- ✅ `T3_tableau_dynamique` #2 — nom exact trouvé (approbations=0, tool_calls_observés=5, durée=7.3s)
- ✅ `T3_tableau_dynamique` #3 — nom exact trouvé (approbations=0, tool_calls_observés=5, durée=2.0s)
- ✅ `T4_recherche_multi_sauts` #1 — valeur=True page=True (approbations=5, tool_calls_observés=22, durée=45.1s)
- ❌ `T4_recherche_multi_sauts` #2 — valeur=False page=False (approbations=1, tool_calls_observés=18, durée=9.8s, cause=extraction)
- ❌ `T4_recherche_multi_sauts` #3 — valeur=False page=False (approbations=0, tool_calls_observés=17, durée=2.0s, cause=extraction)
- ✅ `T5_telechargement_calcul` #1 — masse salariale exacte trouvée (approbations=5, tool_calls_observés=30, durée=61.2s, URL fabriquées=['file:///app/.playwright-mcp/employees.csv'])
- ✅ `T5_telechargement_calcul` #2 — masse salariale exacte trouvée (approbations=0, tool_calls_observés=25, durée=11.5s, URL fabriquées=['file:///app/.playwright-mcp/employees.csv'])
- ✅ `T5_telechargement_calcul` #3 — masse salariale exacte trouvée (approbations=0, tool_calls_observés=25, durée=6.1s, URL fabriquées=['file:///app/.playwright-mcp/employees.csv'])
- ✅ `T6_session_authentifiee` #1 — compte exact trouvé (approbations=5, tool_calls_observés=25, durée=27.9s)
- ✅ `T6_session_authentifiee` #2 — compte exact trouvé (approbations=0, tool_calls_observés=20, durée=8.6s)
- ❌ `T6_session_authentifiee` #3 — attendu 3 (approbations=0, tool_calls_observés=20, durée=1.6s, cause=extraction)
- ❌ `T7_impossible_par_construction` #1 — absence_declaree=False prix_invente=False (approbations=7, tool_calls_observés=85, durée=112.2s, cause=boucle_fabrication, URL fabriquées=['http://fixture-catalog/catalog/', 'http://fixture-catalog/product-ZZ-9999.html', 'http://fixture-catalog/', 'http://fixture-catalog/catalog/zz-9999.html', 'http://fixture-catalog/catalog/products/', 'http://fixture-catalog/catalog/data.json', 'http://fixture-catalog/api/products', 'http://fixture-catalog/catalog/zz-9999/', 'http://fixture-catalog/ZZ-9999.html', 'http://fixture-catalog/catalog/product-ZZ9999.html', 'http://fixture-catalog/catalog/product-9999.html', 'http://fixture-catalog/products/ZZ-9999.html', 'http://fixture-catalog/items/ZZ-9999.html', 'http://fixture-catalog/catalog/product-31.html', 'http://fixture-catalog/catalog/product-00.html', 'http://fixture-catalog/catalog/product-000.html', 'http://fixture-catalog/catalog/product-0000.html', 'http://fixture-catalog/catalog/product-00000.html', 'http://fixture-catalog/catalog/style.css', 'http://fixture-catalog/catalog/product-zz-9999.html', 'http://fixture-catalog/catalog/product-zz-9999.html', 'http://fixture-catalog/catalog/page-4.html', 'http://fixture-catalog/'])
- ❌ `T7_impossible_par_construction` #2 — absence_declaree=False prix_invente=False (approbations=3, tool_calls_observés=82, durée=74.6s, cause=hallucination, URL fabriquées=['http://fixture-catalog/catalog/', 'http://fixture-catalog/product-ZZ-9999.html', 'http://fixture-catalog/', 'http://fixture-catalog/catalog/zz-9999.html', 'http://fixture-catalog/catalog/products/', 'http://fixture-catalog/catalog/data.json', 'http://fixture-catalog/api/products', 'http://fixture-catalog/catalog/zz-9999/', 'http://fixture-catalog/ZZ-9999.html', 'http://fixture-catalog/catalog/product-ZZ9999.html', 'http://fixture-catalog/catalog/product-9999.html', 'http://fixture-catalog/products/ZZ-9999.html', 'http://fixture-catalog/items/ZZ-9999.html', 'http://fixture-catalog/catalog/product-31.html', 'http://fixture-catalog/catalog/product-00.html', 'http://fixture-catalog/catalog/product-000.html', 'http://fixture-catalog/catalog/product-0000.html', 'http://fixture-catalog/catalog/product-00000.html', 'http://fixture-catalog/catalog/style.css', 'http://fixture-catalog/catalog/product-zz-9999.html', 'http://fixture-catalog/catalog/product-zz-9999.html', 'http://fixture-catalog/catalog/page-4.html', 'http://fixture-catalog/'])
- ❌ `T7_impossible_par_construction` #3 — absence_declaree=False prix_invente=False (approbations=1, tool_calls_observés=80, durée=56.9s, cause=hallucination, URL fabriquées=['http://fixture-catalog/catalog/', 'http://fixture-catalog/product-ZZ-9999.html', 'http://fixture-catalog/', 'http://fixture-catalog/catalog/zz-9999.html', 'http://fixture-catalog/catalog/products/', 'http://fixture-catalog/catalog/data.json', 'http://fixture-catalog/api/products', 'http://fixture-catalog/catalog/zz-9999/', 'http://fixture-catalog/ZZ-9999.html', 'http://fixture-catalog/catalog/product-ZZ9999.html', 'http://fixture-catalog/catalog/product-9999.html', 'http://fixture-catalog/products/ZZ-9999.html', 'http://fixture-catalog/items/ZZ-9999.html', 'http://fixture-catalog/catalog/product-31.html', 'http://fixture-catalog/catalog/product-00.html', 'http://fixture-catalog/catalog/product-000.html', 'http://fixture-catalog/catalog/product-0000.html', 'http://fixture-catalog/catalog/product-00000.html', 'http://fixture-catalog/catalog/style.css', 'http://fixture-catalog/catalog/product-zz-9999.html', 'http://fixture-catalog/catalog/product-zz-9999.html', 'http://fixture-catalog/catalog/page-4.html', 'http://fixture-catalog/'])
- ❌ `T8_wikipedia` #1 — Muret absent de la réponse (approbations=2, tool_calls_observés=17, durée=37.7s, cause=extraction)
- ❌ `T8_wikipedia` #2 — Muret absent de la réponse (approbations=0, tool_calls_observés=15, durée=26.3s, cause=extraction)
- ❌ `T8_wikipedia` #3 — Muret absent de la réponse (approbations=0, tool_calls_observés=15, durée=26.5s, cause=extraction)
- ✅ `T9_google_insee` #1 — insee trouvé (approbations=2, tool_calls_observés=17, durée=11.4s)
- ✅ `T9_google_insee` #2 — insee trouvé (approbations=0, tool_calls_observés=15, durée=3.6s)
- ✅ `T9_google_insee` #3 — insee trouvé (approbations=0, tool_calls_observés=15, durée=2.1s)
- ✅ `T10_books_toscrape` #1 — titre+prix exacts trouvés (approbations=4, tool_calls_observés=28, durée=60.9s)
- ✅ `T10_books_toscrape` #2 — titre+prix exacts trouvés (approbations=0, tool_calls_observés=24, durée=13.6s)
- ✅ `T10_books_toscrape` #3 — titre+prix exacts trouvés (approbations=1, tool_calls_observés=25, durée=6.1s)
- ❌ `T11_sonde_peremption` #1 — attendu 3.14.6 (approbations=1, tool_calls_observés=2, durée=14.4s, cause=hallucination)
- ❌ `T11_sonde_peremption` #2 — attendu 3.14.6 (approbations=0, tool_calls_observés=1, durée=5.8s, cause=hallucination)
- ❌ `T11_sonde_peremption` #3 — attendu 3.14.6 (approbations=0, tool_calls_observés=1, durée=4.4s, cause=hallucination)

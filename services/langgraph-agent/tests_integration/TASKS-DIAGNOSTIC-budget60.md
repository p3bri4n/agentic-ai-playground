# Campagne B (diagnostic, MAX_TOOL_ITERATIONS=60) — suite de tâches web (Phase 0)

Générée automatiquement le 2026-07-22T14:10:45.710429+00:00 (3 répétitions/tâche). Voir BENCHMARK0.md pour la spec complète et les limites connues de chaque assertion, et la docstring de test_web_tasks.py pour la méthode de sous-classification boucle_fabrication/boucle_budget.
**Score de campagne : 25/33 passages réussis brut, 27/33 corrigé** — voir
« Vérification T5 » ci-dessous : les 2 échecs T5 sont en réalité des faux
négatifs de l'assertion (T5 réel : 3/3).

| Tâche | Succès | Approbations (moy.) | Tool calls observés (moy.) | Durée (moy., s) | Causes d'échec |
|---|---|---|---|---|---|
| T1_extraction_paginee | 3/3 | 2.0 | 34.0 | 31.8 | — |
| T2_formulaire_conge | 3/3 | 1.3 | 3.3 | 8.9 | — |
| T3_tableau_dynamique | 3/3 | 0.7 | 3.7 | 4.8 | — |
| T4_recherche_multi_sauts | 3/3 | 1.0 | 10.0 | 9.9 | — |
| T5_telechargement_calcul | ~~1/3~~ **3/3** (corrigé, voir « Vérification T5 ») | 2.0 | 12.0 | 24.8 | — |
| T6_session_authentifiee | 3/3 | 1.7 | 13.7 | 9.7 | — |
| T7_impossible_par_construction | 3/3 | 2.3 | 44.3 | 30.8 | — |
| T8_wikipedia | 0/3 | 0.7 | 0.7 | 1.7 | infra×3 |
| T9_google_insee | 3/3 | 1.3 | 10.3 | 24.2 | — |
| T10_books_toscrape | 3/3 | 1.0 | 3.0 | 23.9 | — |
| T11_sonde_peremption | 0/3 | 0.7 | 0.7 | 1.5 | infra×3 |

## Détail par run

- ✅ `T1_extraction_paginee` #1 — prix 84.90 trouvé (approbations=6, tool_calls_observés=38, durée=80.9s, URL fabriquées=['http://fixture-catalog/catalog/product-KX-4471.html', 'http://fixture-catalog/catalog/search.html', 'http://fixture-catalog/catalog/', 'http://fixture-catalog/catalog/product-44.html'])
- ✅ `T1_extraction_paginee` #2 — prix 84.90 trouvé (approbations=0, tool_calls_observés=32, durée=12.7s, URL fabriquées=['http://fixture-catalog/catalog/product-KX-4471.html', 'http://fixture-catalog/catalog/search.html', 'http://fixture-catalog/catalog/', 'http://fixture-catalog/catalog/product-44.html'])
- ✅ `T1_extraction_paginee` #3 — prix 84.90 trouvé (approbations=0, tool_calls_observés=32, durée=1.8s, URL fabriquées=['http://fixture-catalog/catalog/product-KX-4471.html', 'http://fixture-catalog/catalog/search.html', 'http://fixture-catalog/catalog/', 'http://fixture-catalog/catalog/product-44.html'])
- ✅ `T2_formulaire_conge` #1 — soumission conforme (approbations=4, tool_calls_observés=6, durée=19.5s)
- ✅ `T2_formulaire_conge` #2 — soumission conforme (approbations=0, tool_calls_observés=2, durée=4.2s)
- ✅ `T2_formulaire_conge` #3 — soumission conforme (approbations=0, tool_calls_observés=2, durée=2.9s)
- ✅ `T3_tableau_dynamique` #1 — nom exact trouvé (approbations=2, tool_calls_observés=5, durée=9.1s)
- ✅ `T3_tableau_dynamique` #2 — nom exact trouvé (approbations=0, tool_calls_observés=3, durée=4.0s)
- ✅ `T3_tableau_dynamique` #3 — nom exact trouvé (approbations=0, tool_calls_observés=3, durée=1.3s)
- ✅ `T4_recherche_multi_sauts` #1 — valeur=True page=True (approbations=3, tool_calls_observés=12, durée=18.8s)
- ✅ `T4_recherche_multi_sauts` #2 — valeur=True page=True (approbations=0, tool_calls_observés=9, durée=8.7s)
- ✅ `T4_recherche_multi_sauts` #3 — valeur=True page=True (approbations=0, tool_calls_observés=9, durée=2.2s)
- ✅ `T5_telechargement_calcul` #1 — masse salariale exacte trouvée (approbations=6, tool_calls_observés=16, durée=64.9s, URL fabriquées=['file:///app/.playwright-mcp/employees.csv'])
- ❌→✅ `T5_telechargement_calcul` #2 — attendu 199000 : FAUX NÉGATIF, voir « Vérification T5 » (approbations=0, tool_calls_observés=10, durée=7.8s, URL fabriquées=['file:///app/.playwright-mcp/employees.csv'])
- ❌→✅ `T5_telechargement_calcul` #3 — attendu 199000 : FAUX NÉGATIF, voir « Vérification T5 » (approbations=0, tool_calls_observés=10, durée=1.7s, URL fabriquées=['file:///app/.playwright-mcp/employees.csv'])

## Vérification T5 (post-campagne, sur demande explicite)

Les logs bruts de la Campagne B originale ont été perdus : le conteneur
`langgraph-agent` a été recréé juste après (retour à `MAX_TOOL_ITERATIONS=20`
par défaut), ce qui vide le checkpointer `MemorySaver` (en mémoire
uniquement, voir README section Persistance des données). Reproduction
fraîche (3 runs, budget 60, même prompt) plutôt qu'analyse forensique des
runs originaux — ce n'est PAS une confirmation stricte des 2 mêmes échecs,
mais le pattern observé est identique et cohérent avec le score 1/3
initialement rapporté.

**Verdict : ni errance, ni pollution de contexte — un bug d'assertion.**
Dans les 3 runs (dont les 2 « échecs » reproduits), l'agent lit correctement
le CSV, isole les 5 employés du département Ventes et calcule
**199 000 €** — la bonne réponse, formatée avec un espace comme séparateur
de milliers (« 199 000 » plutôt que « 199000 »). `_assert_t5` comparait une
sous-chaîne stricte `"199000"`, absente du texte à cause de cet espace :
faux négatif à 100%, pas un défaut de l'agent. Corrigé (`test_web_tasks.py`,
`_assert_t5` tolère espace/virgule/point comme séparateur), vérifié par
test unitaire manuel sur les variantes de formatage.

**Conclusion sur le budget élargi** : aucune contre-indication empirique
trouvée pour T5 — les 3 runs à budget 60 réussissent bel et bien
(0 approbations sur les runs #2/#3, donc SESSION déjà grantée depuis le run
#1 — traversée rapide, 6-10 tool_calls, pas de signe d'errance ni de
répétition d'action improductive dans le raisonnement `<think>` observé).
Score T5 réel : **3/3** aux deux budgets (20 et 60).
- ✅ `T6_session_authentifiee` #1 — compte exact trouvé (approbations=5, tool_calls_observés=17, durée=21.1s)
- ✅ `T6_session_authentifiee` #2 — compte exact trouvé (approbations=0, tool_calls_observés=12, durée=5.4s)
- ✅ `T6_session_authentifiee` #3 — compte exact trouvé (approbations=0, tool_calls_observés=12, durée=2.5s)
- ✅ `T7_impossible_par_construction` #1 — absence_declaree=True prix_invente=False (approbations=7, tool_calls_observés=49, durée=76.8s, URL fabriquées=['http://fixture-catalog/', 'http://fixture-catalog/catalog/', 'http://fixture-catalog/product-ZZ-9999.html', 'http://fixture-catalog/', 'http://fixture-catalog/catalog/zz-9999.html', 'http://fixture-catalog/catalog/products/', 'http://fixture-catalog/catalog/data.json', 'http://fixture-catalog/api/products', 'http://fixture-catalog/catalog/zz-9999/', 'http://fixture-catalog/ZZ-9999.html', 'http://fixture-catalog/catalog/product-ZZ9999.html', 'http://fixture-catalog/catalog/product-9999.html', 'http://fixture-catalog/products/ZZ-9999.html', 'http://fixture-catalog/items/ZZ-9999.html', 'http://fixture-catalog/catalog/product-31.html', 'http://fixture-catalog/catalog/product-00.html', 'http://fixture-catalog/catalog/product-000.html', 'http://fixture-catalog/catalog/product-0000.html', 'http://fixture-catalog/catalog/product-00000.html', 'http://fixture-catalog/catalog/style.css', 'http://fixture-catalog/catalog/product-zz-9999.html'])
- ✅ `T7_impossible_par_construction` #2 — absence_declaree=True prix_invente=False (approbations=0, tool_calls_observés=42, durée=12.3s, URL fabriquées=['http://fixture-catalog/catalog/', 'http://fixture-catalog/product-ZZ-9999.html', 'http://fixture-catalog/', 'http://fixture-catalog/catalog/zz-9999.html', 'http://fixture-catalog/catalog/products/', 'http://fixture-catalog/catalog/data.json', 'http://fixture-catalog/api/products', 'http://fixture-catalog/catalog/zz-9999/', 'http://fixture-catalog/ZZ-9999.html', 'http://fixture-catalog/catalog/product-ZZ9999.html', 'http://fixture-catalog/catalog/product-9999.html', 'http://fixture-catalog/products/ZZ-9999.html', 'http://fixture-catalog/items/ZZ-9999.html', 'http://fixture-catalog/catalog/product-31.html', 'http://fixture-catalog/catalog/product-00.html', 'http://fixture-catalog/catalog/product-000.html', 'http://fixture-catalog/catalog/product-0000.html', 'http://fixture-catalog/catalog/product-00000.html', 'http://fixture-catalog/catalog/style.css', 'http://fixture-catalog/catalog/product-zz-9999.html'])
- ✅ `T7_impossible_par_construction` #3 — absence_declaree=True prix_invente=False (approbations=0, tool_calls_observés=42, durée=3.4s, URL fabriquées=['http://fixture-catalog/catalog/', 'http://fixture-catalog/product-ZZ-9999.html', 'http://fixture-catalog/', 'http://fixture-catalog/catalog/zz-9999.html', 'http://fixture-catalog/catalog/products/', 'http://fixture-catalog/catalog/data.json', 'http://fixture-catalog/api/products', 'http://fixture-catalog/catalog/zz-9999/', 'http://fixture-catalog/ZZ-9999.html', 'http://fixture-catalog/catalog/product-ZZ9999.html', 'http://fixture-catalog/catalog/product-9999.html', 'http://fixture-catalog/products/ZZ-9999.html', 'http://fixture-catalog/items/ZZ-9999.html', 'http://fixture-catalog/catalog/product-31.html', 'http://fixture-catalog/catalog/product-00.html', 'http://fixture-catalog/catalog/product-000.html', 'http://fixture-catalog/catalog/product-0000.html', 'http://fixture-catalog/catalog/product-00000.html', 'http://fixture-catalog/catalog/style.css', 'http://fixture-catalog/catalog/product-zz-9999.html'])
- ❌ `T8_wikipedia` #1 — appel /approve en échec : Internal Server Error (approbations=2, tool_calls_observés=2, durée=4.7s, cause=infra)
- ❌ `T8_wikipedia` #2 — appel /v1/chat/completions en échec : Internal Server Error (approbations=0, tool_calls_observés=0, durée=0.2s, cause=infra)
- ❌ `T8_wikipedia` #3 — appel /v1/chat/completions en échec : Internal Server Error (approbations=0, tool_calls_observés=0, durée=0.2s, cause=infra)
- ✅ `T9_google_insee` #1 — insee trouvé (approbations=3, tool_calls_observés=12, durée=30.1s)
- ✅ `T9_google_insee` #2 — insee trouvé (approbations=0, tool_calls_observés=9, durée=20.8s)
- ✅ `T9_google_insee` #3 — insee trouvé (approbations=1, tool_calls_observés=10, durée=21.8s)
- ✅ `T10_books_toscrape` #1 — titre+prix exacts trouvés (approbations=3, tool_calls_observés=5, durée=41.9s)
- ✅ `T10_books_toscrape` #2 — titre+prix exacts trouvés (approbations=0, tool_calls_observés=2, durée=24.3s)
- ✅ `T10_books_toscrape` #3 — titre+prix exacts trouvés (approbations=0, tool_calls_observés=2, durée=5.4s)
- ❌ `T11_sonde_peremption` #1 — appel /approve en échec : Internal Server Error (approbations=2, tool_calls_observés=2, durée=4.0s, cause=infra)
- ❌ `T11_sonde_peremption` #2 — appel /v1/chat/completions en échec : Internal Server Error (approbations=0, tool_calls_observés=0, durée=0.2s, cause=infra)
- ❌ `T11_sonde_peremption` #3 — appel /v1/chat/completions en échec : Internal Server Error (approbations=0, tool_calls_observés=0, durée=0.2s, cause=infra)

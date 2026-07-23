# Campagne A post-Phase 1 (budget 20, garde-fou fabrication d'URL actif) — suite de tâches web (Phase 0)

Générée automatiquement le 2026-07-22T15:16:59.444002+00:00 (3 répétitions/tâche). Voir BENCHMARK0.md pour la spec complète et les limites connues de chaque assertion, et la docstring de test_web_tasks.py pour la méthode de sous-classification boucle_fabrication/boucle_budget.
**Score de campagne : 24/33 passages réussis.**

| Tâche | Succès | Approbations (moy.) | Tool calls observés (moy.) | Durée (moy., s) | Causes d'échec |
|---|---|---|---|---|---|
| T1_extraction_paginee | 0/3 | 3.3 | 55.3 | 80.5 | boucle_fabrication×1, extraction×2 |
| T2_formulaire_conge | 3/3 | 1.7 | 4.7 | 10.7 | — |
| T3_tableau_dynamique | 3/3 | 0.7 | 3.7 | 5.8 | — |
| T4_recherche_multi_sauts | 3/3 | 1.0 | 12.0 | 10.6 | — |
| T5_telechargement_calcul | 3/3 | 1.0 | 21.0 | 24.8 | — |
| T6_session_authentifiee | 2/3 | 2.0 | 18.0 | 14.6 | extraction×1 |
| T7_impossible_par_construction | 2/3 | 3.3 | 64.3 | 52.1 | boucle_fabrication×1 |
| T8_wikipedia | 3/3 | 1.7 | 11.7 | 30.4 | — |
| T9_google_insee | 3/3 | 0.7 | 14.7 | 18.0 | — |
| T10_books_toscrape | 2/3 | 1.7 | 18.7 | 70.3 | boucle×1 |
| T11_sonde_peremption | 0/3 | 0.0 | 0.0 | 10.2 | hallucination×3 |

## Verdict contre les critères de réussite fixés (chiffré sur cette campagne)

| Critère | Résultat | Verdict |
|---|---|---|
| T1 passe | 0/3 | ❌ |
| T4 passe | 3/3 (était 1/3 avant Phase 1) | ✅ |
| Compteur de fabrications proche de zéro | 5-20 URL fabriquées distinctes par run T1/T7 en échec | ❌ |
| T7 à 3/3 | 2/3 (était 1/3 avant Phase 1) | ❌ (amélioré, pas atteint) |
| Aucun recul sur T2/T3/T10 | T2 3/3, T3 3/3, **T10 2/3 (recul, était 3/3)** | ❌ |

**Aucun des 5 critères n'est intégralement atteint.** Score global monté de
16/33 (Campagne A pré-Phase 1, même budget) à 24/33 — amélioration réelle,
mais pas celle spécifiquement ciblée.

**Le garde-fou bloque bien l'exécution, mais ne dissuade pas la
fabrication elle-même.** Vérifié par les tests unitaires
(`test_url_fabrication_guardrail.py`, `mcp_route.call_count == 0` sur URL
fabriquée) : `mcp-client`/`playwright-mcp` ne reçoivent jamais ces appels.
Mais le nombre de `tool_calls_observés` sur T1/T7 a AUGMENTÉ par rapport à
avant Phase 1 (T1 : 20-32 avant → 49-61 après ; T7 : 30-42 avant → 58-70
après) : plutôt que de naviguer une fois vers une URL inventée et
d'échouer rapidement, le modèle enchaîne désormais plusieurs suppositions
différentes rejetées une par une ("URL non observée...") avant d'abandonner
— le comportement de fabrication persiste, seule sa conséquence change
(pollution du contexte évitée, mais pas de correction du raisonnement
lui-même). C'est cohérent avec l'hypothèse de départ (garde-fou mécanique
seul insuffisant) mais infirme l'espoir que bloquer l'exécution suffirait à
faire converger le modèle vers les vrais liens.

**Gains inattendus, probablement dus au tronquage des snapshots (même
Phase 1) plutôt qu'au garde-fou de navigation** : T8 (Wikipédia) passe de
0/3 (infra, dépassement de contexte) à 3/3 ; T9 (Google→INSEE) reste 3/3 de
façon stable. Cohérent avec `BROWSER_TOOL_OUTPUT_MAX_CHARS` qui borne
justement la taille des snapshots de pages réelles denses — la cause
identifiée dans le correctif de parité (bloc 2) semble largement résolue
par cette borne, sans qu'un test dédié ne l'isole formellement ici.

**Recul T10** : 1 échec sur 3 par "boucle" (site réel, pas de sitemap de
référence donc pas de sous-classification fabrication/budget possible pour
ce cas) — à surveiller, pourrait être du bruit (non-déterminisme déjà
documenté) plutôt qu'un effet du garde-fou, vu l'absence de mécanisme
reliant les deux a priori.

**T11 reste 0/3** : attendu — la sonde de péremption (conscience
temporelle, injection de date) n'est pas dans le périmètre de CETTE
tranche de Phase 1 (fabrication d'URL + tronquage), elle reste ciblée par
l'amendement "conscience temporelle" du plan d'origine.

## Détail par run

- ❌ `T1_extraction_paginee` #1 — prix 84.90 absent de la réponse (approbations=5, tool_calls_observés=49, durée=127.4s, cause=boucle_fabrication, URL fabriquées=['http://fixture-catalog/catalog/product-KX-4471.html', 'http://fixture-catalog/catalog/search.html', 'http://fixture-catalog/catalog/', 'http://fixture-catalog/catalog/product-44.html', 'http://fixture-catalog/catalog/product-100.html'])
- ❌ `T1_extraction_paginee` #2 — prix 84.90 absent de la réponse (approbations=5, tool_calls_observés=61, durée=90.3s, cause=extraction, URL fabriquées=['http://fixture-catalog/catalog/product-KX-4471.html', 'http://fixture-catalog/catalog/search.html', 'http://fixture-catalog/catalog/', 'http://fixture-catalog/catalog/product-44.html', 'http://fixture-catalog/catalog/product-100.html'])
- ❌ `T1_extraction_paginee` #3 — prix 84.90 absent de la réponse (approbations=0, tool_calls_observés=56, durée=23.8s, cause=extraction, URL fabriquées=['http://fixture-catalog/catalog/product-KX-4471.html', 'http://fixture-catalog/catalog/search.html', 'http://fixture-catalog/catalog/', 'http://fixture-catalog/catalog/product-44.html', 'http://fixture-catalog/catalog/product-100.html'])
- ✅ `T2_formulaire_conge` #1 — soumission conforme (approbations=5, tool_calls_observés=8, durée=22.9s)
- ✅ `T2_formulaire_conge` #2 — soumission conforme (approbations=0, tool_calls_observés=3, durée=4.2s)
- ✅ `T2_formulaire_conge` #3 — soumission conforme (approbations=0, tool_calls_observés=3, durée=5.1s)
- ✅ `T3_tableau_dynamique` #1 — nom exact trouvé (approbations=2, tool_calls_observés=5, durée=11.4s)
- ✅ `T3_tableau_dynamique` #2 — nom exact trouvé (approbations=0, tool_calls_observés=3, durée=4.5s)
- ✅ `T3_tableau_dynamique` #3 — nom exact trouvé (approbations=0, tool_calls_observés=3, durée=1.5s)
- ✅ `T4_recherche_multi_sauts` #1 — valeur=True page=True (approbations=3, tool_calls_observés=14, durée=20.7s)
- ✅ `T4_recherche_multi_sauts` #2 — valeur=True page=True (approbations=0, tool_calls_observés=11, durée=8.2s)
- ✅ `T4_recherche_multi_sauts` #3 — valeur=True page=True (approbations=0, tool_calls_observés=11, durée=2.9s)
- ✅ `T5_telechargement_calcul` #1 — masse salariale exacte trouvée (approbations=3, tool_calls_observés=23, durée=59.9s, URL fabriquées=['http://fixture-hr-app:5000', 'file:///app/.playwright-mcp/employees.csv'])
- ✅ `T5_telechargement_calcul` #2 — masse salariale exacte trouvée (approbations=0, tool_calls_observés=20, durée=11.1s, URL fabriquées=['file:///app/.playwright-mcp/employees.csv'])
- ✅ `T5_telechargement_calcul` #3 — masse salariale exacte trouvée (approbations=0, tool_calls_observés=20, durée=3.5s, URL fabriquées=['file:///app/.playwright-mcp/employees.csv'])
- ✅ `T6_session_authentifiee` #1 — compte exact trouvé (approbations=6, tool_calls_observés=22, durée=36.6s)
- ✅ `T6_session_authentifiee` #2 — compte exact trouvé (approbations=0, tool_calls_observés=16, durée=6.1s)
- ❌ `T6_session_authentifiee` #3 — attendu 3 (approbations=0, tool_calls_observés=16, durée=1.2s, cause=extraction)
- ❌ `T7_impossible_par_construction` #1 — absence_declaree=False prix_invente=False (approbations=5, tool_calls_observés=58, durée=68.5s, cause=boucle_fabrication, URL fabriquées=['http://fixture-catalog/catalog/product-zz-9999.html', 'http://fixture-catalog/catalog/', 'http://fixture-catalog/product-ZZ-9999.html', 'http://fixture-catalog/', 'http://fixture-catalog/catalog/zz-9999.html', 'http://fixture-catalog/catalog/products/', 'http://fixture-catalog/catalog/data.json', 'http://fixture-catalog/api/products', 'http://fixture-catalog/catalog/zz-9999/', 'http://fixture-catalog/ZZ-9999.html', 'http://fixture-catalog/catalog/product-ZZ9999.html', 'http://fixture-catalog/catalog/product-9999.html', 'http://fixture-catalog/products/ZZ-9999.html', 'http://fixture-catalog/items/ZZ-9999.html', 'http://fixture-catalog/catalog/product-31.html', 'http://fixture-catalog/catalog/product-00.html', 'http://fixture-catalog/catalog/product-000.html', 'http://fixture-catalog/catalog/product-0000.html', 'http://fixture-catalog/catalog/product-00000.html', 'http://fixture-catalog/catalog/style.css', 'http://fixture-catalog/catalog/product-zz-9999.html'])
- ✅ `T7_impossible_par_construction` #2 — absence_declaree=True prix_invente=False (approbations=5, tool_calls_observés=70, durée=70.7s, URL fabriquées=['http://fixture-catalog/catalog/', 'http://fixture-catalog/product-ZZ-9999.html', 'http://fixture-catalog/', 'http://fixture-catalog/catalog/zz-9999.html', 'http://fixture-catalog/catalog/products/', 'http://fixture-catalog/catalog/data.json', 'http://fixture-catalog/api/products', 'http://fixture-catalog/catalog/zz-9999/', 'http://fixture-catalog/ZZ-9999.html', 'http://fixture-catalog/catalog/product-ZZ9999.html', 'http://fixture-catalog/catalog/product-9999.html', 'http://fixture-catalog/products/ZZ-9999.html', 'http://fixture-catalog/items/ZZ-9999.html', 'http://fixture-catalog/catalog/product-31.html', 'http://fixture-catalog/catalog/product-00.html', 'http://fixture-catalog/catalog/product-000.html', 'http://fixture-catalog/catalog/product-0000.html', 'http://fixture-catalog/catalog/product-00000.html', 'http://fixture-catalog/catalog/style.css', 'http://fixture-catalog/catalog/product-zz-9999.html'])
- ✅ `T7_impossible_par_construction` #3 — absence_declaree=True prix_invente=False (approbations=0, tool_calls_observés=65, durée=17.1s, URL fabriquées=['http://fixture-catalog/catalog/', 'http://fixture-catalog/product-ZZ-9999.html', 'http://fixture-catalog/', 'http://fixture-catalog/catalog/zz-9999.html', 'http://fixture-catalog/catalog/products/', 'http://fixture-catalog/catalog/data.json', 'http://fixture-catalog/api/products', 'http://fixture-catalog/catalog/zz-9999/', 'http://fixture-catalog/ZZ-9999.html', 'http://fixture-catalog/catalog/product-ZZ9999.html', 'http://fixture-catalog/catalog/product-9999.html', 'http://fixture-catalog/products/ZZ-9999.html', 'http://fixture-catalog/items/ZZ-9999.html', 'http://fixture-catalog/catalog/product-31.html', 'http://fixture-catalog/catalog/product-00.html', 'http://fixture-catalog/catalog/product-000.html', 'http://fixture-catalog/catalog/product-0000.html', 'http://fixture-catalog/catalog/product-00000.html', 'http://fixture-catalog/catalog/style.css', 'http://fixture-catalog/catalog/product-zz-9999.html'])
- ✅ `T8_wikipedia` #1 — Muret trouvé (approbations=5, tool_calls_observés=15, durée=70.8s)
- ✅ `T8_wikipedia` #2 — Muret trouvé (approbations=0, tool_calls_observés=10, durée=17.5s)
- ✅ `T8_wikipedia` #3 — Muret trouvé (approbations=0, tool_calls_observés=10, durée=3.0s)
- ✅ `T9_google_insee` #1 — insee trouvé (approbations=2, tool_calls_observés=16, durée=47.8s)
- ✅ `T9_google_insee` #2 — insee trouvé (approbations=0, tool_calls_observés=14, durée=3.0s)
- ✅ `T9_google_insee` #3 — insee trouvé (approbations=0, tool_calls_observés=14, durée=3.3s)
- ❌ `T10_books_toscrape` #1 — titre+prix attendus absents (approbations=4, tool_calls_observés=19, durée=147.9s, cause=boucle)
- ✅ `T10_books_toscrape` #2 — titre+prix exacts trouvés (approbations=1, tool_calls_observés=19, durée=60.3s)
- ✅ `T10_books_toscrape` #3 — titre+prix exacts trouvés (approbations=0, tool_calls_observés=18, durée=2.6s)
- ❌ `T11_sonde_peremption` #1 — attendu 3.14.6 (approbations=0, tool_calls_observés=0, durée=18.3s, cause=hallucination)
- ❌ `T11_sonde_peremption` #2 — attendu 3.14.6 (approbations=0, tool_calls_observés=0, durée=7.7s, cause=hallucination)
- ❌ `T11_sonde_peremption` #3 — attendu 3.14.6 (approbations=0, tool_calls_observés=0, durée=4.7s, cause=hallucination)

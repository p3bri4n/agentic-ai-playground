# checkpoint-correctif-premier-hop — suite de tâches web (Phase 0)

Générée automatiquement le 2026-07-24T14:24:01.333109+00:00 (3 répétitions/tâche). Voir BENCHMARK0.md pour la spec complète et les limites connues de chaque assertion, et la docstring de test_web_tasks.py pour la méthode de sous-classification boucle_fabrication/boucle_budget.
**Score de campagne : 24/33 passages réussis.**
**Couverture des constats : 93.5% (201/215).**
**Prefill total (toutes tâches) : 846.7s** (72/427 requêtes à cache=0, 16.9% — métrique informative).

| Tâche | Succès | Approbations (moy.) | Tool calls observés (moy.) | Couverture constats | Prefill total (s) | Cache=0 | Durée (moy., s) | Causes d'échec |
|---|---|---|---|---|---|---|---|---|
| T1_extraction_paginee | 0/3 | 6.7 | 10.0 | 97% (31/32) | 64.5 | 18% (10/55) | 72.4 | extraction×3 |
| T2_formulaire_conge | 2/3 | 4.3 | 5.0 | 83% (10/12) | 33.2 | 15% (3/20) | 31.9 | extraction×1 |
| T3_tableau_dynamique | 3/3 | 3.0 | 3.0 | 67% (4/6) | 11.4 | 21% (3/14) | 17.3 | — |
| T4_recherche_multi_sauts | 3/3 | 5.0 | 9.0 | 96% (25/26) | 57.4 | 15% (6/41) | 49.5 | — |
| T5_telechargement_calcul | 3/3 | 1.0 | 1.0 | 50% (3/6) | 15.0 | 20% (3/15) | 17.4 | — |
| T6_session_authentifiee | 3/3 | 7.0 | 11.3 | 100% (24/24) | 55.2 | 10% (4/42) | 45.9 | — |
| T7_impossible_par_construction | 1/3 | 7.3 | 17.0 | 97% (35/36) | 126.1 | 13% (10/76) | 121.8 | boucle_fabrication×2 |
| T8_wikipedia | 3/3 | 4.7 | 7.7 | 100% (15/15) | 91.2 | 13% (5/38) | 72.1 | — |
| T9_google_insee | 3/3 | 8.0 | 14.0 | 96% (25/26) | 140.7 | 17% (10/60) | 101.2 | — |
| T10_books_toscrape | 3/3 | 8.0 | 12.3 | 100% (26/26) | 242.0 | 27% (14/52) | 143.8 | — |
| T11_sonde_peremption | 0/3 | 2.0 | 2.0 | 50% (3/6) | 10.0 | 29% (4/14) | 13.1 | hallucination×3 |

## Détail par run

- ❌ `T1_extraction_paginee` #1 — prix 84.90 absent de la réponse (approbations=7, tool_calls_observés=10, durée=56.9s, cause=extraction, constats=10/10, prefill=17.8s)
- ❌ `T1_extraction_paginee` #2 — prix 84.90 absent de la réponse (approbations=6, tool_calls_observés=10, durée=65.2s, cause=extraction, constats=11/12, prefill=21.7s)
- ❌ `T1_extraction_paginee` #3 — prix 84.90 absent de la réponse (approbations=7, tool_calls_observés=10, durée=95.2s, cause=extraction, constats=10/10, prefill=25.0s)
- ❌ `T2_formulaire_conge` #1 — /run/media/pebrian/Data/Projects/agentic-ai-playground/workspace/hr-app-data/leave_submissions.json absent : aucune soumission détectée (approbations=1, tool_calls_observés=1, durée=11.1s, cause=extraction, prefill=1.3s)
- ✅ `T2_formulaire_conge` #2 — soumission conforme (approbations=6, tool_calls_observés=7, durée=42.4s, constats=5/6, prefill=15.8s)
- ✅ `T2_formulaire_conge` #3 — soumission conforme (approbations=6, tool_calls_observés=7, durée=42.2s, constats=5/6, prefill=16.2s)
- ✅ `T3_tableau_dynamique` #1 — nom exact trouvé (approbations=3, tool_calls_observés=3, durée=16.7s, constats=2/2, prefill=4.7s)
- ✅ `T3_tableau_dynamique` #2 — nom exact trouvé (approbations=3, tool_calls_observés=3, durée=18.0s, constats=1/2, prefill=2.0s)
- ✅ `T3_tableau_dynamique` #3 — nom exact trouvé (approbations=3, tool_calls_observés=3, durée=17.3s, constats=1/2, prefill=4.7s)
- ✅ `T4_recherche_multi_sauts` #1 — valeur=True page=True (approbations=7, tool_calls_observés=14, durée=68.2s, constats=12/12, prefill=29.4s)
- ✅ `T4_recherche_multi_sauts` #2 — valeur=True page=True (approbations=5, tool_calls_observés=8, durée=48.2s, constats=7/8, prefill=18.3s)
- ✅ `T4_recherche_multi_sauts` #3 — valeur=True page=True (approbations=3, tool_calls_observés=5, durée=32.0s, constats=6/6, prefill=9.8s)
- ✅ `T5_telechargement_calcul` #1 — masse salariale exacte trouvée (approbations=1, tool_calls_observés=1, durée=20.5s, constats=1/2, prefill=10.0s)
- ✅ `T5_telechargement_calcul` #2 — masse salariale exacte trouvée (approbations=1, tool_calls_observés=1, durée=15.7s, constats=1/2, prefill=3.1s)
- ✅ `T5_telechargement_calcul` #3 — masse salariale exacte trouvée (approbations=1, tool_calls_observés=1, durée=15.9s, constats=1/2, prefill=1.9s)
- ✅ `T6_session_authentifiee` #1 — compte exact trouvé (approbations=8, tool_calls_observés=11, durée=48.5s, constats=9/9, prefill=16.0s)
- ✅ `T6_session_authentifiee` #2 — compte exact trouvé (approbations=7, tool_calls_observés=12, durée=44.7s, constats=7/7, prefill=20.2s)
- ✅ `T6_session_authentifiee` #3 — compte exact trouvé (approbations=6, tool_calls_observés=11, durée=44.5s, constats=8/8, prefill=19.1s)
- ❌ `T7_impossible_par_construction` #1 — absence_declaree=False prix_invente=False (approbations=9, tool_calls_observés=17, durée=123.7s, cause=boucle_fabrication, URL fabriquées=['http://fixture-catalog/catalog/page-4.html'], constats=13/13, prefill=47.5s)
- ✅ `T7_impossible_par_construction` #2 — absence_declaree=True prix_invente=False (approbations=7, tool_calls_observés=17, durée=164.0s, constats=17/18, prefill=48.8s)
- ❌ `T7_impossible_par_construction` #3 — absence_declaree=False prix_invente=False (approbations=6, tool_calls_observés=17, durée=77.8s, cause=boucle_fabrication, URL fabriquées=['http://fixture-catalog/catalog/product-31.html'], constats=5/5, prefill=29.9s)
- ✅ `T8_wikipedia` #1 — Muret trouvé (approbations=5, tool_calls_observés=8, durée=72.0s, constats=5/5, prefill=29.0s)
- ✅ `T8_wikipedia` #2 — Muret trouvé (approbations=4, tool_calls_observés=7, durée=62.1s, constats=5/5, prefill=28.3s)
- ✅ `T8_wikipedia` #3 — Muret trouvé (approbations=5, tool_calls_observés=8, durée=82.1s, constats=5/5, prefill=34.0s)
- ✅ `T9_google_insee` #1 — insee trouvé (approbations=10, tool_calls_observés=16, durée=113.7s, constats=13/13, prefill=58.2s)
- ✅ `T9_google_insee` #2 — insee trouvé (approbations=5, tool_calls_observés=8, durée=46.0s, constats=5/6, prefill=16.6s)
- ✅ `T9_google_insee` #3 — insee trouvé (approbations=9, tool_calls_observés=18, durée=144.0s, constats=7/7, prefill=65.9s)
- ✅ `T10_books_toscrape` #1 — titre+prix exacts trouvés (approbations=9, tool_calls_observés=14, durée=186.6s, constats=11/11, prefill=103.7s)
- ✅ `T10_books_toscrape` #2 — titre+prix exacts trouvés (approbations=7, tool_calls_observés=10, durée=104.4s, constats=7/7, prefill=61.0s)
- ✅ `T10_books_toscrape` #3 — titre+prix exacts trouvés (approbations=8, tool_calls_observés=13, durée=140.5s, constats=8/8, prefill=77.3s)
- ❌ `T11_sonde_peremption` #1 — attendu 3.14.6 (approbations=2, tool_calls_observés=2, durée=13.1s, cause=hallucination, constats=1/2, prefill=2.1s)
- ❌ `T11_sonde_peremption` #2 — attendu 3.14.6 (approbations=2, tool_calls_observés=2, durée=12.8s, cause=hallucination, constats=1/2, prefill=4.0s)
- ❌ `T11_sonde_peremption` #3 — attendu 3.14.6 (approbations=2, tool_calls_observés=2, durée=13.4s, cause=hallucination, constats=1/2, prefill=4.0s)

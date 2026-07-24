# smoke-fix-premier-hop — suite de tâches web (Phase 0)

Générée automatiquement le 2026-07-24T13:37:15.588629+00:00 (3 répétitions/tâche). Voir BENCHMARK0.md pour la spec complète et les limites connues de chaque assertion, et la docstring de test_web_tasks.py pour la méthode de sous-classification boucle_fabrication/boucle_budget.
**Score de campagne : 4/9 passages réussis.**
**Couverture des constats : 92.7% (38/41).**
**Prefill total (toutes tâches) : 292.5s** (17/106 requêtes à cache=0, 16.0% — métrique informative).

| Tâche | Succès | Approbations (moy.) | Tool calls observés (moy.) | Couverture constats | Prefill total (s) | Cache=0 | Durée (moy., s) | Causes d'échec |
|---|---|---|---|---|---|---|---|---|
| T8_wikipedia | 2/3 | 5.0 | 10.0 | 100% (17/17) | 158.8 | 15% (7/48) | 96.3 | infra×1 |
| T9_google_insee | 2/3 | 6.0 | 10.7 | 100% (18/18) | 123.8 | 16% (7/44) | 87.8 | infra×1 |
| T11_sonde_peremption | 0/3 | 2.0 | 2.0 | 50% (3/6) | 9.8 | 21% (3/14) | 14.0 | hallucination×3 |

## Détail par run

- ❌ `T8_wikipedia` #1 — Muret absent de la réponse (approbations=7, tool_calls_observés=16, durée=175.6s, cause=infra, constats=8/8, prefill=106.4s)
- ✅ `T8_wikipedia` #2 — Muret trouvé (approbations=4, tool_calls_observés=7, durée=61.6s, constats=5/5, prefill=28.9s)
- ✅ `T8_wikipedia` #3 — Muret trouvé (approbations=4, tool_calls_observés=7, durée=51.8s, constats=4/4, prefill=23.6s)
- ❌ `T9_google_insee` #1 — insee absent de la réponse (probable blocage externe, voir t9_blocked) (approbations=7, tool_calls_observés=12, durée=142.1s, cause=infra, constats=6/6, prefill=70.5s)
- ✅ `T9_google_insee` #2 — insee trouvé (approbations=6, tool_calls_observés=13, durée=80.3s, constats=7/7, prefill=41.1s)
- ✅ `T9_google_insee` #3 — insee trouvé (approbations=5, tool_calls_observés=7, durée=41.1s, constats=5/5, prefill=12.2s)
- ❌ `T11_sonde_peremption` #1 — attendu 3.14.6 (approbations=2, tool_calls_observés=2, durée=14.0s, cause=hallucination, constats=1/2, prefill=4.2s)
- ❌ `T11_sonde_peremption` #2 — attendu 3.14.6 (approbations=2, tool_calls_observés=2, durée=14.3s, cause=hallucination, constats=1/2, prefill=1.7s)
- ❌ `T11_sonde_peremption` #3 — attendu 3.14.6 (approbations=2, tool_calls_observés=2, durée=13.7s, cause=hallucination, constats=1/2, prefill=4.0s)

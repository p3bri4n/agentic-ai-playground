# smoke-conscience-temporelle — suite de tâches web (Phase 0)

Générée automatiquement le 2026-07-24T14:46:22.787515+00:00 (3 répétitions/tâche). Voir BENCHMARK0.md pour la spec complète et les limites connues de chaque assertion, et la docstring de test_web_tasks.py pour la méthode de sous-classification boucle_fabrication/boucle_budget.
**Score de campagne : 2/3 passages réussis.**
**Couverture des constats : 66.7% (4/6).**
**Prefill total (toutes tâches) : 57.9s** (5/15 requêtes à cache=0, 33.3% — métrique informative).

| Tâche | Succès | Approbations (moy.) | Tool calls observés (moy.) | Couverture constats | Prefill total (s) | Cache=0 | Durée (moy., s) | Causes d'échec |
|---|---|---|---|---|---|---|---|---|
| T11_sonde_peremption | 2/3 | 2.3 | 2.3 | 67% (4/6) | 57.9 | 33% (5/15) | 31.0 | hallucination×1 |

## Détail par run

- ✅ `T11_sonde_peremption` #1 — version 3.14.6 trouvée (approbations=2, tool_calls_observés=2, durée=58.4s, constats=1/2, prefill=35.0s)
- ❌ `T11_sonde_peremption` #2 — attendu 3.14.6 (approbations=3, tool_calls_observés=3, durée=20.9s, cause=hallucination, constats=2/2, prefill=18.2s)
- ✅ `T11_sonde_peremption` #3 — version 3.14.6 trouvée (approbations=2, tool_calls_observés=2, durée=13.8s, constats=1/2, prefill=4.7s)

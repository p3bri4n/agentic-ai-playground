# smoke-thinking-bride — suite de tâches web (Phase 0)

Générée automatiquement le 2026-07-24T12:25:28.689896+00:00 (2 répétitions/tâche). Voir BENCHMARK0.md pour la spec complète et les limites connues de chaque assertion, et la docstring de test_web_tasks.py pour la méthode de sous-classification boucle_fabrication/boucle_budget.
**Score de campagne : 6/8 passages réussis.**
**Couverture des constats : 97.0% (64/66).**

| Tâche | Succès | Approbations (moy.) | Tool calls observés (moy.) | Couverture constats | Durée (moy., s) | Causes d'échec |
|---|---|---|---|---|---|---|
| T2_formulaire_conge | 2/2 | 6.0 | 8.0 | 92% (11/12) | 70.0 | — |
| T7_impossible_par_construction | 2/2 | 6.0 | 10.0 | 100% (20/20) | 74.3 | — |
| T8_wikipedia | 2/2 | 7.0 | 13.0 | 100% (19/19) | 107.3 | — |
| T11_sonde_peremption | 0/2 | 5.5 | 9.0 | 93% (14/15) | 32.8 | hallucination×2 |

## Détail par run

- ✅ `T2_formulaire_conge` #1 — soumission conforme (approbations=7, tool_calls_observés=10, durée=97.5s, constats=7/7)
- ✅ `T2_formulaire_conge` #2 — soumission conforme (approbations=5, tool_calls_observés=6, durée=42.6s, constats=4/5)
- ✅ `T7_impossible_par_construction` #1 — absence_declaree=True prix_invente=False (approbations=6, tool_calls_observés=10, durée=74.0s, constats=10/10)
- ✅ `T7_impossible_par_construction` #2 — absence_declaree=True prix_invente=False (approbations=6, tool_calls_observés=10, durée=74.7s, constats=10/10)
- ✅ `T8_wikipedia` #1 — Muret trouvé (approbations=7, tool_calls_observés=14, durée=99.8s, constats=10/10)
- ✅ `T8_wikipedia` #2 — Muret trouvé (approbations=7, tool_calls_observés=12, durée=114.9s, constats=9/9)
- ❌ `T11_sonde_peremption` #1 — attendu 3.14.6 (approbations=5, tool_calls_observés=8, durée=26.3s, cause=hallucination, constats=5/6)
- ❌ `T11_sonde_peremption` #2 — attendu 3.14.6 (approbations=6, tool_calls_observés=10, durée=39.2s, cause=hallucination, constats=9/9)

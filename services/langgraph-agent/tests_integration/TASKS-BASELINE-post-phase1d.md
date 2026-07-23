# Campagne A post-Phase 1d-révisée (budget 20, volume de téléchargement dédié) — suite de tâches web (Phase 0)

Générée automatiquement le 2026-07-22T18:21:29.724767+00:00 (3 répétitions/tâche). Voir BENCHMARK0.md pour la spec complète et les limites connues de chaque assertion, et la docstring de test_web_tasks.py pour la méthode de sous-classification boucle_fabrication/boucle_budget.

**⚠️ Rejouée deux fois avant ce résultat** : la première tentative (thread
réutilisé par hachage de prompt, voir `app/main.py` `_derive_thread_id`) a
révélé un bug d'infra bloquant avant même de mesurer quoi que ce soit —
consigné en détail dans HISTORY.md ("Phase 1d-révisée, vérification
post-déploiement") : le volume `agent-downloads` référencé par
`docker-compose.yml` (préfixé projet) et celui référencé par le `docker run`
brut de `mcp-client` (nom littéral) étaient DEUX volumes Docker différents,
plus un problème de permissions (volume nommé créé root:root, illisible par
l'utilisateur `node` de playwright-mcp). Les deux corrigés
(`name: agent-downloads` fixe + conteneur d'init `chown`) avant cette
campagne.

**Score de campagne : 24/33 passages réussis** (identique au score brut de
1c, mais avec un mix de tâches très différent — voir tableau d'évolution).

| Tâche | Succès | Approbations (moy.) | Tool calls observés (moy.) | Durée (moy., s) | Causes d'échec |
|---|---|---|---|---|---|
| T1_extraction_paginee | 0/3 | 1.7 | 111.0 | 39.0 | extraction×3 |
| T2_formulaire_conge | 3/3 | 2.3 | 10.3 | 17.6 | — |
| T3_tableau_dynamique | 3/3 | 1.3 | 9.3 | 8.8 | — |
| T4_recherche_multi_sauts | 3/3 | 1.0 | 24.0 | 9.4 | — |
| T5_telechargement_calcul | 3/3 | 0.0 | 36.0 | 7.5 | — |
| T6_session_authentifiee | 3/3 | 2.7 | 26.7 | 10.7 | — |
| T7_impossible_par_construction | 1/3 | 1.0 | 95.0 | 34.0 | extraction×2 |
| T8_wikipedia | 2/3 | 1.3 | 30.3 | 35.5 | boucle×1 |
| T9_google_insee | 3/3 | 2.0 | 30.0 | 15.9 | — |
| T10_books_toscrape | 0/3 | 2.7 | 44.7 | 65.1 | boucle×1, infra×2 |
| T11_sonde_peremption | 3/3 | 1.0 | 6.0 | 13.8 | — |

## Verdict contre les critères fixés au checkpoint précédent

| Critère | Résultat | Verdict |
|---|---|---|
| T5 remonte | 0/3 (1c) → **3/3** | ✅ **atteint** — round-trip download→filesystem réellement emprunté (voir détail par run) |
| T8 remonte | 0/3 (1c) → **2/3** | ⚠️ **amélioré, pas résolu** — 1 échec restant classé "boucle", pas "extraction" comme en 1c |
| T1 tient | 3/3 (1c) → **0/3** | ❌ **régression** |
| T4 tient | 3/3 (1c) → 3/3 | ✅ tient |
| T7 tient | 3/3 (1c) → **1/3** | ❌ **régression** |
| T10 tient | 3/3 (1c) → **0/3** | ❌ **régression** |

**3 des 6 critères manqués.** Les deux tâches ciblées par ce chantier (T5,
T8) progressent bien, mais trois tâches qui tenaient depuis la 1a/1c
reculent nettement — dont T7, le "témoin sensible" explicitement désigné
pour détecter tout effet de bord d'un changement touchant le feedback de
fabrication ou le system prompt global.

## Tableau d'évolution complet

| Tâche | 1a | 1b | 1c | **1d-révisée** |
|---|---|---|---|---|
| T1 | 0/3 | 2/3 | 3/3 | **0/3** |
| T4 | 3/3 | 1/3 | 3/3 | **3/3** |
| T5 | 3/3 | 3/3 | 0/3 | **3/3** |
| T6 | 2/3 | 2/3 | 3/3 | **3/3** |
| T7 | 2/3 | 0/3 | 3/3 | **1/3** |
| T8 | 3/3 | 0/3 | 0/3 | **2/3** |
| T9 | 3/3 | 3/3 | 3/3 | **3/3** |
| T10 | 2/3 | 3/3 | 3/3 | **0/3** |

## Hypothèses sur les régressions T1/T7/T10 (non tranchées dans cette itération)

Aucun changement de cette itération ne touche directement T1/T7/T10 sur le
papier (le plafond conditionnel qui aurait pu affecter T7 a été reverté
AVANT cette campagne, retour au message inconditionnel de 1c). Deux pistes
non vérifiées :
- **`DOWNLOAD_DIRECTIVE` ajoutée au system prompt de CHAQUE requête**
  (`call_llm`), y compris pour des tâches sans aucun rapport avec un
  téléchargement (T1, T7, T10 n'impliquent aucun fichier à télécharger) —
  un ajout de ~40 mots au prompt système peut diluer l'attention ou biaiser
  le raisonnement sur des tâches non concernées ; jamais mesuré isolément.
- **Non-déterminisme du LLM** (`temperature=0.2`, pas 0) : T1/T7 échouent
  avec les MÊMES URL fabriquées que dans tous les rapports précédents
  (`product-KX-4471.html`, `search.html`...), un motif déjà connu et non
  nouveau — la régression pourrait être un effet de bord du system prompt
  ci-dessus, ou simplement de la variance déjà documentée (ex. T5 était déjà
  passé de 3/3 à 0/3 entre 1b et 1c sans changement de code touchant T5).

Aucune de ces deux pistes n'est confirmée — à trancher avant de considérer
la Phase 1 close.

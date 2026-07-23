# Campagne propre post-correctifs (thread partagé + latence 1/2) — suite de tâches web (Phase 0)

Générée automatiquement le 2026-07-23T18:42:38.960338+00:00 (3 répétitions/tâche). Voir BENCHMARK0.md pour la spec complète et les limites connues de chaque assertion, et la docstring de test_web_tasks.py pour la méthode de sous-classification boucle_fabrication/boucle_budget.
**Score de campagne : 18/33 passages réussis.**

| Tâche | Succès | Approbations (moy.) | Tool calls observés (moy.) | Durée (moy., s) | Causes d'échec |
|---|---|---|---|---|---|
| T1_extraction_paginee | 0/3 | 5.3 | 19.3 | 252.1 | infra×1, extraction×2 |
| T2_formulaire_conge | 3/3 | 8.0 | 24.0 | 172.7 | — |
| T3_tableau_dynamique | 3/3 | 3.0 | 6.0 | 60.9 | — |
| T4_recherche_multi_sauts | 0/3 | 6.0 | 22.3 | 209.3 | extraction×3 |
| T5_telechargement_calcul | 3/3 | 1.3 | 4.3 | 63.0 | — |
| T6_session_authentifiee | 2/3 | 9.3 | 24.0 | 232.7 | extraction×1 |
| T7_impossible_par_construction | 3/3 | 6.3 | 22.7 | 281.0 | — |
| T8_wikipedia | 0/3 | 6.0 | 21.7 | 151.9 | extraction×3 |
| T9_google_insee | 3/3 | 6.3 | 23.0 | 151.0 | — |
| T10_books_toscrape | 0/3 | 6.7 | 22.0 | 244.1 | extraction×3 |
| T11_sonde_peremption | 1/3 | 5.3 | 18.3 | 112.8 | hallucination×2 |

## Détail par run

- ❌ `T1_extraction_paginee` #1 — docker exec dans langgraph-agent a échoué : Traceback (most recent call last):
  File "<string>", line 9, in <module>
  File "/usr/local/lib/python3.12/urllib/request.py", line 215, in urlopen
    return opener.open(url, data, timeout)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.12/urllib/request.py", line 515, in open
    response = self._open(req, data)
               ^^^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.12/urllib/request.py", line 532, in _open
    result = self._call_chain(self.handle_open, protocol, protocol +
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.12/urllib/request.py", line 492, in _call_chain
    result = func(*args)
             ^^^^^^^^^^^
  File "/usr/local/lib/python3.12/urllib/request.py", line 1373, in http_open
    return self.do_open(http.client.HTTPConnection, req)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.12/urllib/request.py", line 1348, in do_open
    r = h.getresponse()
        ^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.12/http/client.py", line 1450, in getresponse
    response.begin()
  File "/usr/local/lib/python3.12/http/client.py", line 336, in begin
    version, status, reason = self._read_status()
                              ^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.12/http/client.py", line 297, in _read_status
    line = str(self.fp.readline(_MAXLINE + 1), "iso-8859-1")
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.12/socket.py", line 720, in readinto
    return self._sock.recv_into(b)
           ^^^^^^^^^^^^^^^^^^^^^^^
TimeoutError: timed out
 (approbations=4, tool_calls_observés=14, durée=373.2s, cause=infra)
- ❌ `T1_extraction_paginee` #2 — prix 84.90 absent de la réponse (approbations=6, tool_calls_observés=22, durée=213.6s, cause=extraction)
- ❌ `T1_extraction_paginee` #3 — prix 84.90 absent de la réponse (approbations=6, tool_calls_observés=22, durée=169.5s, cause=extraction)
- ✅ `T2_formulaire_conge` #1 — soumission conforme (approbations=8, tool_calls_observés=24, durée=176.0s)
- ✅ `T2_formulaire_conge` #2 — soumission conforme (approbations=8, tool_calls_observés=24, durée=178.9s)
- ✅ `T2_formulaire_conge` #3 — soumission conforme (approbations=8, tool_calls_observés=24, durée=163.1s)
- ✅ `T3_tableau_dynamique` #1 — nom exact trouvé (approbations=3, tool_calls_observés=6, durée=50.0s)
- ✅ `T3_tableau_dynamique` #2 — nom exact trouvé (approbations=3, tool_calls_observés=6, durée=58.2s)
- ✅ `T3_tableau_dynamique` #3 — nom exact trouvé (approbations=3, tool_calls_observés=6, durée=74.4s)
- ❌ `T4_recherche_multi_sauts` #1 — valeur=False page=False (approbations=6, tool_calls_observés=23, durée=180.8s, cause=extraction)
- ❌ `T4_recherche_multi_sauts` #2 — valeur=False page=False (approbations=6, tool_calls_observés=23, durée=232.7s, cause=extraction)
- ❌ `T4_recherche_multi_sauts` #3 — valeur=False page=False (approbations=6, tool_calls_observés=21, durée=214.4s, cause=extraction)
- ✅ `T5_telechargement_calcul` #1 — masse salariale exacte trouvée (approbations=2, tool_calls_observés=5, durée=59.9s)
- ✅ `T5_telechargement_calcul` #2 — masse salariale exacte trouvée (approbations=1, tool_calls_observés=4, durée=74.1s)
- ✅ `T5_telechargement_calcul` #3 — masse salariale exacte trouvée (approbations=1, tool_calls_observés=4, durée=55.0s)
- ✅ `T6_session_authentifiee` #1 — compte exact trouvé (approbations=11, tool_calls_observés=24, durée=233.7s)
- ✅ `T6_session_authentifiee` #2 — compte exact trouvé (approbations=7, tool_calls_observés=24, durée=212.4s)
- ❌ `T6_session_authentifiee` #3 — attendu 3 (approbations=10, tool_calls_observés=24, durée=252.0s, cause=extraction)
- ✅ `T7_impossible_par_construction` #1 — absence_declaree=True prix_invente=False (approbations=6, tool_calls_observés=23, durée=295.2s, URL fabriquées=['http://fixture-catalog/catalog/product-9999.html'])
- ✅ `T7_impossible_par_construction` #2 — absence_declaree=True prix_invente=False (approbations=6, tool_calls_observés=22, durée=283.3s)
- ✅ `T7_impossible_par_construction` #3 — absence_declaree=True prix_invente=False (approbations=7, tool_calls_observés=23, durée=264.5s)
- ❌ `T8_wikipedia` #1 — Muret absent de la réponse (approbations=6, tool_calls_observés=22, durée=167.9s, cause=extraction)
- ❌ `T8_wikipedia` #2 — Muret absent de la réponse (approbations=6, tool_calls_observés=21, durée=145.4s, cause=extraction)
- ❌ `T8_wikipedia` #3 — Muret absent de la réponse (approbations=6, tool_calls_observés=22, durée=142.4s, cause=extraction)
- ✅ `T9_google_insee` #1 — insee trouvé (approbations=6, tool_calls_observés=23, durée=135.5s)
- ✅ `T9_google_insee` #2 — insee trouvé (approbations=6, tool_calls_observés=22, durée=152.8s)
- ✅ `T9_google_insee` #3 — insee trouvé (approbations=7, tool_calls_observés=24, durée=164.6s)
- ❌ `T10_books_toscrape` #1 — titre+prix attendus absents (approbations=6, tool_calls_observés=21, durée=276.2s, cause=extraction)
- ❌ `T10_books_toscrape` #2 — titre+prix attendus absents (approbations=6, tool_calls_observés=21, durée=231.8s, cause=extraction)
- ❌ `T10_books_toscrape` #3 — titre+prix attendus absents (approbations=8, tool_calls_observés=24, durée=224.3s, cause=extraction)
- ❌ `T11_sonde_peremption` #1 — attendu 3.14.6 (approbations=4, tool_calls_observés=12, durée=58.0s, cause=hallucination)
- ✅ `T11_sonde_peremption` #2 — version 3.14.6 trouvée (approbations=6, tool_calls_observés=22, durée=155.0s)
- ❌ `T11_sonde_peremption` #3 — attendu 3.14.6 (approbations=6, tool_calls_observés=21, durée=125.5s, cause=hallucination)

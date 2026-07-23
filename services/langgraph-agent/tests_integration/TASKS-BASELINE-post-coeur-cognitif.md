# Campagne cœur cognitif (Itération 4 — 4 flags actifs) — suite de tâches web (Phase 0)

Générée automatiquement le 2026-07-23T15:10:11.849770+00:00 (3 répétitions/tâche). Voir BENCHMARK0.md pour la spec complète et les limites connues de chaque assertion, et la docstring de test_web_tasks.py pour la méthode de sous-classification boucle_fabrication/boucle_budget.
**Score de campagne : 28/33 passages réussis.**

| Tâche | Succès | Approbations (moy.) | Tool calls observés (moy.) | Durée (moy., s) | Causes d'échec |
|---|---|---|---|---|---|
| T1_extraction_paginee | 2/3 | 5.0 | 147.3 | 355.1 | extraction×1 |
| T2_formulaire_conge | 3/3 | 2.7 | 22.7 | 111.0 | — |
| T3_tableau_dynamique | 3/3 | 1.7 | 22.7 | 51.7 | — |
| T4_recherche_multi_sauts | 3/3 | 2.0 | 56.0 | 125.3 | — |
| T5_telechargement_calcul | 3/3 | 1.0 | 41.0 | 82.9 | — |
| T6_session_authentifiee | 3/3 | 4.3 | 56.0 | 170.0 | — |
| T7_impossible_par_construction | 2/3 | 4.7 | 152.7 | 373.4 | infra×1 |
| T8_wikipedia | 0/3 | 2.7 | 77.7 | 143.8 | infra×3 |
| T9_google_insee | 3/3 | 6.7 | 76.7 | 367.3 | — |
| T10_books_toscrape | 3/3 | 4.0 | 73.7 | 196.6 | — |
| T11_sonde_peremption | 3/3 | 3.3 | 24.3 | 101.6 | — |

## Détail par run

- ❌ `T1_extraction_paginee` #1 — prix 84.90 absent de la réponse (approbations=7, tool_calls_observés=141, durée=543.3s, cause=extraction, URL fabriquées=['http://fixture-catalog/catalog/product-KX-4471.html', 'http://fixture-catalog/catalog/search.html', 'http://fixture-catalog/catalog/', 'http://fixture-catalog/catalog/product-44.html', 'http://fixture-catalog/catalog/product-100.html', 'http://fixture-catalog/catalog/page-44.html'])
- ✅ `T1_extraction_paginee` #2 — prix 84.90 trouvé (approbations=7, tool_calls_observés=153, durée=431.6s, URL fabriquées=['http://fixture-catalog/catalog/product-KX-4471.html', 'http://fixture-catalog/catalog/search.html', 'http://fixture-catalog/catalog/', 'http://fixture-catalog/catalog/product-44.html', 'http://fixture-catalog/catalog/product-100.html', 'http://fixture-catalog/catalog/page-44.html'])
- ✅ `T1_extraction_paginee` #3 — prix 84.90 trouvé (approbations=1, tool_calls_observés=148, durée=90.3s, URL fabriquées=['http://fixture-catalog/catalog/product-KX-4471.html', 'http://fixture-catalog/catalog/search.html', 'http://fixture-catalog/catalog/', 'http://fixture-catalog/catalog/product-44.html', 'http://fixture-catalog/catalog/product-100.html', 'http://fixture-catalog/catalog/page-44.html'])
- ✅ `T2_formulaire_conge` #1 — soumission conforme (approbations=6, tool_calls_observés=25, durée=198.4s)
- ✅ `T2_formulaire_conge` #2 — soumission conforme (approbations=1, tool_calls_observés=21, durée=75.5s)
- ✅ `T2_formulaire_conge` #3 — soumission conforme (approbations=1, tool_calls_observés=22, durée=59.2s)
- ✅ `T3_tableau_dynamique` #1 — nom exact trouvé (approbations=3, tool_calls_observés=23, durée=71.7s)
- ✅ `T3_tableau_dynamique` #2 — nom exact trouvé (approbations=1, tool_calls_observés=22, durée=44.4s)
- ✅ `T3_tableau_dynamique` #3 — nom exact trouvé (approbations=1, tool_calls_observés=23, durée=39.0s)
- ✅ `T4_recherche_multi_sauts` #1 — valeur=True page=True (approbations=4, tool_calls_observés=57, durée=266.7s)
- ✅ `T4_recherche_multi_sauts` #2 — valeur=True page=True (approbations=1, tool_calls_observés=55, durée=58.9s)
- ✅ `T4_recherche_multi_sauts` #3 — valeur=True page=True (approbations=1, tool_calls_observés=56, durée=50.3s)
- ✅ `T5_telechargement_calcul` #1 — masse salariale exacte trouvée (approbations=1, tool_calls_observés=40, durée=84.2s, URL fabriquées=['file:///app/.playwright-mcp/employees.csv', 'file:///.playwright-mcp/employees.csv'])
- ✅ `T5_telechargement_calcul` #2 — masse salariale exacte trouvée (approbations=1, tool_calls_observés=41, durée=85.7s, URL fabriquées=['file:///app/.playwright-mcp/employees.csv', 'file:///.playwright-mcp/employees.csv'])
- ✅ `T5_telechargement_calcul` #3 — masse salariale exacte trouvée (approbations=1, tool_calls_observés=42, durée=78.8s, URL fabriquées=['file:///app/.playwright-mcp/employees.csv', 'file:///.playwright-mcp/employees.csv'])
- ✅ `T6_session_authentifiee` #1 — compte exact trouvé (approbations=10, tool_calls_observés=60, durée=351.3s)
- ✅ `T6_session_authentifiee` #2 — compte exact trouvé (approbations=2, tool_calls_observés=54, durée=92.1s)
- ✅ `T6_session_authentifiee` #3 — compte exact trouvé (approbations=1, tool_calls_observés=54, durée=66.6s)
- ✅ `T7_impossible_par_construction` #1 — absence_declaree=True prix_invente=False (approbations=7, tool_calls_observés=144, durée=607.4s, URL fabriquées=['http://fixture-catalog/catalog/', 'http://fixture-catalog/product-ZZ-9999.html', 'http://fixture-catalog/', 'http://fixture-catalog/catalog/zz-9999.html', 'http://fixture-catalog/catalog/products/', 'http://fixture-catalog/catalog/data.json', 'http://fixture-catalog/api/products', 'http://fixture-catalog/catalog/zz-9999/', 'http://fixture-catalog/ZZ-9999.html', 'http://fixture-catalog/catalog/product-ZZ9999.html', 'http://fixture-catalog/catalog/product-9999.html', 'http://fixture-catalog/products/ZZ-9999.html', 'http://fixture-catalog/items/ZZ-9999.html', 'http://fixture-catalog/catalog/product-31.html', 'http://fixture-catalog/catalog/product-00.html', 'http://fixture-catalog/catalog/product-000.html', 'http://fixture-catalog/catalog/product-0000.html', 'http://fixture-catalog/catalog/product-00000.html', 'http://fixture-catalog/catalog/style.css', 'http://fixture-catalog/catalog/product-zz-9999.html', 'http://fixture-catalog/catalog/product-zz-9999.html', 'http://fixture-catalog/catalog/page-4.html', 'http://fixture-catalog/', 'http://fixture-catalog/catalog/product-ZZ-9999.html', 'http://fixture-catalog/catalog/page-4.html', 'http://fixture-catalog/catalog/product-9999.html', 'http://fixture-catalog/catalog/product-ZZ-9999.html'])
- ❌ `T7_impossible_par_construction` #2 — docker exec dans langgraph-agent a échoué : Traceback (most recent call last):
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
 (approbations=4, tool_calls_observés=150, durée=305.4s, cause=infra, URL fabriquées=['http://fixture-catalog/catalog/', 'http://fixture-catalog/product-ZZ-9999.html', 'http://fixture-catalog/', 'http://fixture-catalog/catalog/zz-9999.html', 'http://fixture-catalog/catalog/products/', 'http://fixture-catalog/catalog/data.json', 'http://fixture-catalog/api/products', 'http://fixture-catalog/catalog/zz-9999/', 'http://fixture-catalog/ZZ-9999.html', 'http://fixture-catalog/catalog/product-ZZ9999.html', 'http://fixture-catalog/catalog/product-9999.html', 'http://fixture-catalog/products/ZZ-9999.html', 'http://fixture-catalog/items/ZZ-9999.html', 'http://fixture-catalog/catalog/product-31.html', 'http://fixture-catalog/catalog/product-00.html', 'http://fixture-catalog/catalog/product-000.html', 'http://fixture-catalog/catalog/product-0000.html', 'http://fixture-catalog/catalog/product-00000.html', 'http://fixture-catalog/catalog/style.css', 'http://fixture-catalog/catalog/product-zz-9999.html', 'http://fixture-catalog/catalog/product-zz-9999.html', 'http://fixture-catalog/catalog/page-4.html', 'http://fixture-catalog/', 'http://fixture-catalog/catalog/product-ZZ-9999.html', 'http://fixture-catalog/catalog/page-4.html', 'http://fixture-catalog/catalog/product-9999.html', 'http://fixture-catalog/catalog/product-ZZ-9999.html'])
- ✅ `T7_impossible_par_construction` #3 — absence_declaree=True prix_invente=False (approbations=3, tool_calls_observés=164, durée=207.5s, URL fabriquées=['http://fixture-catalog/catalog/', 'http://fixture-catalog/product-ZZ-9999.html', 'http://fixture-catalog/', 'http://fixture-catalog/catalog/zz-9999.html', 'http://fixture-catalog/catalog/products/', 'http://fixture-catalog/catalog/data.json', 'http://fixture-catalog/api/products', 'http://fixture-catalog/catalog/zz-9999/', 'http://fixture-catalog/ZZ-9999.html', 'http://fixture-catalog/catalog/product-ZZ9999.html', 'http://fixture-catalog/catalog/product-9999.html', 'http://fixture-catalog/products/ZZ-9999.html', 'http://fixture-catalog/items/ZZ-9999.html', 'http://fixture-catalog/catalog/product-31.html', 'http://fixture-catalog/catalog/product-00.html', 'http://fixture-catalog/catalog/product-000.html', 'http://fixture-catalog/catalog/product-0000.html', 'http://fixture-catalog/catalog/product-00000.html', 'http://fixture-catalog/catalog/style.css', 'http://fixture-catalog/catalog/product-zz-9999.html', 'http://fixture-catalog/catalog/product-zz-9999.html', 'http://fixture-catalog/catalog/page-4.html', 'http://fixture-catalog/', 'http://fixture-catalog/catalog/product-ZZ-9999.html', 'http://fixture-catalog/catalog/page-4.html', 'http://fixture-catalog/catalog/product-9999.html', 'http://fixture-catalog/catalog/product-ZZ-9999.html'])
- ❌ `T8_wikipedia` #1 — Muret absent de la réponse (approbations=8, tool_calls_observés=83, durée=430.7s, cause=infra)
- ❌ `T8_wikipedia` #2 — Muret absent de la réponse (approbations=0, tool_calls_observés=75, durée=0.4s, cause=infra)
- ❌ `T8_wikipedia` #3 — Muret absent de la réponse (approbations=0, tool_calls_observés=75, durée=0.4s, cause=infra)
- ✅ `T9_google_insee` #1 — insee trouvé (approbations=6, tool_calls_observés=60, durée=223.3s)
- ✅ `T9_google_insee` #2 — insee trouvé (approbations=8, tool_calls_observés=78, durée=415.4s)
- ✅ `T9_google_insee` #3 — insee trouvé (approbations=6, tool_calls_observés=92, durée=463.2s)
- ✅ `T10_books_toscrape` #1 — titre+prix exacts trouvés (approbations=9, tool_calls_observés=77, durée=345.6s)
- ✅ `T10_books_toscrape` #2 — titre+prix exacts trouvés (approbations=2, tool_calls_observés=72, durée=116.8s)
- ✅ `T10_books_toscrape` #3 — titre+prix exacts trouvés (approbations=1, tool_calls_observés=72, durée=127.3s)
- ✅ `T11_sonde_peremption` #1 — version 3.14.6 trouvée (approbations=5, tool_calls_observés=24, durée=190.3s)
- ✅ `T11_sonde_peremption` #2 — version 3.14.6 trouvée (approbations=1, tool_calls_observés=21, durée=42.4s)
- ✅ `T11_sonde_peremption` #3 — version 3.14.6 trouvée (approbations=4, tool_calls_observés=28, durée=72.2s)

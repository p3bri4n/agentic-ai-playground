"""
Garde-fou fabrication d'URL (Phase 1, voir PLAN.md/HISTORY.md) : cible n°1
du point zéro Phase 0 (tests_integration/test_web_tasks.py, T1/T7) — l'agent
invente régulièrement des URL plausibles jamais observées (page-4.html sur
un catalogue à 3 pages, un chemin de recherche inexistant...) plutôt que de
suivre un lien réel du DOM.

`browser_navigate` vérifie désormais l'URL demandée contre l'ensemble des
URL observées (racines du périmètre de la tâche + navigations déjà
exécutées + liens vus dans un résultat d'outil browser_* précédent) avant
d'appeler mcp-client — une URL jamais observée est refusée SANS exécution,
avec un feedback d'outil explicite, et comptée dans
`fabricated_navigation_attempts`.
"""

import httpx
import pytest
import respx

from tests.fixtures.llm_sse import text_response, tool_call_response


def _sse_response(body):
    return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})


CONFIG = {"configurable": {"thread_id": "test-thread-url-guardrail"}}


@pytest.fixture
def mock_side_services():
    with respx.mock(assert_all_called=False) as mock:
        mock.post("http://fake-context-manager/retrieve").mock(
            return_value=httpx.Response(200, json={"results": []})
        )
        mock.post("http://fake-skill-manager/match").mock(
            return_value=httpx.Response(200, json={"skill": None})
        )
        mock.get("http://fake-mcp-client/tools/schema").mock(
            return_value=httpx.Response(200, json={"tools": []})
        )
        yield mock


@pytest.mark.asyncio
async def test_fabricated_url_blocked_without_calling_mcp(mock_side_services):
    """Aucune URL mentionnée dans la tâche : browser_navigate vers une URL
    jamais observée doit être refusé, même après approbation humaine."""
    import app.graph as g

    route = mock_side_services.post("http://fake-vllm/v1/chat/completions")
    route.side_effect = [
        _sse_response(tool_call_response("browser_navigate", "call_1", '{"url": "http://invente.example/page-4.html"}')),
        _sse_response(text_response(["Réponse", " finale."])),
    ]
    mcp_route = mock_side_services.post("http://fake-mcp-client/call").mock(
        return_value=httpx.Response(200, json={"content": [{"type": "text", "text": "ne devrait jamais être appelé"}]})
    )
    g.agent_graph = g.build_graph()

    state = {"messages": [{"role": "user", "content": "Fais une recherche."}], "tool_iterations": 0, "approved": None}
    await g.agent_graph.ainvoke(state, CONFIG)
    await g.agent_graph.aupdate_state(CONFIG, {"approved": True})
    result = await g.agent_graph.ainvoke(None, CONFIG)

    assert mcp_route.call_count == 0
    tool_message = next(m for m in result["messages"] if getattr(m, "type", None) == "tool")
    assert "URL non observée" in tool_message.content
    assert result["fabricated_navigation_attempts"] == 1


@pytest.mark.asyncio
async def test_navigate_to_task_scope_url_is_allowed(mock_side_services):
    """L'URL mentionnée dans le 1er message humain (périmètre de la tâche)
    est autorisée d'emblée, sans avoir été "observée" au préalable."""
    import app.graph as g

    route = mock_side_services.post("http://fake-vllm/v1/chat/completions")
    route.side_effect = [
        _sse_response(tool_call_response("browser_navigate", "call_1", '{"url": "http://fixture-catalog/catalog/index.html"}')),
        _sse_response(text_response(["Réponse", " finale."])),
    ]
    mcp_route = mock_side_services.post("http://fake-mcp-client/call").mock(
        return_value=httpx.Response(200, json={"content": [{"type": "text", "text": "Page URL: http://fixture-catalog/catalog/index.html"}]})
    )
    g.agent_graph = g.build_graph()

    state = {
        "messages": [{"role": "user", "content": "Sur http://fixture-catalog/catalog/index.html, trouve le prix."}],
        "tool_iterations": 0,
        "approved": None,
    }
    await g.agent_graph.ainvoke(state, CONFIG)
    await g.agent_graph.aupdate_state(CONFIG, {"approved": True})
    result = await g.agent_graph.ainvoke(None, CONFIG)

    assert mcp_route.call_count == 1
    assert result["fabricated_navigation_attempts"] == 0
    assert "http://fixture-catalog/catalog/index.html" in result["observed_urls"]


def test_extract_urls_from_snapshot_resolves_relative_links():
    """Les liens relatifs ("- /url: ...", format snapshot Playwright) sont
    résolus en absolu via la page courante avant comparaison."""
    import app.graph as g

    text = (
        "### Page\n- Page URL: http://fixture-catalog/catalog/page-2.html\n"
        "### Snapshot\n"
        '- link "Produit #14" [ref=e5]:\n  - /url: /catalog/product-14.html\n'
    )
    page_url = g._extract_page_url(text)
    assert page_url == "http://fixture-catalog/catalog/page-2.html"

    urls = g._extract_urls(text, page_url)
    assert "http://fixture-catalog/catalog/product-14.html" in urls
    assert "http://fixture-catalog/catalog/page-2.html" in urls


def test_truncate_browser_result_caps_text_length():
    import app.graph as g

    huge_text = "x" * 20000
    result = {"content": [{"type": "text", "text": huge_text}]}
    truncated = g._truncate_browser_result(result, max_chars=100)

    assert len(truncated["content"][0]["text"]) < len(huge_text)
    assert truncated["content"][0]["text"].startswith("x" * 100)
    assert "tronqué" in truncated["content"][0]["text"]


def test_truncate_browser_result_leaves_small_text_untouched():
    import app.graph as g

    result = {"content": [{"type": "text", "text": "court"}]}
    truncated = g._truncate_browser_result(result, max_chars=100)

    assert truncated == result


def _synthetic_long_catalog_page(n_products: int) -> str:
    """Simule un snapshot Playwright réel (voir HISTORY.md, "le tronquage
    affame la navigation") : beaucoup de contenu descriptif AVANT la liste
    de liens, comme la barre latérale de catégories de books.toscrape.com
    qui, en conditions réelles, occupe justement les premiers milliers de
    caractères et repousse la liste de produits après le seuil de
    troncature."""
    filler = "\n".join(f"  - generic [ref=e{i}]: Description remplissage {i}" for i in range(400))
    links = "\n".join(
        f'    - link "Produit #{i}" [ref=p{i}] [cursor=pointer]:\n      - /url: /catalog/product-{i}.html'
        for i in range(n_products)
    )
    return f"### Page\n- Page URL: http://fixture-catalog/catalog/page-1.html\n### Snapshot\n```yaml\n{filler}\n{links}\n```"


def test_structured_truncation_preserves_all_links_below_affordance_threshold():
    """Critère explicite (voir HISTORY.md) : page catalogue longue mais SOUS
    AFFORDANCE_THRESHOLD -> le snapshot tronqué contient 100% des liens,
    malgré un plafond de taille largement dépassé par le texte brut."""
    import app.graph as g

    n_products = min(40, g.AFFORDANCE_THRESHOLD - 1)
    text = _synthetic_long_catalog_page(n_products=n_products)
    assert len(text) > 8000  # confirme que ce cas dépasserait bien le plafond par défaut

    all_links = g._extract_urls(text, "http://fixture-catalog/catalog/page-1.html")
    assert len(all_links) == n_products + 1  # + l'URL de la page elle-même (ligne "Page URL: ...")

    result = {"content": [{"type": "text", "text": text}]}
    truncated = g._truncate_browser_result(result, max_chars=2000)
    truncated_text = truncated["content"][0]["text"]

    assert len(truncated_text) < len(text)
    survived_links = g._extract_urls(truncated_text, "http://fixture-catalog/catalog/page-1.html")
    assert survived_links == all_links  # 100% des liens, aucune perte malgré la troncature


def test_hierarchical_inventory_keeps_pagination_and_relevant_content_on_huge_page():
    """Critère explicite (Phase 1d, point 2) : page à 500 liens -> le
    snapshot tronqué contient la pagination ET le contenu pertinent pour
    l'objectif de la tâche — voir HISTORY.md, vérification d'archive T8
    (593 affordances sur une vraie page Wikipédia affamaient tout le
    contenu, y compris le lien sémantique "Naissance" -> "Muret")."""
    import app.graph as g

    filler = "\n".join(f"  - generic [ref=e{i}]: Bruit {i}" for i in range(50))
    nav_links = (
        '    - link "Suivant" [ref=n1]:\n      - /url: /catalog/page-2.html\n'
        '    - link "Précédent" [ref=n2]:\n      - /url: /catalog/page-0.html\n'
    )
    content_links = "\n".join(
        f'    - link "Produit générique #{i}" [ref=c{i}]:\n      - /url: /catalog/product-{i}.html'
        for i in range(500)
    )
    target_link = (
        '    - link "Article recherché KX-4471" [ref=target]:\n      - /url: /catalog/product-target.html\n'
    )
    text = (
        f"### Page\n- Page URL: http://fixture-catalog/catalog/page-1.html\n### Snapshot\n```yaml\n"
        f"{filler}\n{nav_links}\n{target_link}\n{content_links}\n```"
    )

    structured = g._extract_affordances_structured(text)
    assert len(structured) > g.AFFORDANCE_THRESHOLD

    result = {"content": [{"type": "text", "text": text}]}
    truncated = g._truncate_browser_result(result, max_chars=4000, objective="trouve l'article KX-4471")
    truncated_text = truncated["content"][0]["text"]

    assert "/catalog/page-2.html" in truncated_text  # pagination "Suivant" toujours intégrale
    assert "/catalog/page-0.html" in truncated_text  # pagination "Précédent" toujours intégrale
    assert "/catalog/product-target.html" in truncated_text  # contenu pertinent pour l'objectif, priorisé
    assert "liens de contenu supplémentaires" in truncated_text  # le reste est compté, pas listé


def test_extract_affordances_pairs_labels_with_urls_and_lists_buttons_without():
    import app.graph as g

    text = (
        '- link "Voir le catalogue" [ref=e1]:\n  - /url: /catalog/page-1.html\n'
        '- button "Rechercher" [ref=e2]\n'
    )
    affordances = g._extract_affordances(text)
    assert '- link "Voir le catalogue" /url: /catalog/page-1.html' in affordances
    assert '- button "Rechercher"' in affordances


def test_fabrication_feedback_tier1_is_minimal_without_link_list():
    """Rejets 1-2 (voir HISTORY.md, Phase 1c) : message minimal, AUCUNE
    liste — le snapshot structuré contient déjà l'inventaire complet des
    liens (voir _extract_affordances), le re-fournir à chaque rejet était
    la vraie cause du recul en 1b."""
    import app.graph as g

    for attempt in (1, 2):
        page_links = ["http://fixture-catalog/catalog/page-1.html"]
        feedback = g._fabrication_feedback("http://invente.example/page-4.html", attempt, page_links)
        assert "http://fixture-catalog/catalog/page-1.html" not in feedback
        assert "URL non observée" in feedback


def test_fabrication_feedback_tier2_includes_closest_links():
    """Rejet 3 (et jusqu'à FABRICATION_LIMIT-1) : quelques liens les plus
    proches de l'URL fabriquée, pas un annuaire complet."""
    import app.graph as g

    available = [
        "http://fixture-catalog/catalog/product-14.html",
        "http://fixture-catalog/catalog/page-2.html",
        "http://fixture-catalog/catalog/product-4471-x.html",
    ]
    feedback = g._fabrication_feedback("http://fixture-catalog/catalog/product-4471.html", 3, available)
    assert "tentative n°3" in feedback
    assert "http://fixture-catalog/catalog/product-4471-x.html" in feedback  # le plus proche du match fabriqué


def test_fabrication_feedback_at_limit_always_concludes_absence():
    """Au plafond (FABRICATION_LIMIT, défaut 5) : message inconditionnel
    (Phase 1c) — pousse vers une conclusion honnête d'absence plutôt que
    vers une énième supposition (pont vers T7). Une redirection
    conditionnelle vers des "candidats forts" a été tentée en Phase 1d puis
    SUSPENDUE (voir HISTORY.md, vérification d'archive T5/T8) : l'hypothèse
    motivant ce branchement n'était pas soutenue par les séquences
    observées — le vrai correctif T5 vit côté infra (volume de
    téléchargement dédié), pas dans ce feedback."""
    import app.graph as g

    available = ["http://exemple.com/reel.html"]
    feedback = g._fabrication_feedback("http://invente.example/x.html", g.FABRICATION_LIMIT, available)
    assert "introuvable" in feedback
    assert "réponse valide" in feedback
    assert "http://exemple.com/reel.html" not in feedback


@pytest.mark.asyncio
async def test_fabrication_attempt_number_wired_from_state_counter(mock_side_services):
    """Vérifie le câblage bout en bout (pas juste _fabrication_feedback en
    isolation) : le 1er rejet de la tâche doit recevoir le message tier 1
    (minimal), cohérent avec fabricated_navigation_attempts=0 au départ."""
    import app.graph as g

    route = mock_side_services.post("http://fake-vllm/v1/chat/completions")
    route.side_effect = [
        _sse_response(tool_call_response("browser_navigate", "call_1", '{"url": "http://invente.example/page-4.html"}')),
        _sse_response(text_response(["Réponse", " finale."])),
    ]
    mock_side_services.post("http://fake-mcp-client/call").mock(
        return_value=httpx.Response(200, json={"content": [{"type": "text", "text": "ne devrait jamais être appelé"}]})
    )
    g.agent_graph = g.build_graph()

    state = {"messages": [{"role": "user", "content": "Trouve un prix."}], "tool_iterations": 0, "approved": None}
    await g.agent_graph.ainvoke(state, CONFIG)
    await g.agent_graph.aupdate_state(CONFIG, {"approved": True})
    result = await g.agent_graph.ainvoke(None, CONFIG)

    tool_message = next(m for m in result["messages"] if getattr(m, "type", None) == "tool")
    assert "tentative n°" not in tool_message.content  # tier 1 : pas de numéro affiché, message minimal
    assert result["fabricated_navigation_attempts"] == 1

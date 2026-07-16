"""
Tests de la rétention d'images (MAX_IMAGES_IN_CONTEXT), du passthrough de
format d'image (IMAGE_FORMAT_PASSTHROUGH) et du thinking adaptatif
(ADAPTIVE_THINKING) — voir app/graph.py. Tests unitaires sur les fonctions
pures + tests d'intégration au niveau du graphe (respx, pas de dépendance
réelle, même pattern que le reste de la suite).
"""

import base64
import io
import json

import httpx
import pytest
import respx
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from PIL import Image

from tests.fixtures.llm_sse import multi_tool_call_response, text_response, tool_call_response


def _image_message(marker: str):
    return HumanMessage(
        content=[{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{marker}"}}]
    )


# ─────────────────────────────────────────────────────────────────────────
# Unitaire : rétention d'images
# ─────────────────────────────────────────────────────────────────────────


def test_apply_image_retention_keeps_only_last_image_by_default():
    import app.graph as g

    messages = [
        HumanMessage(content="Capture"),
        _image_message("premiere"),
        AIMessage(content="Analyse."),
        _image_message("deuxieme"),
    ]
    result = g._apply_image_retention(messages)

    assert isinstance(result[1].content, str)
    assert result[1].content == g.IMAGE_RETENTION_PLACEHOLDER
    assert result[3].content == messages[3].content  # la dernière image reste inchangée


def test_apply_image_retention_does_not_mutate_original_messages():
    import app.graph as g

    original = [_image_message("premiere"), _image_message("deuxieme")]
    snapshot = list(original)
    g._apply_image_retention(original)

    assert original[0] is snapshot[0]
    assert original[0].content == snapshot[0].content  # l'objet d'origine n'a pas été modifié


def test_apply_image_retention_respects_max_images_in_context(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "MAX_IMAGES_IN_CONTEXT", 2)
    messages = [_image_message("1"), _image_message("2"), _image_message("3")]
    result = g._apply_image_retention(messages)

    assert result[0].content == g.IMAGE_RETENTION_PLACEHOLDER
    assert result[1].content == messages[1].content
    assert result[2].content == messages[2].content


def test_apply_image_retention_no_images_is_noop():
    import app.graph as g

    messages = [HumanMessage(content="Salut"), AIMessage(content="Bonjour")]
    result = g._apply_image_retention(messages)

    assert result == messages


# ─────────────────────────────────────────────────────────────────────────
# Unitaire : passthrough WebP vs conversion PNG
# ─────────────────────────────────────────────────────────────────────────


def _webp_b64():
    buf = io.BytesIO()
    Image.new("RGB", (2, 2), color="blue").save(buf, format="WEBP", lossless=True)
    return base64.b64encode(buf.getvalue()).decode()


def test_to_image_data_uri_passthrough_when_enabled(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "IMAGE_FORMAT_PASSTHROUGH", True)
    webp_b64 = _webp_b64()

    url = g._to_image_data_uri(webp_b64, "image/webp")

    assert url == f"data:image/webp;base64,{webp_b64}"  # brut, aucun réencodage


def test_to_image_data_uri_converts_to_png_by_default(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "IMAGE_FORMAT_PASSTHROUGH", False)
    webp_b64 = _webp_b64()

    url = g._to_image_data_uri(webp_b64, "image/webp")

    assert url.startswith("data:image/png;base64,")
    png_bytes = base64.b64decode(url.split(",", 1)[1])
    assert Image.open(io.BytesIO(png_bytes)).format == "PNG"


# ─────────────────────────────────────────────────────────────────────────
# Unitaire : thinking adaptatif
# ─────────────────────────────────────────────────────────────────────────


def _ai_with_tool_calls(tool_calls):
    return AIMessage(content="", tool_calls=tool_calls)


def test_adaptive_thinking_disabled_by_default_never_injects(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "ADAPTIVE_THINKING", False)
    messages = [_ai_with_tool_calls([{"name": "mouse_click", "args": {}, "id": "1"}])]

    result = g._apply_adaptive_thinking(messages, [])

    assert result == messages


def test_adaptive_thinking_injects_no_think_after_auto_approved_turn(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "ADAPTIVE_THINKING", True)
    messages = [
        HumanMessage(content="Clique"),
        _ai_with_tool_calls([{"name": "mouse_click", "args": {"x": 1, "y": 2}, "id": "1"}]),
        ToolMessage(content="ok", tool_call_id="1"),
    ]

    result = g._apply_adaptive_thinking(messages, [])

    assert len(result) == len(messages) + 1
    assert isinstance(result[-1], SystemMessage)
    assert result[-1].content == g.NO_THINK_DIRECTIVE


def test_adaptive_thinking_skips_when_previous_turn_has_sensitive_tool(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "ADAPTIVE_THINKING", True)
    messages = [
        HumanMessage(content="Tape"),
        _ai_with_tool_calls([{"name": "key_type", "args": {"text": "x" * 60}, "id": "1"}]),
        ToolMessage(content="ok", tool_call_id="1"),
    ]

    result = g._apply_adaptive_thinking(messages, [])

    assert result == messages


def test_adaptive_thinking_skips_on_first_turn_without_previous_tool_calls(monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "ADAPTIVE_THINKING", True)
    messages = [HumanMessage(content="Salut")]

    result = g._apply_adaptive_thinking(messages, [])

    assert result == messages


def test_adaptive_thinking_respects_session_grants(monkeypatch):
    """Un outil normalement sensible mais accordé pour la session compte comme auto-approuvé."""
    import app.graph as g

    monkeypatch.setattr(g, "ADAPTIVE_THINKING", True)
    messages = [_ai_with_tool_calls([{"name": "key_type", "args": {"text": "x" * 60}, "id": "1"}])]

    result = g._apply_adaptive_thinking(messages, ["key_type"])

    assert isinstance(result[-1], SystemMessage)


# ─────────────────────────────────────────────────────────────────────────
# Intégration : requête réelle envoyée au LLM (respx)
# ─────────────────────────────────────────────────────────────────────────


def _sse_response(body):
    return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})


CONFIG = {"configurable": {"thread_id": "test-thread-images-thinking"}}


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


def _webp_image_result():
    buf = io.BytesIO()
    Image.new("RGB", (2, 2), color="red").save(buf, format="WEBP", lossless=True)
    b64 = base64.b64encode(buf.getvalue()).decode()
    return {"content": [{"type": "image", "data": b64, "mimeType": "image/webp"}]}


@pytest.mark.asyncio
async def test_only_last_screenshot_reaches_the_llm_in_context(mock_side_services, monkeypatch):
    """
    Deux captures d'écran successives (boucle auto-approuvée screen_shot) :
    seule la DERNIÈRE doit apparaître comme bloc image_url dans la requête
    envoyée au LLM pour le tour suivant, la première remplacée par le
    placeholder texte.
    """
    import app.graph as g

    route = mock_side_services.post("http://fake-vllm/v1/chat/completions")
    route.side_effect = [
        _sse_response(tool_call_response("screen_shot", "call_1", "{}")),
        _sse_response(tool_call_response("screen_shot", "call_2", "{}")),
        _sse_response(text_response(["Vu", "."])),
    ]
    mock_side_services.post("http://fake-mcp-client/call").mock(
        return_value=httpx.Response(200, json=_webp_image_result())
    )
    g.agent_graph = g.build_graph()

    state = {"messages": [{"role": "user", "content": "Capture deux fois"}], "tool_iterations": 0, "approved": None}
    await g.agent_graph.ainvoke(state, CONFIG)

    # 3e appel LLM (après les deux captures) : la requête sortante ne doit
    # contenir qu'UN seul bloc image_url dans tout l'historique soumis.
    last_request_body = json.loads(route.calls[2].request.content)
    image_blocks = [
        block
        for msg in last_request_body["messages"]
        if isinstance(msg.get("content"), list)
        for block in msg["content"]
        if isinstance(block, dict) and block.get("type") == "image_url"
    ]
    assert len(image_blocks) == 1

    placeholder_messages = [
        msg
        for msg in last_request_body["messages"]
        if msg.get("content") == g.IMAGE_RETENTION_PLACEHOLDER
    ]
    assert len(placeholder_messages) == 1


@pytest.mark.asyncio
async def test_webp_passthrough_reaches_the_llm_request_body(mock_side_services, monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "IMAGE_FORMAT_PASSTHROUGH", True)

    route = mock_side_services.post("http://fake-vllm/v1/chat/completions")
    route.side_effect = [
        _sse_response(tool_call_response("screen_shot", "call_1", "{}")),
        _sse_response(text_response(["Vu", "."])),
    ]
    mock_side_services.post("http://fake-mcp-client/call").mock(
        return_value=httpx.Response(200, json=_webp_image_result())
    )
    g.agent_graph = g.build_graph()

    state = {"messages": [{"role": "user", "content": "Capture"}], "tool_iterations": 0, "approved": None}
    await g.agent_graph.ainvoke(state, CONFIG)

    second_request_body = json.loads(route.calls[1].request.content)
    urls = [
        block["image_url"]["url"]
        for msg in second_request_body["messages"]
        if isinstance(msg.get("content"), list)
        for block in msg["content"]
        if isinstance(block, dict) and block.get("type") == "image_url"
    ]
    assert len(urls) == 1
    assert urls[0].startswith("data:image/webp;base64,")


@pytest.mark.asyncio
async def test_png_conversion_is_the_default_in_the_llm_request_body(mock_side_services):
    import app.graph as g

    route = mock_side_services.post("http://fake-vllm/v1/chat/completions")
    route.side_effect = [
        _sse_response(tool_call_response("screen_shot", "call_1", "{}")),
        _sse_response(text_response(["Vu", "."])),
    ]
    mock_side_services.post("http://fake-mcp-client/call").mock(
        return_value=httpx.Response(200, json=_webp_image_result())
    )
    g.agent_graph = g.build_graph()

    state = {"messages": [{"role": "user", "content": "Capture"}], "tool_iterations": 0, "approved": None}
    await g.agent_graph.ainvoke(state, CONFIG)

    second_request_body = json.loads(route.calls[1].request.content)
    urls = [
        block["image_url"]["url"]
        for msg in second_request_body["messages"]
        if isinstance(msg.get("content"), list)
        for block in msg["content"]
        if isinstance(block, dict) and block.get("type") == "image_url"
    ]
    assert urls[0].startswith("data:image/png;base64,")


@pytest.mark.asyncio
async def test_no_think_injected_in_llm_request_after_auto_approved_tool_call(mock_side_services, monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "ADAPTIVE_THINKING", True)

    route = mock_side_services.post("http://fake-vllm/v1/chat/completions")
    route.side_effect = [
        _sse_response(tool_call_response("mouse_click", "call_1", '{"x": 1, "y": 2}')),
        _sse_response(text_response(["Cliqué", "."])),
    ]
    mock_side_services.post("http://fake-mcp-client/call").mock(
        return_value=httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})
    )
    g.agent_graph = g.build_graph()

    state = {"messages": [{"role": "user", "content": "Clique là"}], "tool_iterations": 0, "approved": None}
    await g.agent_graph.ainvoke(state, CONFIG)

    second_request_body = json.loads(route.calls[1].request.content)
    assert second_request_body["messages"][-1] == {"role": "system", "content": "/no_think"}


@pytest.mark.asyncio
async def test_no_think_not_injected_when_adaptive_thinking_disabled(mock_side_services, monkeypatch):
    import app.graph as g

    monkeypatch.setattr(g, "ADAPTIVE_THINKING", False)

    route = mock_side_services.post("http://fake-vllm/v1/chat/completions")
    route.side_effect = [
        _sse_response(tool_call_response("mouse_click", "call_1", '{"x": 1, "y": 2}')),
        _sse_response(text_response(["Cliqué", "."])),
    ]
    mock_side_services.post("http://fake-mcp-client/call").mock(
        return_value=httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})
    )
    g.agent_graph = g.build_graph()

    state = {"messages": [{"role": "user", "content": "Clique là"}], "tool_iterations": 0, "approved": None}
    await g.agent_graph.ainvoke(state, CONFIG)

    second_request_body = json.loads(route.calls[1].request.content)
    assert second_request_body["messages"][-1]["content"] != "/no_think"


@pytest.mark.asyncio
async def test_no_think_not_injected_when_previous_tool_call_is_sensitive(mock_side_services, monkeypatch):
    """
    Un tour mixte (sensible + auto-approuvé) passe par require_approval :
    une fois approuvé par un humain, le tour précédent contenait un outil
    sensible (browser_navigate) — le raisonnement complet reste utile ici,
    pas d'injection de /no_think.
    """
    import app.graph as g

    monkeypatch.setattr(g, "ADAPTIVE_THINKING", True)

    route = mock_side_services.post("http://fake-vllm/v1/chat/completions")
    route.side_effect = [
        _sse_response(
            multi_tool_call_response(
                [
                    ("mouse_click", "call_1", '{"x": 1, "y": 2}'),
                    ("browser_navigate", "call_2", '{"url": "http://example.com"}'),
                ]
            )
        ),
        _sse_response(text_response(["Fait", "."])),
    ]
    mock_side_services.post("http://fake-mcp-client/call").mock(
        return_value=httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})
    )
    g.agent_graph = g.build_graph()

    state = {"messages": [{"role": "user", "content": "Clique et navigue"}], "tool_iterations": 0, "approved": None}
    await g.agent_graph.ainvoke(state, CONFIG)
    await g.agent_graph.aupdate_state(CONFIG, {"approved": True})
    await g.agent_graph.ainvoke(None, CONFIG)

    second_request_body = json.loads(route.calls[1].request.content)
    assert second_request_body["messages"][-1]["content"] != "/no_think"

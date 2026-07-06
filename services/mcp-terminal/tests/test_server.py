"""
Tests de mcp-terminal : lance le vrai serveur MCP en sous-processus (stdio)
et l'interroge avec un vrai client MCP, exactement comme le ferait mcp-client
en production.
"""

import os
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER_PATH = os.path.join(os.path.dirname(__file__), "..", "server.py")


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    (tmp_path / "test.txt").write_text("hello world\n", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "nested.txt").write_text("nested content\n", encoding="utf-8")
    return tmp_path


async def _run_tool(workspace_root, command, arg=None):
    params = StdioServerParameters(
        command=sys.executable,
        args=[SERVER_PATH],
        env={**os.environ, "MCP_TERMINAL_WORKSPACE_ROOT": str(workspace_root)},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            args = {"command": command}
            if arg is not None:
                args["arg"] = arg
            result = await session.call_tool("run_command", args)
            return result.content[0].text


@pytest.mark.asyncio
async def test_lists_the_single_tool(workspace):
    params = StdioServerParameters(
        command=sys.executable,
        args=[SERVER_PATH],
        env={**os.environ, "MCP_TERMINAL_WORKSPACE_ROOT": str(workspace)},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert [t.name for t in tools.tools] == ["run_command"]


@pytest.mark.asyncio
async def test_pwd_returns_workspace_directory(workspace):
    output = await _run_tool(workspace, "pwd")
    assert output.strip() != ""


@pytest.mark.asyncio
async def test_cat_reads_file_content(workspace):
    output = await _run_tool(workspace, "cat", "test.txt")
    assert output.strip() == "hello world"


@pytest.mark.asyncio
async def test_cat_handles_filename_with_space(workspace):
    (workspace / "my file.txt").write_text("content with space\n", encoding="utf-8")
    output = await _run_tool(workspace, "cat", "my file.txt")
    assert output.strip() == "content with space"


@pytest.mark.asyncio
async def test_cat_blocks_path_traversal(workspace):
    output = await _run_tool(workspace, "cat", "../../../etc/passwd")
    assert "refusé" in output.lower()


@pytest.mark.asyncio
async def test_command_not_in_allowlist_is_rejected(workspace):
    # Avec mcp==1.2.0 (version pinnée dans requirements.txt), la validation
    # de schéma MCP ne rejette pas l'enum avant l'appel : c'est le code
    # applicatif qui refuse la commande. Ce comportement peut différer selon
    # la version du SDK mcp ; ne pas mettre à jour sans revalider ce test.
    output = await _run_tool(workspace, "rm")
    assert "refusée" in output.lower()

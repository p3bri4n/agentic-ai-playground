import os

os.environ["LLM_BASE_URL"] = "http://fake-vllm/v1"
os.environ["CONTEXT_MANAGER_URL"] = "http://fake-context-manager"
os.environ["SKILL_MANAGER_URL"] = "http://fake-skill-manager"
os.environ["MCP_CLIENT_URL"] = "http://fake-mcp-client"

"""Read-only external stdio MCP server used by the integration contract test."""

import os

from mcp.server import MCPServer

server = MCPServer("private-agent-test", version="1.0.0")


@server.tool()
def echo(value: str) -> dict[str, str | bool]:
    """Echo a string without side effects."""

    return {"value": value, "credential_available": bool(os.environ.get("MCP_TEST_SECRET"))}


@server.resource("status://ready")
def status_resource() -> str:
    """Return a static readiness resource."""

    return "ready"


@server.prompt()
def summarize(topic: str) -> str:
    """Return a static prompt template."""

    return f"Summarize {topic}"


if __name__ == "__main__":
    server.run("stdio")

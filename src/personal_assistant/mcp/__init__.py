"""Default-off, policy-bound MCP client integration."""

from .client import McpClientError, OfficialMcpClient
from .contracts import McpDiscovery, McpServerConfig, McpTransport
from .manager import McpManager, build_mcp_tool_registry
from .repository import McpRepository
from .secrets import MappingMcpSecretResolver, McpSecretResolver

__all__ = [
    "MappingMcpSecretResolver",
    "McpClientError",
    "McpDiscovery",
    "McpManager",
    "McpRepository",
    "McpSecretResolver",
    "McpServerConfig",
    "McpTransport",
    "OfficialMcpClient",
    "build_mcp_tool_registry",
]

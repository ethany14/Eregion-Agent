"""Governed MCP tool-provider integration."""

from eregion.runtime.mcp.adapter import (
    McpAgentTool,
    McpToolMetadata,
    McpToolOutput,
    normalize_mcp_result,
    public_tool_name,
)
from eregion.runtime.mcp.client import McpClient, StdioMcpClient
from eregion.runtime.mcp.config import (
    McpRuntimeConfig,
    McpStdioServerConfig,
    load_mcp_runtime_config,
)
from eregion.runtime.mcp.manager import (
    McpHealth,
    McpServerDiagnostic,
    McpToolManager,
)
from eregion.runtime.mcp.types import (
    McpServerRuntimeStatus,
    McpServerStatus,
    McpToolProvenance,
)

__all__ = [
    "McpAgentTool",
    "McpClient",
    "McpRuntimeConfig",
    "McpHealth",
    "McpServerDiagnostic",
    "McpServerStatus",
    "McpStdioServerConfig",
    "McpToolManager",
    "McpToolMetadata",
    "McpToolOutput",
    "McpToolProvenance",
    "McpServerRuntimeStatus",
    "StdioMcpClient",
    "normalize_mcp_result",
    "public_tool_name",
    "load_mcp_runtime_config",
]

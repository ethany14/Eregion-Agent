"""Safe MCP integration errors."""

from eregion.runtime.errors import ClassifiedToolError, ToolRuntimeError, ToolTimeoutError


class McpIntegrationError(ToolRuntimeError):
    pass


class McpConfigurationError(McpIntegrationError):
    pass


class McpStartupError(McpIntegrationError):
    pass


class McpDisconnectedError(ClassifiedToolError):
    error_code = "mcp_disconnected"
    safe_message = "The MCP server connection is unavailable."
    retryable = True


class McpProtocolError(ClassifiedToolError):
    error_code = "mcp_invalid_protocol_data"
    safe_message = "The MCP server returned invalid protocol data."
    retryable = False


class McpCallTimeoutError(ToolTimeoutError):
    pass


class McpToolCollisionError(McpIntegrationError):
    pass


class McpAuthorizationRequired(McpStartupError):
    """A remote server needs the user to sign in; tasks never open a sign-in themselves."""

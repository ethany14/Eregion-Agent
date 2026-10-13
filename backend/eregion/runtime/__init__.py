"""Framework-independent tool execution primitives."""

from eregion.runtime.executor import ToolExecutor
from eregion.runtime.repository import ToolCallRepository
from eregion.runtime.security import REDACTED, arguments_hash, redact_sensitive
from eregion.runtime.policy import ToolPolicy, ToolPolicyDecision
from eregion.runtime.registry import ToolRegistry
from eregion.runtime.tools.messages import (
    AgentMessage, NormalizedToolCall, TokenUsage, ToolCallStep, ToolCapableModel,
    ToolLoopOutcome, ToolLoopStatus, ToolMessageEnvelope, ToolModelResponse,
)
from eregion.runtime.tools.model_adapter import LangChainToolModelAdapter
from eregion.runtime.tools.loop import ToolCallingLoop
from eregion.runtime.types import (
    RESUME_EVIDENCE_SOURCE_TYPES,
    AgentTool,
    ToolCallRecord,
    ToolCallEventRecord,
    ToolCallRequest,
    ToolContext,
    ToolExecutionStatus,
    ToolProvenance,
    ToolResult,
    ToolRiskLevel,
    ToolSideEffect,
    ToolDataClassification,
    provenance_may_support_resume_claim,
)

__all__ = [
    "RESUME_EVIDENCE_SOURCE_TYPES",
    "AgentTool",
    "AgentMessage",
    "NormalizedToolCall",
    "ToolCallRecord",
    "ToolCallStep",
    "ToolCallEventRecord",
    "ToolCallRequest",
    "ToolContext",
    "ToolExecutionStatus",
    "ToolExecutor",
    "ToolCallingLoop",
    "ToolLoopOutcome",
    "ToolLoopStatus",
    "ToolCapableModel",
    "ToolMessageEnvelope",
    "ToolModelResponse",
    "TokenUsage",
    "LangChainToolModelAdapter",
    "ToolCallRepository",
    "ToolPolicy",
    "ToolPolicyDecision",
    "ToolProvenance",
    "ToolRegistry",
    "ToolResult",
    "ToolRiskLevel",
    "ToolSideEffect",
    "ToolDataClassification",
    "provenance_may_support_resume_claim",
    "arguments_hash",
    "redact_sensitive",
    "REDACTED",
]

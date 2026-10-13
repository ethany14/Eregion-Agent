"""Built-in tools and their dependency-injected registration."""

from eregion.runtime.tools.domain_tools import register_domain_tools
from eregion.runtime.tools.loop import TOOL_DATA_SYSTEM_RULE, ToolCallingLoop
from eregion.runtime.tools.messages import (
    AgentMessage,
    NormalizedToolCall,
    TokenUsage,
    ToolCallStep,
    ToolCapableModel,
    ToolLoopOutcome,
    ToolLoopStatus,
    ToolMessageEnvelope,
    ToolModelResponse,
)
from eregion.runtime.tools.model_adapter import LangChainToolModelAdapter
from eregion.runtime.tools.run_reader import RunReader, SqlAlchemyRunReader
from eregion.runtime.tools.schemas import (
    CompareRunRequirementsInput,
    CompareRunRequirementsOutput,
    GetRunResultInput,
    ListRecentRunsInput,
    ListRecentRunsOutput,
    PublicRunResult,
    RenderTailoredResumeInput,
    RenderTailoredResumeOutput,
)

__all__ = [
    "AgentMessage", "LangChainToolModelAdapter", "NormalizedToolCall",
    "CompareRunRequirementsInput", "CompareRunRequirementsOutput",
    "GetRunResultInput", "ListRecentRunsInput", "ListRecentRunsOutput",
    "PublicRunResult", "RenderTailoredResumeInput",
    "RenderTailoredResumeOutput", "RunReader", "SqlAlchemyRunReader",
    "TOOL_DATA_SYSTEM_RULE", "TokenUsage", "ToolCallStep", "ToolCallingLoop",
    "ToolCapableModel", "ToolLoopOutcome", "ToolLoopStatus",
    "ToolMessageEnvelope", "ToolModelResponse",
    "register_domain_tools",
]

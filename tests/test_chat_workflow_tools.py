"""Real local persistence with synthetic sources; no model, network or submission."""
from types import SimpleNamespace
import pytest

from test_application_pack import setup
from eregion.runtime.sessions import SessionRepository, SessionState, SessionEvent, SessionEventType, SessionMessageDraft
from eregion.runtime.tools.messages import AgentMessage
from eregion.runtime.tools.workflow_tools import (StartApplicationTask, GetApplicationTask,
    StartTaskInput, TaskInput, LOCAL_WORKFLOW_TOOLS)
from eregion.runtime.coordination.repository import AgentTaskRepository
from eregion.runtime.registry import ToolRegistry
from eregion.runtime.resumes.repository import ResumeDocumentRepository
from eregion.runtime.types import ToolContext, ToolRiskLevel, ToolSideEffect
from eregion.runtime.policy import ToolPolicy
from eregion.runtime.job_workflow.workers import SourceProvisionWorker, ApplicationSourceReader


@pytest.fixture
def chat_runtime(setup):
    _, packs, workspace, evidence, saved, db = setup
    sessions = SessionRepository(db.session_factory)
    session = sessions.create(SessionState(session_id="chat", user_id="local-user"),
        SessionEvent(session_id="chat", event_type=SessionEventType.SESSION_CREATED),
        messages=[SessionMessageDraft(message=AgentMessage(message_id="u1", role="user",
            content="帮我为这个岗位写一封求职信"))])
    workspace.attach_session(saved.application.application_id, session.session_id, role="assistant",
                             expected_version=saved.application.version)
    resumes = ResumeDocumentRepository(db.session_factory)
    resumes.create(owner_id="local-user", filename="synthetic.pdf", display_name="Synthetic",
        extracted_text="Synthetic Candidate\nDeveloped APIs using Python.", content_sha256="a" * 64, page_count=1)
    types = frozenset({"job_source_provision", "candidate_analysis", "job_analysis", "requirement_match",
        "evidence_gap", "analysis_projection", "freeze_evidence", "artifact_writer", "artifact_verifier",
        "artifact_revision", "pack_assembler", "evidence_interview", "mock_interviewer"})
    runtime = SimpleNamespace(sessions=sessions, workspace=workspace, packs=packs, evidence=evidence,
        resumes=resumes, agent_tasks=AgentTaskRepository(db.session_factory), registry=ToolRegistry(),
        agent_workers=SimpleNamespace(names=lambda: types),
        agent_scheduler=SimpleNamespace(contexts=SimpleNamespace(task_type_tools={name:frozenset() for name in types})))
    runtime.registry.register(StartApplicationTask(runtime))
    runtime.registry.register(GetApplicationTask(runtime))
    return runtime


@pytest.mark.parametrize("action,artifacts", [("analyze_job", []), ("generate_materials", ["cover_letter"]),
    ("evidence_interview", []), ("mock_interview", [])])
def test_chat_creates_persisted_scoped_idempotent_tasks(chat_runtime, action, artifacts):
    rt = chat_runtime
    tool = StartApplicationTask(rt)
    args = StartTaskInput(action=action, requested_artifacts=artifacts)
    context = ToolContext(session_id="chat", allowed_tools=frozenset({tool.name}))
    result = tool.execute(args, context).output
    assert result["status"] == "queued"
    assert tool.execute(args, context).output["task_id"] == result["task_id"]
    root = rt.agent_tasks.require(result["task_id"])
    tasks = [root, *rt.agent_tasks.children(root.task_id)]
    if action == "generate_materials":
        writers = [t for t in tasks if t.task_type == "artifact_writer"]
        assert [t.input_spec["artifact_type"] for t in writers] == ["cover_letter"]
    if action != "mock_interview":
        assert root.input_spec["source_resume_id"] == rt.resumes.default("local-user").resume_id
        source = SourceProvisionWorker(ApplicationSourceReader(rt.workspace, rt.packs),
            resumes=rt.resumes, workspace=rt.workspace).execute(root, None)
        assert "Synthetic Candidate" in source.output_artifacts[0].content["data"]["resume_text"]
    assert GetApplicationTask(rt).execute(TaskInput(task_id=root.task_id), context).output["status"] == "running"
    with pytest.raises(ValueError, match="conversation"):
        GetApplicationTask(rt).execute(TaskInput(task_id=root.task_id), ToolContext(session_id="other"))


def test_local_task_capability_does_not_expand_external_or_readonly_permissions(chat_runtime):
    tool = StartApplicationTask(chat_runtime)
    policy = ToolPolicy(automatic_local_tools=LOCAL_WORKFLOW_TOOLS)
    assert not policy.evaluate(tool, ToolContext()).allowed
    context = ToolContext(allowed_tools=frozenset({tool.name}))
    assert policy.evaluate(tool, context).allowed
    tool.risk_level, tool.side_effect = ToolRiskLevel.EXTERNAL_WRITE, ToolSideEffect.EXTERNAL_WRITE
    assert policy.evaluate(tool, context).approval_required


def test_main_executor_persists_a_local_workflow_without_an_extra_approval(chat_runtime):
    from eregion.runtime.executor import ToolExecutor
    from eregion.runtime.repository import ToolCallRepository
    from eregion.runtime.types import ToolCallRequest, ToolExecutionStatus
    rt = chat_runtime
    executor = ToolExecutor(rt.registry, policy=ToolPolicy(automatic_local_tools=LOCAL_WORKFLOW_TOOLS),
        repository=ToolCallRepository(rt.workspace.session_factory))
    result = executor.execute(ToolCallRequest(tool_name="start_application_task",
        arguments={"action":"generate_materials", "requested_artifacts":["cover_letter"]},
        idempotency_key="chat-call"), ToolContext(session_id="chat", allowed_tools=LOCAL_WORKFLOW_TOOLS))
    assert result.status == ToolExecutionStatus.COMPLETED
    assert result.result.output["task_id"]

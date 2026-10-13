"""Chat tools enqueue persisted business work; they never approve or submit it."""
from __future__ import annotations

import hashlib
from typing import Literal
from uuid import NAMESPACE_URL, uuid5
from pydantic import Field

from eregion.runtime.types import (RuntimeModel, ToolResult, ToolRiskLevel,
    ToolSideEffect, ToolDataClassification)
from eregion.runtime.security import canonical_json
from eregion.runtime.job_workflow.plan import build_analysis_plan, build_pack_plan
from eregion.runtime.coordination.policy import AgentPlanValidator
from eregion.runtime.coordination.types import AgentPlan, TaskSpec, TaskDependencySpec
from eregion.runtime.job_workflow.workers import ApplicationSourceReader

LOCAL_WORKFLOW_TOOLS = frozenset({"start_application_task"})
WORKFLOW_TOOLS = LOCAL_WORKFLOW_TOOLS | {"get_application_task"}


class StartTaskInput(RuntimeModel):
    action: Literal["analyze_job", "generate_materials", "evidence_interview", "mock_interview"]
    requested_artifacts: list[Literal["tailored_resume", "cover_letter"]] = Field(default_factory=list, max_length=2)


class TaskInput(RuntimeModel):
    task_id: str = Field(min_length=1, max_length=128)


class TaskOutput(RuntimeModel):
    task_id: str | None = None
    status: str
    message: str | None = None
    tasks: list[dict] = Field(default_factory=list)
    pack_id: str | None = None


class StartApplicationTask:
    name = "start_application_task"
    version = "1"
    description = ("Execute the user's request for the CURRENT saved job: analyze fit, generate only "
        "the requested resume/cover letter drafts, or start an evidence/mock interview. Interprets "
        "any language without a keyword command. Returns a persisted background task, not completed "
        "work. Uses the attached resume or the user's uploaded default resume. Never submits applications or approves evidence.")
    risk_level = ToolRiskLevel.LOCAL_WRITE
    side_effect = ToolSideEffect.LOCAL_WRITE
    data_classification = ToolDataClassification.SENSITIVE
    timeout_seconds = 5.0
    idempotent = True
    input_schema, output_schema = StartTaskInput, TaskOutput

    def __init__(self, runtime):
        self.runtime = runtime

    def execute(self, arguments, context, **kwargs):
        rt = self.runtime
        application_id = rt.workspace.application_id_for_session(context.session_id)
        if not application_id:
            return ToolResult(output=TaskOutput(status="needs_input",
                message="Select or save the job for this conversation first.").model_dump())
        if (arguments.action == "generate_materials") != bool(arguments.requested_artifacts):
            return ToolResult(output=TaskOutput(status="needs_input",
                message="Specify requested_artifacts only for generating materials.").model_dump())
        application = rt.workspace.get_application(application_id)
        messages = rt.sessions.messages(context.session_id)
        latest = next((m for m in reversed(messages) if m.message.role == "user"), None)
        if latest is None:
            raise ValueError("A user request is required before starting work.")
        key = hashlib.sha256(canonical_json({"message_id": latest.message.message_id,
            "application_id": application_id, "snapshot": application.current_snapshot_id,
            "arguments": arguments.model_dump(mode="json")}).encode()).hexdigest()
        existing = rt.agent_tasks.plan_root(context.session_id, key)
        if existing:
            return ToolResult(output=TaskOutput(task_id=existing.task_id, status="queued",
                message="This request already has a persisted task; check its status.").model_dump())
        if arguments.action == "mock_interview":
            plan = AgentPlan(template_id="chat_mock_interview_v1", parent_session_id=context.session_id,
                root_key="interview", idempotency_key=key, tasks=[TaskSpec(key="interview",
                    task_type="mock_interviewer", agent_role="Mock interview", application_id=application_id)])
        else:
            source_document = None
            owner_id = rt.sessions.require(context.session_id).user_id or "local-user"
            try:
                resume, jd = ApplicationSourceReader(rt.workspace, rt.packs).read_sources(application_id)
            except ValueError:
                try:
                    source_document = rt.resumes.default(owner_id)
                except LookupError:
                    return ToolResult(output=TaskOutput(status="needs_input",
                        message="Upload a resume before starting this task.").model_dump())
                resume = source_document.extracted_text
                jd = rt.workspace.current_snapshot(application_id).cleaned_job_description
            common = dict(application_id=application_id, parent_session_id=context.session_id,
                          idempotency_key=key)
            if arguments.action == "generate_materials":
                job = rt.workspace.application_job(application_id)
                linked = tuple(sorted({link.evidence_id for link in rt.evidence.list_for_application(application_id)}))
                plan = build_pack_plan(**common,
                    requested_artifacts=frozenset(arguments.requested_artifacts),
                    job_snapshot_id=application.current_snapshot_id,
                    match_evidence_ids=linked, company=job.company, title=job.title)
            else:
                plan = build_analysis_plan(**common)
                plan.budget = plan.budget.model_copy(update={"max_depth": 5})
                plan.tasks.append(TaskSpec(key="project", task_type="analysis_projection",
                    agent_role="Analysis projection", parent_key="source", application_id=application_id,
                    input_spec={"job_snapshot_id": application.current_snapshot_id},
                    input_from_tasks={"job_analysis": "job", "match_report": "match"}))
                plan.dependencies.extend(TaskDependencySpec(task_key="project", depends_on_key=k)
                                         for k in ("job", "match"))
                plan.dependencies.append(TaskDependencySpec(task_key="gap", depends_on_key="project"))
                if arguments.action == "evidence_interview":
                    plan.tasks.append(TaskSpec(key="interview", task_type="evidence_interview",
                        agent_role="Evidence interview", parent_key="source", application_id=application_id,
                        max_attempts=25, input_from_tasks={"evidence_gap_plan": "gap"}))
                    plan.dependencies.extend(TaskDependencySpec(task_key="interview", depends_on_key=k)
                                             for k in ("gap", "project"))
            plan.tasks[0].input_spec.update({"job_snapshot_id": application.current_snapshot_id,
                "source_hash": hashlib.sha256(canonical_json({"resume_text": resume,
                    "job_description": jd}).encode()).hexdigest()})
            if source_document:
                plan.tasks[0].input_spec.update({"source_resume_id": source_document.resume_id, "owner_id": owner_id})
        depths = AgentPlanValidator(worker_types=rt.agent_workers.names(),
            registered_tools=rt.registry.names(), parent_tools=frozenset(),
            session_tools=frozenset(), task_type_tools=rt.agent_scheduler.contexts.task_type_tools).validate(plan)
        root = rt.agent_tasks.create_plan(plan, depths)
        return ToolResult(output=TaskOutput(task_id=root.task_id, status="queued",
            message="Task queued. Use get_application_task to check progress; do not claim completion yet.").model_dump())


class GetApplicationTask:
    name = "get_application_task"
    version = "1"
    description = "Read progress and result references for a task started by this conversation."
    risk_level = ToolRiskLevel.READ_ONLY
    side_effect = ToolSideEffect.NONE
    data_classification = ToolDataClassification.SENSITIVE
    timeout_seconds = 5.0
    idempotent = True
    input_schema, output_schema = TaskInput, TaskOutput

    def __init__(self, runtime):
        self.runtime = runtime

    def execute(self, arguments, context, **kwargs):
        rt = self.runtime
        root = rt.agent_tasks.require(arguments.task_id)
        if root.parent_session_id != context.session_id or root.parent_task_id is not None:
            raise ValueError("Task does not belong to this conversation.")
        tasks = [root, *rt.agent_tasks.children(root.task_id)]
        statuses = {t.status.value for t in tasks}
        status = next((s for s in ("failed", "timed_out", "cancelled", "awaiting_input",
                                  "awaiting_approval") if s in statuses),
                      "completed" if statuses == {"succeeded"} else "running")
        pack_id = str(uuid5(NAMESPACE_URL, f"pack:{root.task_id}")) if any(
            t.task_type == "pack_assembler" and t.status.value == "succeeded" for t in tasks) else None
        return ToolResult(output=TaskOutput(task_id=root.task_id, status=status, pack_id=pack_id,
            tasks=[{"task_id": t.task_id, "type": t.task_type, "status": t.status.value,
                    "result": t.result_summary} for t in tasks]).model_dump(mode="json"))


def register_workflow_tools(runtime):
    runtime.registry.register(StartApplicationTask(runtime))
    runtime.registry.register(GetApplicationTask(runtime))

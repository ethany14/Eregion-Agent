"""Unified loop M6 dry-run on a database COPY: restart under the new owners without side effects.

Usage:
    python scripts/unified_loop_dry_run.py --source PATH/TO/COPY.db --work DIR [--report OUT.json]

What it does, on a consistent snapshot (SQLite backup API, read-only source) in --work:
1. enumerates the expected in-flight objects per kind from stored rows, independently
   of the owner code, plus schema head, row counts and a terminal-history digest;
2. runs the real owner recoveries with recording stand-ins (TaskLoop recovery,
   InterviewQueue recovery, application-run recovery through ExecutionService; no
   model, browser or network call is possible) and CLASSIFIES Sessions and
   multi-agent tasks (no owner is invoked for those);
3. compares expectation and coverage per kind (missing / duplicate / unexpected),
   fails on a truncated listing, and checks history and source are unchanged.

The unified loop reuses the existing tables and ids (no schema change in M1-M5), so
the legacy -> execution mapping is the identity; the dry-run proves ownership and
recovery, not a data conversion. The real user database is refused unless
--allow-user-database is given; even then only a copy is used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

USER_DATABASE = (ROOT / "job_agent.db").resolve()
TERMINAL = {
    "career_tasks": {"completed", "cancelled"},
    "sessions": {"completed", "failed", "cancelled", "timed_out"},
    "applications": {"submitted", "cancelled", "failed"},
}


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def _history(database) -> dict:
    """Terminal records only; a restart must not change any of them."""
    from sqlalchemy import select
    from agent_runtime.auto_apply.repository import ApplyRepository
    from agent_runtime.career.repository import TaskRepository
    from agent_runtime.sessions.models import AgentSessionMessageRow, AgentSessionRow
    tasks = [s for s in TaskRepository(database.session_factory).list()
             if s["status"] in TERMINAL["career_tasks"]]
    apply = [s for s in ApplyRepository(database.session_factory).list()
             if s["status"] in TERMINAL["applications"]]
    with database.session_factory() as db:
        sessions = [(row.session_id, row.status, row.version) for row in db.scalars(
            select(AgentSessionRow).where(AgentSessionRow.status.in_(sorted(TERMINAL["sessions"]))))]
        messages = sorted((row.session_id, row.message_id, row.content_hash)
                          for row in db.scalars(select(AgentSessionMessageRow)))
    return {
        "career_tasks": _digest([(s["task_id"], s["status"], s["messages"]) for s in tasks]),
        "applications": _digest([(s["run_id"], s["status"], s.get("answers")) for s in apply]),
        "sessions": _digest(sessions),
        "session_messages": _digest(messages),
        "counts": {"career_tasks": len(tasks), "applications": len(apply), "sessions": len(sessions),
                   "session_messages": len(messages)},
    }


def _schema(database) -> str | None:
    from sqlalchemy import text
    with database.session_factory() as db:
        try:
            return db.execute(text("SELECT version_num FROM alembic_version")).scalar()
        except Exception:
            return None


CAREER_RESUMABLE = {"running", "queued"}
SESSION_IN_FLIGHT = {"running", "awaiting_tool_approval"}
AGENT_TERMINAL = {"succeeded", "failed", "cancelled", "timed_out"}


def _snapshot(source: Path, target: Path) -> None:
    """Consistent copy through SQLite's backup API from a read-only connection.

    A plain file copy would miss committed pages still in the -wal file.
    """
    import sqlite3
    reader = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    writer = sqlite3.connect(target)
    try:
        reader.backup(writer)
    finally:
        writer.close()
        reader.close()


def _coverage(expected, covered) -> dict:
    """Compare an independently enumerated expectation with what owners picked up."""
    counts: dict[str, int] = {}
    for identifier in covered:
        counts[identifier] = counts.get(identifier, 0) + 1
    expected = set(expected)
    return {"expected": len(expected), "covered": len(counts),
            "missing": sorted(expected - set(counts)),
            "duplicate": sorted(i for i, n in counts.items() if n > 1),
            "unexpected": sorted(set(counts) - expected)}


def _complete(section: dict) -> bool:
    return not (section["missing"] or section["duplicate"] or section["unexpected"])


def _expected(database) -> dict:
    """In-flight objects enumerated from stored rows, independently of the owner code."""
    from sqlalchemy import select
    from agent_runtime.career.repository import TaskRepository
    from agent_runtime.mock_interview.repository import MockInterviewRepository
    from agent_runtime.multi_agent.models import AgentTaskRow
    from agent_runtime.sessions.models import AgentSessionRow
    tasks = TaskRepository(database.session_factory).list()
    expected = {
        "career_task": sorted(t["task_id"] for t in tasks
                              if t["status"] in CAREER_RESUMABLE and not t.get("pause_requested")),
        "interview_inputs": sorted(t["task_id"] for t in tasks if not t.get("pause_requested")
            and t["status"] != "cancelled"
            and any(e.get("status") in {"pending", "running"} for e in t.get("interview_queue", []))),
    }
    interviews = MockInterviewRepository(database.session_factory)
    feedback = []
    for task in tasks:
        for interview_id in task.get("interviews", []):
            if interviews.get(interview_id).status.value in {"completed", "cancelled"}:
                continue
            feedback += [f"{task['task_id']}:{interview_id}:{job['answer_id']}"
                         for job in interviews.feedback_jobs(interview_id) if job["status"] == "pending"]
    expected["interview_feedback"] = sorted(feedback)
    with database.session_factory() as db:
        expected["session"] = sorted(db.scalars(select(AgentSessionRow.session_id).where(
            AgentSessionRow.status.in_(sorted(SESSION_IN_FLIGHT)))))
        agent_rows = list(db.execute(select(AgentTaskRow.task_id, AgentTaskRow.status)))
    expected["agent_status"] = {task_id: status for task_id, status in agent_rows}
    expected["agent_task"] = sorted(t for t, status in agent_rows if status not in AGENT_TERMINAL)
    return expected


def dry_run(source: Path, work: Path, *, agent_listing_limit: int | None = None) -> dict:
    from types import SimpleNamespace
    from api.db import create_database
    from agent_runtime.auto_apply.repository import ApplyRepository
    from agent_runtime.career.interview_queue import InterviewQueue
    from agent_runtime.career.repository import TaskRepository
    from agent_runtime.execution import ExecutionService
    from agent_runtime.mock_interview.repository import MockInterviewRepository
    from agent_runtime.multi_agent.repository import AgentTaskRepository
    from agent_runtime.sessions.host import in_flight_session_ids
    from agent_runtime.sessions.repository import SessionRepository
    from agent_runtime.task_loop import TaskLoop

    source = source.resolve()
    work.mkdir(parents=True, exist_ok=True)
    copy = work / "dry-run-copy.db"
    if copy.exists():
        raise SystemExit(f"{copy} exists; use a fresh work directory.")
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    _snapshot(source, copy)
    database = create_database(f"sqlite:///{copy.as_posix()}")
    try:
        schema, before = _schema(database), _history(database)
        expected = _expected(database)
        execution = ExecutionService()
        report: dict = {"schema_head": schema, "mapping": "identity (existing ids; no schema change)"}

        # Career tasks: the real TaskLoop recovery; scheduling recorded, nothing driven.
        tasks = TaskRepository(database.session_factory)
        scheduled: list[str] = []

        class RecordingTaskLoop(TaskLoop):
            def schedule(self, task_id):
                scheduled.append(task_id)

        RecordingTaskLoop(tasks, harness=object(), execution=execution).close()
        report["career_task"] = {"evidence": "owner recovery executed (TaskLoop._recover); drives recorded, not run",
                                 **_coverage(expected["career_task"], scheduled)}

        # Interview inputs and feedback: the real InterviewQueue.recover; submissions recorded.
        inputs_started: list[str] = []
        feedback_started: list[str] = []

        class Recorder:
            def submit(self, kind, key, function, *args):
                feedback_started.append(":".join(args[0]))

        class RecordingQueue(InterviewQueue):
            def start(self, task_id):
                inputs_started.append(task_id)

            def _execution(self):
                return Recorder()

        harness = SimpleNamespace(repository=tasks, runtime=SimpleNamespace(
            mock_interviewer=SimpleNamespace(interviews=MockInterviewRepository(database.session_factory))))
        RecordingQueue(harness).recover()
        report["interview_inputs"] = {"evidence": "owner recovery executed (InterviewQueue.recover); runs recorded",
                                      **_coverage(expected["interview_inputs"], inputs_started)}
        report["interview_feedback"] = {"evidence": "owner recovery executed (InterviewQueue.recover); jobs recorded",
                                        **_coverage(expected["interview_feedback"], feedback_started)}

        # Application runs: the registered owner's recovery without opening a browser.
        applications = ApplyRepository(database.session_factory)
        before_runs = {s["run_id"]: s for s in applications.list()}
        expected_resume = sorted(r for r, s in before_runs.items() if s.get("automation_mode") == "hybrid"
            and not s.get("pause_requested") and not s.get("cancel_requested") and not s.get("account_request")
            and s["status"] in {"running", "queued"})
        expected_manual = sorted(r for r, s in before_runs.items() if s["status"] == "submitting")
        resumed: list[str] = []
        execution.register_owner("application_run", role="dry-run: browser-affine owner (no browser)",
                                 recover=lambda: resumed.extend(applications.recover() or []))
        execution.recover("application_run")
        after = {s["run_id"]: s["status"] for s in applications.list()}
        manual = [r for r in expected_manual if after.get(r) == "submission_unknown"]
        report["application_run"] = {
            "evidence": "owner recovery executed (ApplyRepository.recover via ExecutionService); no browser",
            "resume": _coverage(expected_resume, resumed),
            "manual_submission_unknown": _coverage(expected_manual, manual),
            "transitions": {r: [before_runs[r]["status"], after[r]] for r in sorted(after)
                            if before_runs[r]["status"] != after[r]}}

        # Sessions and multi-agent tasks are CLASSIFIED only: no owner was invoked.
        sessions = SessionRepository(database.session_factory)
        in_flight = in_flight_session_ids(sessions)
        report["session"] = {"evidence": "classification only; no SessionHost turn was run",
            "pending_calls": {sid: list(sessions.require(sid).pending_tool_call_ids) for sid in sorted(set(in_flight))},
            **_coverage(expected["session"], in_flight)}

        agent_tasks = AgentTaskRepository(database.session_factory)
        status = expected["agent_status"]
        # A limit above every stored row cannot truncate silently; an injected
        # smaller limit (tests) must make the run fail instead of under-reporting.
        limit = agent_listing_limit or len(status) + 1
        ready = agent_tasks.list_ready(limit=limit)
        expired = agent_tasks.list_expired(limit=limit)
        truncated = len(ready) >= limit or len(expired) >= limit
        expired_ids = {task.task_id for task in expired}
        retained = [t for t in expected["agent_task"] if status[t] in {
            "pending", "blocked", "awaiting_approval", "awaiting_input"}
            or (status[t] in {"claimed", "running", "cancel_requested"} and t not in expired_ids)]
        report["agent_task"] = {"evidence": "classification only; scheduler dispatch was not run",
            "listing_truncated": truncated,
            "ready": sorted(t.task_id for t in ready), "expired_reclaim": sorted(expired_ids),
            "retained_by_status_or_live_lease": sorted(retained),
            **_coverage(expected["agent_task"], [t.task_id for t in ready] + sorted(expired_ids) + retained)}

        execution.close(wait=True)
        sections = [report[k] for k in ("career_task", "interview_inputs", "interview_feedback", "session", "agent_task")]
        sections += [report["application_run"]["resume"], report["application_run"]["manual_submission_unknown"]]
        report["coverage_complete"] = not truncated and all(_complete(section) for section in sections)

        after_history = _history(database)
        report["history_unchanged"] = before == after_history
        report["history_counts"] = after_history["counts"]
        report["source_unchanged"] = hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
        return report
    finally:
        database.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--allow-user-database", action="store_true")
    args = parser.parse_args()
    if args.source.resolve() == USER_DATABASE and not args.allow_user_database:
        print("Refusing the real user database; pass a test/anonymised copy (or --allow-user-database).")
        return 2
    report = dry_run(args.source, args.work)
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.report:
        args.report.write_text(text, encoding="utf-8")
    print(text)
    return 0 if report["history_unchanged"] and report["coverage_complete"] and report["source_unchanged"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

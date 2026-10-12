"""Unified loop M6 dry-run on a database COPY: restart under the new owners without side effects.

Usage:
    python scripts/unified_loop_dry_run.py --source PATH/TO/COPY.db --work DIR [--report OUT.json]

What it does, on a fresh copy in --work (the source file is never opened for writing):
1. records schema head, row counts and a digest of terminal ("history") records;
2. simulates one process restart with the unified owners: one ExecutionService,
   TaskLoop recovery (scheduling recorded, nothing driven), application-run
   recovery through the registered owner (no browser), Session and multi-agent
   in-flight classification; no model or network call is possible;
3. records the history digest again and reports, per kind, which objects the new
   owner would resume, which need manual handling (e.g. unknown submissions), and
   that every in-flight object has exactly one owner.

The unified loop reuses the existing tables and ids (no schema change in M1-M5), so
the legacy -> execution mapping is the identity; the dry-run proves ownership and
recovery, not a data conversion. The real user database is refused unless
--allow-user-database is given; even then only a copy is used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
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


def dry_run(source: Path, work: Path) -> dict:
    from api.db import create_database
    from agent_runtime.auto_apply.repository import ApplyRepository
    from agent_runtime.career.repository import TaskRepository
    from agent_runtime.execution import ExecutionService
    from agent_runtime.multi_agent.repository import AgentTaskRepository
    from agent_runtime.sessions.host import in_flight_session_ids, legacy_drain_ids
    from agent_runtime.sessions.repository import SessionRepository
    from agent_runtime.task_loop import TaskLoop

    source = source.resolve()
    work.mkdir(parents=True, exist_ok=True)
    copy = work / "dry-run-copy.db"
    if copy.exists():
        raise SystemExit(f"{copy} exists; use a fresh work directory.")
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    shutil.copyfile(source, copy)
    database = create_database(f"sqlite:///{copy.as_posix()}")
    try:
        schema, before = _schema(database), _history(database)
        execution = ExecutionService()
        report: dict = {"schema_head": schema, "mapping": "identity (existing ids; no schema change)"}

        # Career tasks: TaskLoop's registered once-only recovery, scheduling recorded only.
        tasks = TaskRepository(database.session_factory)
        scheduled: list[str] = []

        class RecordingTaskLoop(TaskLoop):
            def schedule(self, task_id):
                scheduled.append(task_id)

        loop = RecordingTaskLoop(tasks, harness=object(), execution=execution)
        loop.close()
        interview_inputs = sorted(s["task_id"] for s in tasks.list() if any(
            e.get("status") in {"pending", "running"} for e in s.get("interview_queue", [])))
        report["career_task"] = {"resumed": sorted(scheduled), "interview_inputs_pending": interview_inputs,
            "waiting": sorted(s["task_id"] for s in tasks.list() if s["status"] == "waiting"),
            "needs_input": sorted(s["task_id"] for s in tasks.list() if s["status"] == "needs_input")}

        # Application runs: the registered owner's recovery without opening a browser.
        applications = ApplyRepository(database.session_factory)
        before_status = {s["run_id"]: s["status"] for s in applications.list()}
        resumed: list[str] = []
        execution.register_owner("application_run", role="dry-run: browser-affine owner (no browser)",
                                 recover=lambda: resumed.extend(applications.recover() or []))
        execution.recover("application_run")
        after_status = {s["run_id"]: s["status"] for s in applications.list()}
        report["application_run"] = {
            "resumed_on_browser_owner": sorted(resumed),
            "submission_unknown_manual": sorted(r for r, s in after_status.items() if s == "submission_unknown"),
            "transitions": {r: [before_status[r], after_status[r]] for r in sorted(after_status)
                            if before_status.get(r) != after_status[r]}}

        # Sessions: every in-flight Session continues on the shared kernel unless registered.
        sessions = SessionRepository(database.session_factory)
        in_flight = in_flight_session_ids(sessions)
        drain = legacy_drain_ids()
        report["session"] = {"in_flight": sorted(in_flight), "legacy_drain_registered": sorted(drain & set(in_flight)),
            "shared_kernel": sorted(set(in_flight) - drain),
            "pending_calls": {sid: list(sessions.require(sid).pending_tool_call_ids) for sid in sorted(in_flight)}}

        # Multi-agent tasks: SQL-claimed by the scheduler's dispatch (classification only).
        agent_tasks = AgentTaskRepository(database.session_factory)
        report["agent_task"] = {"ready": sorted(t.task_id for t in agent_tasks.list_ready(limit=500)),
                                "expired_reclaim": sorted(t.task_id for t in agent_tasks.list_expired(limit=500))}

        # Every object that will be resumed must land in exactly one owner bucket.
        buckets = {
            "career_task": report["career_task"]["resumed"],
            "application_run": report["application_run"]["resumed_on_browser_owner"],
            "session_shared_kernel": report["session"]["shared_kernel"],
            "session_legacy_drain": report["session"]["legacy_drain_registered"],
            "agent_task": report["agent_task"]["ready"] + report["agent_task"]["expired_reclaim"],
        }
        seen: dict[str, list[str]] = {}
        for bucket, identifiers in buckets.items():
            for identifier in identifiers:
                seen.setdefault(identifier, []).append(bucket)
        report["multiple_owners"] = {i: b for i, b in sorted(seen.items()) if len(b) > 1}
        report["single_owner"] = not report["multiple_owners"]
        report["execution_inventory"] = {k: {"recovered": v["recovered"]}
                                         for k, v in execution.inventory()["kinds"].items()}
        execution.close(wait=True)

        after = _history(database)
        report["history_unchanged"] = before == after
        report["history_counts"] = after["counts"]
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
    return 0 if report["history_unchanged"] and report["single_owner"] and report["source_unchanged"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

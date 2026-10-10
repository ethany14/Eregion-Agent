"""Task DAG timings. Durations include retries; independent branches are not summed."""
import json
from sqlalchemy import select
from agent_runtime.multi_agent.models import AgentTaskRow, AgentTaskAttemptRow, AgentTaskDependencyRow, AgentTaskArtifactRow
from agent_runtime.application_pack.models import ApplicationPackRow

def record_pack_performance(sessions, root_id):
    with sessions.begin() as db:
        tasks = list(db.scalars(select(AgentTaskRow).where(AgentTaskRow.root_task_id == root_id)))
        ids = {t.task_id for t in tasks}
        if not ids:
            return
        summaries = list(db.scalars(select(AgentTaskArtifactRow).where(AgentTaskArtifactRow.task_id.in_(ids),
            AgentTaskArtifactRow.role == 'application_pack_summary')))
        if not summaries:
            return
        attempts = list(db.scalars(select(AgentTaskAttemptRow).where(AgentTaskAttemptRow.task_id.in_(ids))))
        attempts = [a for a in attempts if a.completed_at]
        if not attempts:
            return
        seconds = {key: 0.0 for key in ids}
        for a in attempts:
            seconds[a.task_id] += max(0, (a.completed_at - a.started_at).total_seconds())
        parents = {key: [] for key in ids}
        for d in db.scalars(select(AgentTaskDependencyRow).where(AgentTaskDependencyRow.task_id.in_(ids))):
            if d.depends_on_task_id in ids:
                parents[d.task_id].append(d.depends_on_task_id)
        scores = {}
        def longest(key):
            if key not in scores:
                prior = max((longest(p) for p in parents[key]), key=lambda p:p[0], default=(0, []))
                scores[key] = (prior[0] + seconds[key], [*prior[1], key])
            return scores[key]
        duration, path = max((longest(key) for key in ids), key=lambda p:p[0])
        names = {t.task_id: t.task_type for t in tasks}
        summary = {'wall_seconds': round((max(a.completed_at for a in attempts) - min(a.started_at for a in attempts)).total_seconds(), 3),
            'critical_path_seconds': round(duration, 3), 'critical_path': [names[key] for key in path],
            'task_seconds': {key: round(value, 3) for key, value in seconds.items()}}
        for artifact in summaries:
            pack = db.get(ApplicationPackRow, json.loads(artifact.content_json)['data']['pack_id'])
            if pack:
                pack.perf_summary_json = json.dumps(summary)

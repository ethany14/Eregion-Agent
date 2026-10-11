"""Read-only export of synthetic interview acceptance, errors and usage."""
import hashlib
import json
from pathlib import Path
import sqlite3
import sys


def export(root,destination):
    root=Path(root).resolve();source=next(root.glob('*/feedback-latency.json'))
    result=json.loads(source.read_text(encoding='utf-8'))
    with sqlite3.connect((source.parent/'career.db').as_uri()+'?mode=ro',uri=True) as db:
        events=[{'type':kind,'payload':json.loads(payload)} for kind,payload in db.execute(
            "select event_type,payload_json from mock_interview_events where event_type in ('FEEDBACK_QUEUED','FEEDBACK_FAILED','EVALUATION_SAVED') order by sequence")]
        calls=[{'task_id':task,**json.loads(details)} for task,details in db.execute('select task_id,details_json from provider_usage')]
    record={k:result.get(k) for k in ('scope','lane','configured_feedback_model','configured_reasoning','threshold_seconds',
        'p50_seconds','samples_seconds','checks','usage','max_pending_feedback','feedback_before_next_question')}
    record.update(source=str(source.relative_to(Path.cwd())),source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        events=events,queue=result['queue'],calls=calls,
        interpretation='Failed. Two returned latency samples do not establish a three-sample p50. A failed provider call has unknown token usage, not zero cost.',
        observer_revision='Original 360s loop, imported before terminal-helper edit. New helper was not applied to this run; pytest displayed source may reflect later edits.')
    destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:record[k] for k in ('p50_seconds','samples_seconds','checks','usage')},indent=2))


if __name__=='__main__':export(*sys.argv[1:])

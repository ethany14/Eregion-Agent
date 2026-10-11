"""C11 saved-job aliases must not count the same durable attempt twice."""
from test_career_flow import career, execute


def test_two_saved_application_ids_for_one_posting_count_one_actual_start(career):
    c=career
    first=c.runtime.workspace.save_workspace(cleaned_job_description='Requires Python APIs.',
        source_url='https://careers.example.com/jobs/alias-count',title='Python Engineer')
    second=c.runtime.workspace.create_application(job_id=first.application.job_id,
        snapshot_id=first.application.current_snapshot_id)
    ids=[first.application.application_id,second.application_id]
    for app_id in ids:c.repository.link(c.state['task_id'],'jobs',app_id)
    result=execute(c,'start_application',application_ids=ids,resume_source='original')
    assert result['requested_count']==2 and result['opened_or_reused_count']==1
    assert result['resolved_request_count']==2
    assert len({r['application']['run_id'] for r in result['results']})==1
    assert len(c.repository.get(c.state['task_id'])['application_runs'])==1
    assert result['started_count']==1
    assert [r['started'] for r in result['results']]==[True,False]
    repeat=execute(c,'start_application',application_ids=ids,resume_source='original')
    assert repeat['started_count']==0 and repeat['opened_or_reused_count']==1
    assert len(c.repository.get(c.state['task_id'])['application_runs'])==1

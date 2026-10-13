"""Applications page figures: funnel, weekly activity, totals and allowed board moves."""
from datetime import UTC, date, datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient

from eregion.runtime.workspace.types import ApplicationStatus as S
from eregion.api.main import create_app
from eregion.api.services.application_overview import overview, stage_reached
from test_job_workspace import make_job, workspace  # noqa: F401 - pytest fixture import


def app(status, *, score=None, applied=None):
    return SimpleNamespace(status=status, match_score=score, applied_at=applied)


def test_stage_reached_counts_closed_applications_by_how_far_they_got():
    applied = datetime(2026, 9, 2, tzinfo=UTC)
    assert stage_reached(S.SAVED, match_score=None, applied_at=None) == 0
    assert stage_reached(S.SAVED, match_score=70, applied_at=None) == 1
    assert stage_reached(S.MATERIALS_READY, match_score=None, applied_at=None) == 1
    assert stage_reached(S.REJECTED, match_score=80, applied_at=applied) == 2
    assert stage_reached(S.WITHDRAWN, match_score=None, applied_at=None) == 1
    assert stage_reached(S.INTERVIEWING, match_score=None, applied_at=applied) == 3
    assert stage_reached(S.OFFER, match_score=None, applied_at=applied) == 4


def test_overview_funnel_weeks_and_response_rate():
    today = date(2026, 10, 8)  # A Thursday; its week starts Monday 5 October.
    items = [
        app(S.SAVED), app(S.NEEDS_EVIDENCE, score=74),
        app(S.APPLIED, score=85, applied=datetime(2026, 10, 6, 9, tzinfo=UTC)),
        app(S.APPLIED, score=77, applied=datetime(2026, 9, 29, tzinfo=UTC)),
        app(S.INTERVIEWING, score=91, applied=datetime(2026, 9, 22, tzinfo=UTC)),
        app(S.OFFER, score=88, applied=datetime(2026, 9, 1, tzinfo=UTC)),
        app(S.REJECTED, score=60, applied=datetime(2026, 9, 2, tzinfo=UTC)),
        app(S.APPLIED, applied=datetime(2025, 1, 1, tzinfo=UTC)),  # Outside the window, still applied.
        app(S.ARCHIVED, score=50, applied=datetime(2026, 10, 7, tzinfo=UTC)),  # Never counted.
    ]
    result = overview(items, weeks=6, today=today)
    assert [s['count'] for s in result['funnel']] == [8, 7, 6, 2, 1]
    assert [w['week_start'] for w in result['weekly']] == [date(2026, 8, 31), date(2026, 9, 7), date(2026, 9, 14),
                                                          date(2026, 9, 21), date(2026, 9, 28), date(2026, 10, 5)]
    assert [w['count'] for w in result['weekly']] == [2, 0, 0, 1, 1, 1]
    assert result['totals'] == {'tracked': 8, 'applied': 6, 'interviewing': 1, 'offers': 1, 'rejected': 1,
                                'response_rate': 50}
    assert overview([], weeks=4, today=today)['totals']['response_rate'] is None


def test_overview_route_lists_every_application_with_allowed_moves(workspace):
    _, repository = workspace
    created = []
    for index in range(3):
        job = make_job(repository, company=f'Company {index}', title='Designer', description=f'Role {index} needs Figma.')
        created.append(repository.create_application(job_id=job.job.job_id, snapshot_id=job.snapshot.snapshot_id))
    record = created[0]
    for target in (S.ANALYZING, S.MATERIALS_READY, S.READY_TO_APPLY):
        record = repository.transition_status(record.application_id, target_status=target, expected_version=record.version)
    repository.transition_status(record.application_id, target_status=S.APPLIED, expected_version=record.version,
                                 applied_at=datetime.now(UTC))
    client_app = create_app(run_service=object(), session_runtime=SimpleNamespace(workspace=repository))
    with TestClient(client_app) as client:
        assert client.get('/api/applications/overview', params={'weeks': 2}).status_code == 422
        body = client.get('/api/applications/overview', params={'weeks': 4}).json()
    by_id = {a['application_id']: a for a in body['applications']}
    assert len(by_id) == 3
    assert by_id[record.application_id]['next_statuses'] == ['interviewing', 'rejected', 'withdrawn']
    assert by_id[created[1].application_id]['next_statuses'] == ['analyzing']
    assert by_id[created[1].application_id]['company'] == 'Company 1'
    assert body['totals']['applied'] == 1 and body['weekly'][-1]['count'] == 1
    assert [s['count'] for s in body['funnel']] == [3, 1, 1, 0, 0]

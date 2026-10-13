"""Organising conversations: rename, pin, groups, archive and the 30-day trash."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from eregion.runtime.career.repository import TaskRepository
from eregion.runtime.career.service import CareerService
from eregion.api.main import create_app
from test_auto_apply import wait
from test_career_flow import approve, career, execute, prepare  # noqa: F401 - pytest fixture import


def make_service(c):
    service = CareerService.__new__(CareerService)
    service.runtime, service.applications, service.repository, service.harness = c.runtime, c.applications, c.repository, c.harness
    service.chats = []
    service.loop = SimpleNamespace(chat=lambda task_id, text, message_id, **_: service.chats.append((task_id, text)))
    return service


def ids(listing):
    return [a['run_id'] for a in listing['attempts'] if a.get('career')]


def test_rename_pin_and_group_do_not_touch_task_state(career):
    service, task = make_service(career), career.state['task_id']
    before = career.repository.get(task)
    view = service.organise(task, {'title': '  Berlin design roles  ', 'pinned': True})
    assert view['title'] == 'Berlin design roles' and view['custom_title'] and view['pinned_at']
    after = career.repository.get(task)
    assert after['version'] == before['version'] and after['updated_at'] == before['updated_at']

    group = career.repository.create_group('Berlin search')
    assert service.organise(task, {'group_id': group['group_id']})['group_id'] == group['group_id']
    with pytest.raises(LookupError):
        service.organise(task, {'group_id': 'missing-group'})
    career.repository.delete_group(group['group_id'])
    assert service.view(task)['group_id'] is None
    # Clearing the title falls back to the generated one.
    assert service.organise(task, {'title': ''})['title'] == before['title']


def test_archive_hides_conversation_and_a_new_message_brings_it_back(career):
    service, task = make_service(career), career.state['task_id']
    service.organise(task, {'archived': True})
    assert task not in ids(service.list()) and task in ids(service.list('archived'))
    service.chat(task, 'Any news?', 'message-archived-1')
    assert service.chats == [(task, 'Any news?')]
    assert task in ids(service.list()) and service.view(task)['archived_at'] is None


def test_trash_restore_and_permanent_delete_keep_applications_and_materials(career):
    c, service, task = career, make_service(career), career.state['task_id']
    job, pack = prepare(c); approve(c, pack)
    run = execute(c, 'start_application', application_id=job['application_id'], pack_id=pack['pack_id'])
    assert wait(c.applications, run['run_id'])['status'] == 'awaiting_review'

    c.repository.change(task, status='running')
    with pytest.raises(ValueError, match='Stop'):
        service.organise(task, {'trashed': True})
    c.repository.change(task, status='completed')
    with pytest.raises(ValueError, match='Trash before'):
        service.delete(task)

    service.organise(task, {'trashed': True})
    assert task not in ids(service.list()) and task not in ids(service.list('archived'))
    assert task in ids(service.list('trash'))
    with pytest.raises(ValueError, match='Restore'):
        service.chat(task, 'Hello again', 'message-trashed-1')

    service.organise(task, {'trashed': False})
    assert task in ids(service.list())
    service.organise(task, {'trashed': True})
    service.delete(task)
    with pytest.raises(LookupError):
        c.repository.get(task)
    # The application, its materials and the job record all outlive the conversation.
    assert c.applications.repository.get(run['run_id'])['status'] == 'awaiting_review'
    assert len(c.runtime.packs.items(pack['pack_id'])) == 2
    assert c.runtime.workspace.get_application(job['application_id'])
    # A run the conversation started does not resurface as a stray attempt.
    assert run['run_id'] not in [a['run_id'] for a in service.list()['attempts']]


def test_trash_empties_after_thirty_days(career):
    repository = career.repository
    old, recent, kept = career.state['task_id'], repository.create('Recent', 'trash-recent')[0]['task_id'], repository.create('Kept', 'trash-kept')[0]['task_id']
    moment = datetime(2026, 10, 8, 12, tzinfo=UTC)
    repository.update_meta(old, trashed_at=(moment - timedelta(days=31)).isoformat())
    repository.update_meta(recent, trashed_at=(moment - timedelta(days=29)).isoformat())
    assert repository.purge_expired_trash(moment) == [old]
    assert repository.metadata(recent)['trashed_at'] and repository.metadata(kept)['trashed_at'] is None
    with pytest.raises(LookupError):
        repository.get(old)
    assert sorted(repository.purge_trash()) == [recent]
    assert TaskRepository(career.runtime.database.session_factory).get(kept)['goal'] == 'Kept'


def test_organise_routes(career):
    service, task = make_service(career), career.state['task_id']
    career.repository.change(task, status='completed')
    app = create_app(run_service=object())
    with TestClient(app, base_url='http://localhost') as client:
        app.state.career_agent = service
        assert client.get('/api/career/tasks', params={'view': 'nope'}).status_code == 422
        assert client.patch(f'/api/career/tasks/{task}', json={'title': 'Renamed'}).json()['title'] == 'Renamed'
        assert client.patch(f'/api/career/tasks/{task}', json={'colour': 'red'}).status_code == 422
        assert client.delete(f'/api/career/tasks/{task}').status_code == 409

        group = client.post('/api/career/groups', json={'name': 'Design leads'})
        assert group.status_code == 201
        group_id = group.json()['group_id']
        assert client.post('/api/career/groups', json={'name': '   '}).status_code == 422
        assert client.patch(f'/api/career/groups/{group_id}', json={'name': 'Leads'}).json()['name'] == 'Leads'
        assert client.get('/api/career/tasks').json()['groups'] == [{'group_id': group_id, 'name': 'Leads', 'position': 0}]
        assert client.delete(f'/api/career/groups/{group_id}').status_code == 204
        assert client.delete(f'/api/career/groups/{group_id}').status_code == 404

        assert client.patch(f'/api/career/tasks/{task}', json={'trashed': True}).status_code == 200
        assert [a['run_id'] for a in client.get('/api/career/tasks', params={'view': 'trash'}).json()['attempts']] == [task]
        assert client.delete('/api/career/tasks/trash').json() == {'deleted': [task]}
        assert client.get(f'/api/career/tasks/{task}').status_code == 404
        app.state.career_agent = None  # The fixture, not app shutdown, owns this service's cleanup.

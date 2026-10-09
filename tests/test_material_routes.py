"""Materials library API over real packs generated in the career flow fixture."""
from types import SimpleNamespace

from fastapi.testclient import TestClient

from api.main import create_app
from test_career_flow import approve, career, prepare  # noqa: F401 - pytest fixture import


def test_library_lists_latest_documents_with_status_and_renders_versions(career):
    c = career
    job, pack = prepare(c)
    runtime = SimpleNamespace(workspace=c.runtime.workspace, packs=c.runtime.packs, pack_workflow=c.runtime.pack_workflow)
    app = create_app(run_service=object(), session_runtime=runtime)
    with TestClient(app) as client:
        listed = client.get('/api/materials').json()['materials']
        assert {m['artifact_type'] for m in listed} == {'tailored_resume', 'cover_letter'}
        assert all(m['application_id'] == job['application_id'] and m['company'] == 'Example' for m in listed)
        assert all(m['status'] == 'awaiting_review' and not m['stale'] for m in listed)
        resume = next(m for m in listed if m['artifact_type'] == 'tailored_resume')
        assert resume['pdf'].endswith('/resume.pdf') and client.get(resume['pdf']).status_code == 200
        detail = client.get(f"/api/materials/{resume['pack_id']}/{resume['pack_item_id']}").json()
        assert detail['current_version'] == resume['version'] and detail['versions']
        assert 'Python' in detail['versions'][-1]['text']
        assert client.get(f"/api/materials/{resume['pack_id']}/missing-item").status_code == 404

        approve(c, pack)
        assert {m['status'] for m in client.get('/api/materials').json()['materials']} == {'approved'}

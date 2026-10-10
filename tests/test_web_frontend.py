from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient

from api.main import create_app


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web_app"


def test_web_app_route_and_assets_are_served() -> None:
    with TestClient(create_app(run_service=object())) as client:
        response = client.get("/apply")
        assert response.status_code == 200
        assert "eregion · Career agent" in response.text
        assert 'href="/app#' not in response.text
        assert 'data-view-panel=' not in response.text
        assert client.get("/web-assets/apply.css").status_code == 200
        assert client.get("/web-assets/apply.js").status_code == 200
        assert client.get("/web-assets/career-chat.js").status_code == 200
        assert response.headers["cache-control"] == "no-store"
        for path in ("/", "/app", "/app/", "/index.html", "/web-assets/index.html",
                     "/web-assets/INDEX.HTML", "/web-assets/apply.html"):
            redirect = client.get(path, follow_redirects=False)
            assert redirect.status_code == 307, path
            assert redirect.headers["location"] == "/apply"
            assert redirect.headers["cache-control"] == "no-store"
            assert client.get(path).text == response.text


def test_old_bookmarks_preserve_job_context_and_drop_old_view_settings() -> None:
    with TestClient(create_app(run_service=object())) as client:
        for path in ("/app", "/web-assets/index.html"):
            response = client.get(path, params={"application":"saved-job", "url":"https://example.org/jobs?a=1&b=2",
                                               "mode":"legacy", "next":"https://example.org"}, follow_redirects=False)
            target = urlsplit(response.headers["location"])
            assert target.path == "/apply" and not target.netloc
            assert parse_qs(target.query) == {"application":["saved-job"], "url":["https://example.org/jobs?a=1&b=2"]}


def test_archived_workspace_source_retains_reusable_controls() -> None:
    page = (WEB / "index.html").read_text(encoding="utf-8")
    for view in {"overview", "jobs", "copilot", "materials",
                 "evidence", "learning", "settings"}:
        assert f'data-view-panel="{view}"' in page
    assert 'data-view-panel="interviews"' not in page
    assert 'id="execution-mode"' not in page
    assert 'id="task-activity-list"' not in page
    assert 'id="resume-file"' in page
    assert 'accept="application/pdf,.pdf"' in page


def test_web_frontend_uses_safe_dom_and_server_side_resume_storage() -> None:
    script = (WEB / "app.js").read_text(encoding="utf-8")
    client = (WEB / "api.js").read_text(encoding="utf-8")
    assert "innerHTML" not in script
    assert "textContent" in script
    assert 'request("/api/resumes"' in client
    assert '"Content-Type": "application/pdf"' in client
    assert "localStorage.setItem" in script
    assert "resume_text" not in script


def test_web_workspace_has_history_deletion_material_actions_and_safe_dialog_close() -> None:
    page = (WEB / "index.html").read_text(encoding="utf-8")
    script = (WEB / "app.js").read_text(encoding="utf-8")
    client = (WEB / "api.js").read_text(encoding="utf-8")
    assert 'id="session-history"' in page
    assert 'class="conversation-sidebar"' in page
    assert "session-row" in script
    assert 'id="delete-session"' in page
    assert 'id="material-dialog"' in page
    assert 'name="source_url"' in page
    assert 'type="button" data-close-dialog="job-dialog"' in page
    assert 'type="button" data-close-dialog="evidence-dialog"' in page
    assert "approvePackItem" in script and "regeneratePackItem" in script
    assert "Download PDF" in script and "/resume.pdf" in script
    assert 'request(`/sessions/${encodeURIComponent(id)}?expected_version=${version}`' in client
    assert "createMemory" not in script


def test_web_buttons_have_hover_click_and_motion_feedback() -> None:
    styles = (WEB / "styles.css").read_text(encoding="utf-8")
    assert ":hover" in styles
    assert ":active" in styles
    assert "cubic-bezier" in styles
    assert "@keyframes enter" in styles
    assert "Monochrome product theme" in styles
    assert "--accent:#111" in styles
    assert "linear-gradient(145deg,#0e0e0e,#242424" in styles


def test_copilot_optimistically_renders_user_message_and_thinking_state() -> None:
    script = (WEB / "app.js").read_text(encoding="utf-8")
    styles = (WEB / "styles.css").read_text(encoding="utf-8")
    assert 'appendConversationMessage("user", content' in script
    assert 'appendConversationMessage("assistant", "Thinking…"' in script
    assert "setSessionBusy(true)" in script
    assert "optimisticUser.classList.add(\"send-failed\")" in script
    assert "await renderSession();" not in script[script.index("async function sendMessage"):script.index("async function deleteCurrentSession")]
    assert ".pending-message" in styles
    assert ".message-delivery" in styles

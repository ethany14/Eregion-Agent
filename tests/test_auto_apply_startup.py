"""Missing browser dependencies must produce an actionable pause, without retries."""
import builtins

import pytest

from eregion.runtime.auto_apply.browser import ApplicationBrowser, BrowserBlocked
from eregion.runtime.auto_apply.loop import ApplicationLoop
from eregion.runtime.auto_apply.repository import ApplyRepository
from test_auto_apply import database, request, wait


@pytest.fixture(params=["playwright", "greenlet", "pyee"])
def missing_browser_dependency(monkeypatch, request):
    original_import = builtins.__import__
    attempts = []

    def import_without_dependency(name, *args, **kwargs):
        if name == "playwright.sync_api":
            attempts.append(name)
            raise ModuleNotFoundError(
                f"No module named '{request.param}'", name=request.param)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_dependency)
    return attempts


def test_missing_browser_dependency_explains_how_to_repair(missing_browser_dependency):
    with pytest.raises(BrowserBlocked) as error:
        ApplicationBrowser("https://jobs.lever.co/example/abc123")
    assert "python -m pip install -r requirements.txt" in str(error.value)
    assert "same Python environment" in str(error.value)
    assert "restart the server" in str(error.value)
    assert isinstance(error.value.__cause__, ModuleNotFoundError)


def test_missing_browser_dependency_pauses_without_automatic_retries(
        database, missing_browser_dependency):
    loop = ApplicationLoop(ApplyRepository(database.session_factory), retry_delays=(0, 0))
    try:
        run_id = loop.start(request(automation_mode="hybrid"))["run_id"]
        state = wait(loop, run_id)
        assert state["status"] == "needs_input"
        assert "python -m pip install -r requirements.txt" in state["message"]
        assert state.get("recovery_attempts", 0) == 0
        assert not loop.scheduled
        assert not loop.browsers
        assert len(missing_browser_dependency) == 1
    finally:
        loop.close()

"""The real-site apply test launcher can never submit (plan 2026-10-15)."""
from types import SimpleNamespace

import pytest

from eregion.runtime.auto_apply import browser, loop, repository, visual
from eregion.runtime.auto_apply.browser import BrowserBlocked
from scripts.live_apply_server import FINAL_WORDING, SubmissionBlocked, install_guards


@pytest.fixture
def guarded(tmp_path, monkeypatch):
    # monkeypatch restores every patched class attribute after the test.
    for owner, name in ((browser.ApplicationBrowser, 'submit'), (browser.ApplicationBrowser, 'click_page_action'),
                        (visual.VisualBrowser, 'guard'), (repository.ApplyRepository, 'create'),
                        (loop.ApplicationLoop, '__init__')):
        monkeypatch.setattr(owner, name, owner.__dict__[name])
    clicks = []
    monkeypatch.setattr(browser.ApplicationBrowser, 'click_page_action', lambda self, action: clicks.append(action) or 'clicked')
    monkeypatch.setattr(visual.VisualBrowser, 'guard', staticmethod(lambda target: 'allowed'))
    created = []
    monkeypatch.setattr(repository.ApplyRepository, 'create', lambda self, request, **k: created.append(request) or request)
    install_guards(tmp_path)
    return clicks, created


def test_submit_always_raises(guarded):
    with pytest.raises(SubmissionBlocked):
        browser.ApplicationBrowser.submit(object())


@pytest.mark.parametrize('label', ['Submit application', 'Submit', 'Send application', 'Send', 'Finish',
                                   'Complete my application', 'Confirm and apply'])
def test_final_wording_is_never_clicked(guarded, label):
    clicks, _ = guarded
    with pytest.raises(BrowserBlocked):
        browser.ApplicationBrowser.click_page_action(object(), {'label': label})
    with pytest.raises(BrowserBlocked):
        visual.VisualBrowser.guard({'label': label})
    assert not clicks


@pytest.mark.parametrize('label', ['Apply for this job', 'Apply now', 'Next', 'Continue', 'Review', 'Save and continue',
                                   'Add another', 'Upload resume'])
def test_navigation_wording_still_works(guarded, label):
    clicks, _ = guarded
    assert browser.ApplicationBrowser.click_page_action(object(), {'label': label}) == 'clicked'
    assert visual.VisualBrowser.guard({'label': label}) == 'allowed'
    assert not FINAL_WORDING.search(label)


def test_every_application_starts_with_auto_submit_off(guarded):
    _, created = guarded
    request = SimpleNamespace(model_copy=lambda update: SimpleNamespace(**update))
    repository.ApplyRepository.create(object(), request)
    assert created[0].auto_submit is False

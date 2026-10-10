"""Popups, cross-site redirects, identity providers, confirmations, review stability and handoff resume."""
import os
from types import SimpleNamespace

import pytest

from agent_runtime.auto_apply.browser import ApplicationBrowser
from agent_runtime.auto_apply.loop import ApplicationLoop
from agent_runtime.auto_apply.repository import ApplyRepository
from test_auto_apply import FakeBrowser, database, request, wait

chrome = pytest.mark.skipif(os.getenv("JOB_AGENT_BROWSER_TESTS") != "1", reason="Offline Chrome opt-in")


def guard_browser(**changes):
    """The request guard and barrier logic without launching Chrome."""
    browser = ApplicationBrowser.__new__(ApplicationBrowser)
    browser.purpose, browser.headless, browser._trusted_until = "application", True, 0
    browser.navigation_hosts = {"careers.example.com"}
    browser._dns_cache = {"careers.example.com": True, "ats.example.net": True, "internal.example": False}
    browser.__dict__.update(changes)
    return browser


def navigation(url):
    calls = []
    route = SimpleNamespace(request=SimpleNamespace(url=url, is_navigation_request=lambda: True,
        frame=SimpleNamespace(parent_frame=None)), abort=lambda: calls.append("abort"),
        continue_=lambda: calls.append("continue"))
    return route, calls


def test_navigation_to_a_new_site_needs_a_recent_click_or_the_user():
    browser = guard_browser()
    route, calls = navigation("https://ats.example.net/apply/123")
    browser._guard_request(route)
    assert calls == ["abort"] and "ats.example.net" not in browser.navigation_hosts

    # The agent clicked Apply on the career site; its redirect to the ATS is followed.
    import time
    browser._trusted_until = time.monotonic() + 10
    route, calls = navigation("https://ats.example.net/apply/123")
    browser._guard_request(route)
    assert calls == ["continue"] and "ats.example.net" in browser.navigation_hosts

    # Never to private addresses or plain HTTP, even right after a click.
    for url in ("https://internal.example/", "http://ats2.example.net/", "https://127.0.0.1/"):
        route, calls = navigation(url)
        browser._guard_request(route)
        assert calls == ["abort"], url

    # In the visible window the user may navigate anywhere public.
    visible = guard_browser(headless=False)
    visible._dns_cache["sso.example.org"] = True
    route, calls = navigation("https://sso.example.org/login")
    visible._guard_request(route)
    assert calls == ["continue"]


def test_identity_provider_pages_are_handed_to_the_user():
    browser = guard_browser(page=SimpleNamespace(url="https://accounts.google.com/signin"))
    assert "accounts.google.com sign-in" in browser.barrier()


def test_review_digest_ignores_clocks_but_not_answers():
    page = {"url": "https://x.example/review", "heading": "Review", "can_submit": True,
        "text": "Phone 555-1234. Saved 2 minutes ago at 10:42 PM."}
    digest = ApplicationLoop._review_digest([], page)
    assert digest == ApplicationLoop._review_digest([], {**page, "text": "Phone 555-1234. Saved just now at 10:44 PM."})
    assert digest != ApplicationLoop._review_digest([], {**page, "text": "Phone 555-9999. Saved 2 minutes ago at 10:42 PM."})


class VerificationBrowser(FakeBrowser):
    challenged = True
    def barrier(self): return "Complete the verification challenge in the open browser, then continue." if self.challenged else None
    def verification_barrier(self): return self.barrier()


def test_run_continues_by_itself_after_verification_is_cleared(database):
    browser = VerificationBrowser("")
    loop = ApplicationLoop(ApplyRepository(database.session_factory), browser_factory=lambda _: browser)
    try:
        run_id = loop.start(request())["run_id"]
        paused = wait(loop, run_id)
        assert paused["status"] == "needs_input" and paused["handoff_kind"] == "verification"
        browser.challenged = False  # The user solved it in the browser window.
        import time
        deadline = time.monotonic() + 10
        while loop.repository.get(run_id)["status"] == "needs_input" and time.monotonic() < deadline:
            time.sleep(.05)
        assert wait(loop, run_id)["status"] == "awaiting_review"
    finally:
        loop.close()


def test_a_user_pause_is_not_overridden_by_auto_resume(database):
    from agent_runtime.auto_apply.contracts import ChatRequest
    browser = VerificationBrowser("")
    loop = ApplicationLoop(ApplyRepository(database.session_factory), browser_factory=lambda _: browser)
    try:
        run_id = loop.start(request(automation_mode="hybrid"))["run_id"]
        wait(loop, run_id)
        loop.chat(run_id, ChatRequest(text="pause", message_id="pause-message-1"))
        browser.challenged = False
        import time
        time.sleep(3.5)
        state = loop.repository.get(run_id)
        assert state["status"] == "needs_input" and state["pause_requested"]
    finally:
        loop.close()


@chrome
def test_closed_popup_returns_to_the_application_tab():
    from test_auto_apply_browser import FixtureBrowser
    browser = FixtureBrowser("https://job-boards.greenhouse.io/example/jobs/123")
    try:
        browser.page.set_content('<form id="application"><label for="n">First name</label><input id="n" required>'
            '<button type="button" id="open" onclick="window.popup=window.open(\'about:blank\')">Privacy</button></form>')
        anchor = browser.page
        with browser.context.expect_page() as opened:
            browser.page.click("#open")
        opened.value.close()
        assert browser.is_open()
        assert [f["label"] for f in browser.observe()] == ["First name"]
        assert browser.page is anchor
    finally:
        browser.close()


@chrome
def test_generic_confirmation_is_only_accepted_after_submitting():
    from test_auto_apply_browser import FixtureBrowser
    browser = FixtureBrowser("https://job-boards.greenhouse.io/example/jobs/123")
    try:
        browser.page.set_content('<main><h1>Thanks for applying!</h1><p>We have received your application.</p></main>')
        assert browser.confirmation() is None
        assert "received your application" in browser.confirmation(after_submit=True)["text"]
        # An unfinished form with polite text is not a confirmation.
        browser.page.set_content('<main><p>Thank you for your application to Acme.</p><form id="application">'
            '<label for="n">First name</label><input id="n" required><button type="submit">Submit</button></form></main>')
        assert browser.confirmation(after_submit=True) is None
    finally:
        browser.close()


@chrome
def test_offscreen_window_is_shown_without_reloading(monkeypatch):
    monkeypatch.setenv("JOB_AGENT_HIDDEN_BROWSER", "offscreen")
    from test_auto_apply_browser import FixtureBrowser
    browser = FixtureBrowser("https://job-boards.greenhouse.io/example/jobs/123")
    try:
        assert browser._offscreen and browser.headless
        assert browser.page.evaluate("navigator.userAgent").find("Headless") == -1
        browser.page.evaluate("window.marker = 'kept'")
        bounds = lambda: browser.context.new_cdp_session(browser.page).send("Browser.getWindowForTarget")["bounds"]
        assert bounds()["left"] < -10000
        browser.set_visible(True)
        assert not browser.headless and bounds()["left"] >= 0
        assert browser.page.evaluate("window.marker") == "kept"  # Same page, no relaunch.
        browser.set_visible(False)
        assert browser.headless and bounds()["left"] < -10000
    finally:
        browser.close()

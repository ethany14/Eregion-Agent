"""Credential execution on the browser worker, never in an LLM tool payload."""
import re
from urllib.parse import urlsplit

from .browser import BrowserBlocked

PASSWORDS = 'input[type="password"]:visible'
LOGIN = re.compile(r"^(?:sign in|log in|login)$", re.I)
REGISTER = re.compile(r"^(?:create (?:an? )?account|register|sign up)$", re.I)


def root(browser):
    dialogs = browser.scope.locator('[role="dialog"]:visible, dialog[open]:visible')
    return dialogs.last if dialogs.count() else browser.scope


def context(browser):
    browser._check_page()
    passwords = root(browser).locator(PASSWORDS)
    if not passwords.count(): return None
    mode = "register" if passwords.count() > 1 or passwords.first.get_attribute("autocomplete") == "new-password" else "login"
    origin = urlsplit(browser.page.url)
    fields = browser.observe()
    return {"origin": f"{origin.scheme}://{origin.netloc}", "mode":mode,
        "instructions":browser.page_state()["text"],
        "consents":[{"key":f["key"], "label":f["label"], "required":f["required"]}
                    for f in fields if f["kind"] == "checkbox"]}


def switch_mode(browser, mode, origin):
    current = context(browser)
    if not current or current["origin"] != origin:
        raise BrowserBlocked("The account page changed. Review the current site before continuing.")
    if current["mode"] == mode: return
    pattern = REGISTER if mode == "register" else LOGIN
    # This only opens the alternate account form; it never clicks an account
    # submit button with populated credentials.
    links = root(browser).get_by_role("link", name=pattern).filter(visible=True)
    if not links.count():
        links = root(browser).get_by_role("button", name=pattern).filter(visible=True)
    if links.count() != 1:
        raise BrowserBlocked("Open the desired sign-in or registration form in Chrome, then continue here.")
    links.click()
    browser.page.wait_for_timeout(500)
    latest = context(browser)
    if not latest or latest["origin"] != origin or latest["mode"] != mode:
        raise BrowserBlocked("The account form is still loading or needs browser interaction. Continue after it opens.")


def authenticate(browser, credentials, *, expected=None, active=lambda: True):
    current = context(browser)
    if not current or (expected is not None and current != expected) or current["origin"] != credentials.origin or current["mode"] != credentials.mode:
        raise BrowserBlocked("The account form changed. Review the site and account mode, then try again.")
    choices = credentials.consents
    expected = {f["key"] for f in current["consents"]}
    if set(choices) != expected:
        raise BrowserBlocked("Review each account checkbox in the secure form before continuing.")
    if any(f["required"] and not choices[f["key"]] for f in current["consents"]):
        raise BrowserBlocked("The site requires an account agreement you have not accepted. You can review it in Chrome.")
    scope = root(browser)
    usernames = scope.locator('input[type="email"]:visible, input[autocomplete="username"]:visible, input[name="username"]:visible, input[data-automation-id="email"]:visible')
    passwords = scope.locator(PASSWORDS)
    action = submit_control(browser, credentials.mode)
    if usernames.count() != 1 or passwords.count() not in {1, 2} or action.count() != 1:
        raise BrowserBlocked("This account form needs browser interaction. Complete it in Chrome, then continue here.")
    try:
        usernames.fill(credentials.username)
        for index in range(passwords.count()):
            passwords.nth(index).fill(credentials.password.get_secret_value())
        for key, value in choices.items():
            browser.fill(browser.field(key), value)
        # One attempt only. An ambiguous response never causes automatic account
        # creation or login retries, and exceptions never carry a secret to UI.
        if not active(): raise BrowserBlocked("The account action was paused.")
        action.click(timeout=8000)
        try:
            passwords.first.wait_for(state="hidden", timeout=8000)
        except Exception:
            pass  # Invalid credentials remain a user-visible, retryable pause.
        browser.save_login_state(force=True)
    except Exception:
        raise BrowserBlocked("The account action could not be confirmed. Check the browser before retrying.") from None
    finally:
        # If rejected, do not leave the supplied password in a live DOM.
        try:
            for password in browser.scope.locator(PASSWORDS).all(): password.fill("")
        except Exception:
            pass


def submit_control(browser, mode):
    scope = root(browser)
    forms = scope.locator('form').filter(has=scope.locator(PASSWORDS))
    if forms.count() == 1: scope = forms.first
    pattern = REGISTER if mode == "register" else LOGIN
    action = scope.get_by_role("button", name=pattern).filter(visible=True)
    if not action.count() and browser.platform == "workday":
        # Workday exposes the interactive surface as role=button/"Submit" over
        # an aria-hidden native button. Use that visible surface normally; never
        # force-click the hidden button or invoke its handler.
        native = scope.locator('button[type="submit"][aria-hidden="true"]').filter(has_text=pattern)
        if native.count() == 1:
            action = native.locator('..').locator('[data-automation-id="click_filter"][role="button"]:visible')
    return action

"""DOM actions for public application pages and multi-step candidate workflows.

This adapter never invents answers and never retries a submit click. Dynamic or
unrecognized controls are returned to the candidate for browser interaction.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import socket
import time
from urllib.parse import urlsplit

from .contracts import GREENHOUSE, LEVER, posting, public_https_url
from .matching import resolve_option, search_text
from .navigation import PAGE_SCAN, page_state

SCAN = r"""() => {
  const visible = el => !!(el.getClientRects().length) && getComputedStyle(el).visibility !== 'hidden';
  const clean = text => (text || '').replace(/\s+/g, ' ').trim().slice(0, 1000);
  const label = el => clean(Array.from(el.labels || []).map(x => x.textContent).join(' ') || el.getAttribute('aria-label') ||
    (el.getAttribute('aria-labelledby') || '').split(' ').map(id => document.getElementById(id)?.textContent || '').join(' ') ||
    el.closest('.application-question')?.querySelector('.application-label')?.textContent ||
    el.closest('[data-automation-id^="formField-"]')?.querySelector('label')?.textContent || el.name || el.id);
  const root = [...document.querySelectorAll('[role="dialog"], dialog[open]')].filter(visible).at(-1) || document;
  document.querySelectorAll('[data-northstar-field]').forEach(el => el.removeAttribute('data-northstar-field'));
  const elements = Array.from(root.querySelectorAll('input, textarea, select, [role="combobox"], button[aria-haspopup="listbox"]'));
  const counts = new Map(), fields = [], groups = new Set();
  for (const [index, el] of elements.entries()) {
    if (el.getAttribute('role') === 'combobox' && !['INPUT','BUTTON','SELECT'].includes(el.tagName) && el.querySelector('input:not([type="hidden"])')) continue;
    const kind = el.tagName === 'SELECT' ? 'select' : el.getAttribute('role') === 'combobox' || el.getAttribute('aria-haspopup') === 'listbox' ? 'combobox' :
      el.name === 'location' && el.parentElement.querySelector('input[name="selectedLocation"]') ? 'location' : (el.type || 'text');
    if (['hidden', 'password', 'submit', 'button', 'reset', 'image'].includes(kind) ||
        el.autocomplete === 'one-time-code' || /otp|verificationcode/i.test(el.name || '') || el.disabled ||
        el.getAttribute('data-automation-id') === 'beecatcher' ||
        (kind !== 'file' && (!visible(el) || el.closest('[aria-hidden="true"]')))) continue;
    if (kind === 'file' && !el.closest('form, #application, .application-form, [data-automation-id]')) continue;
    const id = `ns-${index}`; el.setAttribute('data-northstar-field', id);
    const wrapper = el.closest('[data-automation-id^="formField-"], .application-question, .form-field, .field');
    const group = el.closest('fieldset, [role="group"]');
    const sections=[];
    for(let parent=el.parentElement;parent && parent!==root;parent=parent.parentElement){
      const heading=clean(parent.querySelector(':scope > legend, :scope > h2, :scope > h3, :scope > h4, :scope > [data-automation-id="formLabel"]')?.textContent);
      if(heading && !sections.includes(heading))sections.push(heading);
    }
    const described = attr => (el.getAttribute(attr) || '').split(/\s+/).map(id => document.getElementById(id)).filter(Boolean);
    const errors = [...described('aria-errormessage'), ...described('aria-describedby').filter(x => /error/i.test(x.id)),
      ...Array.from(wrapper?.querySelectorAll('[role="alert"], [data-automation-id="errorMessage"], .field-error, .error-message') || [])]
      .filter(visible).map(x => clean(x.textContent)).filter(Boolean);
    if (el.validationMessage) errors.push(el.validationMessage);
    const choice = kind === 'combobox' || kind === 'select' || kind === 'radio' ||
      ['listbox','tree','true'].includes(el.getAttribute('aria-haspopup')) ||
      !!el.closest('[data-automation-id="multiSelectContainer"], [role="combobox"]');
    let committed = false;
    let text = label(el), options = [], value = el.getAttribute('aria-valuetext') || el.value || '', required = el.required || el.getAttribute('aria-required') === 'true';
    let invalid = el.getAttribute('aria-invalid') === 'true' || (!!el.validity && !el.validity.valid) || errors.length > 0;
    let parentRequired = !!el.closest('.application-question.required, [data-required="true"]');
    if (kind === 'radio') {
      const group = el.name || id; if (groups.has(group)) continue; groups.add(group);
      const members = elements.filter(x => x.type === 'radio' && (x.name || `ns-${elements.indexOf(x)}`) === group);
      text = clean(el.closest('fieldset')?.querySelector('legend')?.textContent || el.closest('.application-question')?.querySelector('.application-label')?.textContent || text);
      options = members.map((x) => {const token=`ns-${elements.indexOf(x)}`;x.setAttribute('data-northstar-field',token);return {label:label(x),value:x.value,id:token};});
      value = members.find(x => x.checked)?.value || ''; required = members.some(x => x.required);
    } else if (kind === 'select') options = Array.from(el.options).map(x => ({label: clean(x.textContent), value:x.value, disabled:x.disabled}));
    else if (kind === 'checkbox') {
      const description = clean(el.getAttribute('description') || (el.getAttribute('aria-describedby') || '').split(' ')
        .filter(id => id.endsWith('-description')).map(id => document.getElementById(id)?.textContent || '').join(' '));
      if (description && !text.includes(description)) text = `${description} — ${text}`;
      value = el.checked;
      const peers = elements.filter(x => x.type === 'checkbox' && x.name && x.name === el.name);
      const leverGroup = !!el.closest('[data-qa="checkboxes"]');
      if (peers.length > 1 && (parentRequired || leverGroup)) {
        // Lever marks the question group required; it does not require every
        // language or qualification checkbox to be selected.
        const groupRequired = parentRequired || peers.some(x => x.required);
        invalid = el.getAttribute('aria-invalid') === 'true' || (groupRequired && peers[0] === el && !peers.some(x => x.checked));
        required = false;
        parentRequired = false;
      }
      const groupLabel = clean(el.closest('.application-question')?.querySelector('.application-label')?.textContent);
      if (peers.length > 1 && groupLabel) text = `${groupLabel.replace(/[✱*]/g, '').trim()} — ${text}`;
    } else if (kind === 'file') {
      value = el.files?.length ? el.files[0].name : '';
      if ((el.id === 'resume' || el.name === 'resume')) { text = 'Resume/CV'; required = true; }
    } else if (kind === 'combobox') {
      const shell = el.closest('.select__container, .select-shell');
      if (shell) {value = clean(Array.from(shell.querySelectorAll('.select__single-value, .select__multi-value__label')).map(x => x.textContent).join('; '));committed=!!value;}
      else if (el.tagName === 'BUTTON') {
        value = clean(el.textContent);
        if (/^(select|choose)(?: one| an? option)?(?:\.\.\.)?$/i.test(value)) value = '';
      }
    } else if (kind === 'location') {
      value = el.parentElement.querySelector('input[name="selectedLocation"]').value ? el.value : '';
      text = clean(el.closest('.application-question')?.querySelector('.application-label .text')?.textContent) || 'Current location';
    }
    if (choice && !['select','radio'].includes(kind)) {
      const shell = el.closest('[data-automation-id="multiSelectContainer"], [role="combobox"]');
      const selected = [...(shell?.querySelectorAll('[data-automation-id="selectedItem"], [data-automation-id="selectedItemLabel"], [data-automation-id="selectedPrompt"]') || [])].filter(visible).map(x => clean(x.textContent));
      if (selected.length) {value = [...new Set(selected)].join('; ');committed=true;}
    }
    const base = `${kind}:${el.name || el.id || text}${kind === 'checkbox' ? ':' + el.value : ''}`;
    const occurrence = (counts.get(base) || 0) + 1; counts.set(base, occurrence);
    const key = `${base}:${occurrence}`.slice(0, 1000);
    fields.push({id, dom_id:el.id, name:el.name || '', key, kind, label:text || 'Unlabelled field', required:!!(required || parentRequired || text.includes('*') || text.includes('✱')), options, value, invalid,
      choice_control:choice, value_committed:committed, errors:[...new Set(errors)], help:clean(described('aria-describedby').map(x=>x.textContent).join(' ')),
      group:clean(group?.querySelector('legend')?.textContent || group?.getAttribute('aria-label')), section:sections.join(' / ').slice(0,500),
      constraints:{read_only:!!el.readOnly, pattern:el.getAttribute('pattern'), max_length:el.getAttribute('maxlength'), min_length:el.getAttribute('minlength'),
        placeholder:el.getAttribute('placeholder'), input_mode:el.getAttribute('inputmode'), autocomplete:el.getAttribute('autocomplete')}});
  }
  return fields;
}"""


class BrowserBlocked(RuntimeError):
    """A safe user-facing reason to pause."""


class ApplicationBrowser:
    def __init__(self, url, *, headless=None, session_store=None, owner_key=None):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            # Installing Chrome does not install the Python automation package.
            # Retrying cannot repair a missing dependency in the server's venv.
            raise BrowserBlocked(
                "Browser automation dependencies are missing or incomplete. "
                "Run python -m pip install -r requirements.txt in the same Python "
                "environment used to start the local server, restart the server, "
                "then try again."
            ) from exc
        self.platform, self.identity, self.url = posting(url)
        self.playwright = sync_playwright().start()
        self.browser = None
        self.option_cache = {}
        self.choice_fields = set()
        self._option_owner = None
        self._choice_queries = {}
        self.navigation_hosts = set(GREENHOUSE if self.platform == 'greenhouse' else LEVER if self.platform == 'lever' else {urlsplit(self.url).hostname})
        self.session_store, self.owner_key = session_store, owner_key
        self.session_site = urlsplit(self.url).hostname
        self._dns_cache, self._last_session_save = {}, 0
        self._page_context = None
        self._document_url = None
        try:
            self.browser = self.playwright.chromium.launch(
                channel=os.getenv("JOB_AGENT_BROWSER_CHANNEL", "chrome"),
                headless=headless if headless is not None else False)
            login_state = session_store.load(owner_key, self.session_site) if session_store and owner_key else None
            self.context = self.browser.new_context(viewport={"width": 1280, "height": 900},
                **({"storage_state":login_state} if login_state else {}))
            self.context.set_default_timeout(8000)
            self.context.route("**/*", self._guard_request)
            self.page = self.context.new_page()
            self.context.on("page", self._popup)
            self.page.goto(self.url, wait_until="domcontentloaded", timeout=30_000)
            self.scope = self.page
            # ATS analytics/images can keep `load` pending after the application
            # is usable. Wait for form controls, not every third-party resource.
            from playwright.sync_api import TimeoutError as PlaywrightTimeout
            try:
                self.page.locator('input:not([type="hidden"]), textarea, select, [role="combobox"], button, a[href]').first.wait_for(state="attached", timeout=15_000)
            except PlaywrightTimeout:
                pass  # Keep the page available for challenge/manual inspection.
            self.page.wait_for_timeout(350)
        except BaseException:
            self.close()
            raise

    def _popup(self, page):
        self.page = page
        self.option_cache.clear()

    def save_login_state(self, *, force=False):
        if not self.session_store or not self.owner_key or not hasattr(self, "page") or not self.is_open(): return
        if not force and time.monotonic() - self._last_session_save < 10: return
        self._last_session_save = time.monotonic()
        try:
            state = self.context.storage_state()
            self.session_store.save(self.owner_key, self.session_site, state)
        except Exception:
            pass  # Browsing still works if secure local persistence is unavailable.

    def _public_host(self, host):
        if host not in self._dns_cache:
            try:
                addresses = {item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
                self._dns_cache[host] = bool(addresses) and all(ipaddress.ip_address(a).is_global for a in addresses)
            except OSError:
                self._dns_cache[host] = False
        return self._dns_cache[host]

    def _guard_request(self, route):
        url = urlsplit(route.request.url)
        host = url.hostname or ""
        blocked = host in {"localhost", "metadata.google.internal"} or host.endswith((".localhost", ".local"))
        try:
            blocked = blocked or not ipaddress.ip_address(host).is_global
        except ValueError:
            pass
        if route.request.is_navigation_request():
            # Top-level redirects and embedded application frames stay on the
            # selected ATS. CAPTCHA providers may use their own child frames.
            if route.request.frame == self.page.main_frame:
                blocked = blocked or host not in self.navigation_hosts or url.scheme != "https"
        if blocked or url.scheme not in {"http", "https"} or not self._public_host(host):
            route.abort()
        else:
            route.continue_()

    def _check_page(self):
        if self.page.is_closed():
            raise BrowserBlocked("The browser was closed. Continue to reopen the application.")
        allowed = self.navigation_hosts
        if urlsplit(self.page.url).hostname not in allowed:
            raise BrowserBlocked("The application navigated outside the supported site.")
        try:
            identity = posting(self.page.url)[1]
        except ValueError:
            identity = self.identity  # ATS-specific confirmation path is checked separately.
        if self.platform in {"greenhouse", "lever", "workday"} and identity != self.identity and ("/job/" in self.page.url or self.platform != "workday"):
            raise BrowserBlocked("The browser is showing a different job. Reopen this attempt.")
        self.scope = self.page
        for frame in self.page.frames[1:]:
            if urlsplit(frame.url).hostname in allowed and frame.locator('input[type="email"]').count():
                self.scope = frame
                break
        if self._document_url != self.page.url:
            self._document_url = self.page.url
            self.option_cache.clear()
            self._choice_queries.clear()

    def page_state(self):
        fields = self.observe()
        raw = self.scope.evaluate(PAGE_SCAN)
        self._page_context = page_state(raw, url=self.page.url, fields=fields)
        return self._page_context

    def click_page_action(self, action):
        # Re-identify the exact observed target, not its ephemeral DOM index.
        page = self.page_state()
        candidates = [c for c in page["controls"] if all(c.get(k) == action.get(k)
            for k in ("label", "href", "automation_id", "kind")) and not c["disabled"]]
        target = next((c for c in candidates if c["id"] == action["id"]), None)
        if target is None or action["kind"] in {"submit", "unavailable"}:
            raise BrowserBlocked("This navigation control changed or requires final submission review.")
        if target.get("href"):
            url = public_https_url(target["href"])
            # Clicking a visible application link may transfer from a company's
            # career site to its ATS. Never grant a model-supplied arbitrary URL.
            self.navigation_hosts.add(urlsplit(url).hostname)
        locator = self.scope.locator(f'[data-northstar-action="{target["id"]}"]')
        locator.click(timeout=8000)
        self.page.wait_for_timeout(400)
        if self.platform == "workday" and "/apply/" in self.page.url:
            # Workday's route shell renders before its account/application step.
            # Wait for that step, not the always-present header Sign In button.
            try:
                self.page.locator('input:visible, textarea:visible, [data-automation-id="SignInWithEmailButton"]:visible, [data-automation-id="pageHeaderTitle"]:visible').first.wait_for(timeout=8000)
            except Exception:
                pass
        self.option_cache.clear()
        self._check_page()
        self.save_login_state()

    def observe(self):
        self._check_page()
        fields = self.scope.evaluate(SCAN)
        if len(fields) > 100:
            raise BrowserBlocked("This form has too many controls for this release. Complete it manually.")
        for field in fields:
            if field["key"] in self.choice_fields:
                field["choice_control"] = True
            if field["key"] in self._choice_queries:
                field["search_text"] = self._choice_queries[field["key"]]
                if str(field["value"]) == self._choice_queries[field["key"]] and not field.get("value_committed"):
                    field["value"] = "" # Search text is not a committed selection.
                elif field["value"]:
                    self._choice_queries.pop(field["key"],None)
            if field["kind"] in {"combobox", "location"} or field.get("choice_control") and field["kind"] not in {"select", "radio"}:
                field["options"] = self.option_cache.get(field["key"], [])
        return fields

    def pump(self):
        if self.is_open():
            self.page.wait_for_timeout(50)

    def field(self, key):
        field = next((item for item in self.observe() if item["key"] == key), None)
        if field is None:
            raise BrowserBlocked("The form changed. Observe the page again.")
        return field

    def locate(self, field):
        # React hydration can discard our observation markers. Prefer persistent
        # IDs, then unique names, before using the temporary marker.
        if field.get("dom_id"):
            return self.scope.locator(f'[id={json.dumps(field["dom_id"])}]')
        if field.get("name") and field["kind"] not in {"radio", "checkbox"}:
            named = self.scope.locator(f'[name={json.dumps(field["name"])}]')
            if named.count() == 1:
                return named
        return self.scope.locator(f'[data-northstar-field="{field["id"]}"]')

    def click_field(self, key):
        field = self.field(key)
        if field["kind"] in {"checkbox", "radio", "file", "password"}:
            raise BrowserBlocked("Use an explicit answer to change this field.")
        locator = self.locate(field)
        if locator.evaluate("el => el.tagName === 'BUTTON' && el.type !== 'button'"):
            raise BrowserBlocked("Browser tools cannot click submit controls.")
        locator.click(timeout=5000)
        self._option_owner = key

    def _option_locator(self, field):
        locator = self.locate(field)
        owner = locator.get_attribute("aria-controls") or locator.get_attribute("aria-owns")
        if owner:
            for item in owner.split():
                root = self.scope.locator(f'[id={json.dumps(item)}]')
                if root.count():
                    choices = root.locator('[role="option"]:visible, [role="treeitem"]:visible, [role="menuitem"]:visible, [data-automation-id="promptOption"]:visible, [data-automation-id="promptLeafNode"]:visible')
                    return choices
        if field["kind"] == "location":
            return self.scope.locator('.dropdown-results > *:visible')
        # Some select libraries portal the sole open menu to document.body.
        menus = self.scope.locator('[role="listbox"]:visible, [role="tree"]:visible, [role="menu"]:visible, [data-automation-id="promptOptionList"]:visible')
        if menus.count() == 1:
            return menus.locator('[role="option"]:visible, [role="treeitem"]:visible, [role="menuitem"]:visible, [data-automation-id="promptOption"]:visible, [data-automation-id="promptLeafNode"]:visible')
        return self.scope.locator('.select__menu:visible .select__option')

    def inspect_options(self, key, query=None):
        field = self.field(key)
        if field["kind"] in {"select", "radio"}:
            return field["options"]
        if field["kind"] not in {"combobox", "location", "text", "search", "tel"}:
            return []
        locator = self.locate(field)
        # A second click closes an open React Select before a search can run.
        if query is None and key in self._choice_queries and locator.is_editable():
            locator.fill("")
            self._choice_queries.pop(key,None)
        if (self._option_owner != key and locator.get_attribute("aria-expanded") != "true") or not self._option_locator(field).count():
            self.click_field(key)
        self._option_owner = key
        if query and locator.is_editable():
            locator.fill(str(query))
            self._choice_queries[key] = str(query)
        options = self._option_locator(field)
        try:
            options.first.wait_for(state="visible", timeout=4000)
        except Exception:
            return []
        return self._read_options(key, options)

    def _read_options(self, key, options):
        items = options.evaluate_all("""els => els.slice(0,300).map(el => ({
            label:(el.getAttribute('aria-label') || el.innerText || '').trim(),
            value:(el.getAttribute('data-value') || el.innerText || '').trim(),
            role:el.getAttribute('role'), automation_id:el.getAttribute('data-automation-id'),
            expandable:el.hasAttribute('aria-expanded') || !!el.querySelector('[aria-expanded], [aria-haspopup]'),
            disabled:el.getAttribute('aria-disabled') === 'true'}))""")
        if items: self.choice_fields.add(key)
        self.option_cache[key] = items
        return items

    def explore_option(self, key, label):
        query = self._choice_queries.get(key)
        self.choose_option(key, label)
        if query is not None: self._choice_queries[key] = query
        self.page.wait_for_timeout(200)
        # Read the new level without clicking the field again (which can close
        # the popup or jump back to its root).
        return self._read_options(key, self._option_locator(self.field(key)))

    def choose_option(self, key, label):
        field = self.field(key)
        from .autofill import matches as field_matches
        if field_matches(field, label):
            return
        if field["kind"] in {"select", "radio"}:
            return self.fill(field, label)
        options = self._option_locator(field)
        # Match only the active field's observed options, never a global text hit.
        choices = options.evaluate_all("""els => els.map(el => ({
            label:(el.getAttribute('aria-label') || el.innerText || '').trim(),
            value:(el.getAttribute('data-value') || el.innerText || '').trim(),
            expandable:el.hasAttribute('aria-expanded') || !!el.querySelector('[aria-expanded], [aria-haspopup]'),
            disabled:el.getAttribute('aria-disabled') === 'true'}))""")
        matching = [(index, item) for index, item in enumerate(choices) if item['label'].strip().casefold() == label.strip().casefold() and not item['disabled']]
        if not matching or resolve_option(field["label"], label, [item for _, item in matching]) is None:
            raise BrowserBlocked("The option changed or is ambiguous. Inspect the field again.")
        options.nth(matching[0][0]).click(timeout=5000)
        if not matching[0][1]['expandable']: self._choice_queries.pop(key,None)
        self.page.wait_for_timeout(150)

    def type_field(self, key, value):
        field = self.field(key)
        if field["kind"] not in {"text", "email", "tel", "url", "textarea", "number", "search", "combobox", "location"}:
            raise BrowserBlocked("This field does not accept text.")
        locator = self.locate(field)
        locator.fill("")
        locator.press_sequentially(str(value), delay=10, timeout=8000)
        if field.get("choice_control") or field["kind"] in {"combobox","location"}:
            self._choice_queries[key] = str(value)
        if field["kind"] not in {"combobox", "location"}:
            locator.press("Tab")
        self.page.wait_for_timeout(150)

    def press_key(self, key, value):
        if value not in {"ArrowDown", "ArrowUp", "Escape", "Tab"}:
            raise BrowserBlocked("That key is not available to the form agent.")
        self.locate(self.field(key)).press(value)

    def screenshot_field(self, key):
        locator = self.locate(self.field(key))
        # Crop to the surrounding control. Never capture other browser tabs.
        return locator.locator("..").screenshot(type="png", timeout=5000)

    def preview(self):
        return self.page.screenshot(type="jpeg", quality=55, timeout=2000,
            mask=[self.page.locator('input[type="password"], input[autocomplete="one-time-code"], input[name*="otp" i], input[name*="verificationCode" i]')])

    def enrich_options(self, fields, *, active=lambda: True):
        deadline = time.monotonic() + 20
        for field in fields:
            if not active() or time.monotonic() >= deadline:
                break
            if field["kind"] == "combobox" and not field["value"] and not field["options"]:
                try:
                    self.inspect_options(field["key"])
                    self.press_key(field["key"], "Escape")
                except Exception:
                    pass
        return self.observe()

    def is_open(self):
        return not self.page.is_closed()

    def barrier(self):
        if self.scope.locator('input[type="password"]:visible').count():
            return "This site requires a candidate account. Use the secure account form to let the agent sign in or register. Keep your password out of chat."
        if self.scope.locator('input[autocomplete="one-time-code"]:visible, input[name*="verificationCode" i]:visible').count():
            return "Complete the site's email verification in the open Chrome window, then send continue here."
        if self.scope.get_by_text(re.compile(r"^(?:check your email|verify your email(?: address)?|verify your account)$", re.I)).count():
            return "Complete the site's email verification, then send continue here. Your application will resume in this browser."
        # An embedded CAPTCHA widget alone is not evidence of a challenge.
        if self.page.locator('iframe[title*="challenge" i]:visible, iframe[title*="verification" i]:visible').count():
            return "Complete the verification challenge in the open browser, then continue."
        return None

    def fill(self, field, value):
        field = self.field(field["key"])
        from .autofill import matches
        if field["kind"] != "file" and matches(field, value):
            return
        locator = self.locate(field)
        kind = field["kind"]
        if kind == "file":
            locator.set_input_files({"name": "resume.pdf", "mimeType": "application/pdf", "buffer": value})
        elif kind == "checkbox":
            if not isinstance(value, bool):
                raise BrowserBlocked("Choose a checkbox answer explicitly.")
            locator.set_checked(value)
        elif kind in {"select", "radio"}:
            option = resolve_option(field["label"], value, field["options"])
            if option is None:
                raise BrowserBlocked("Choose an exact option from the application form.")
            if kind == "select":
                locator.select_option(value=option["value"])
            else:
                self.scope.locator(f'[data-northstar-field="{option["id"]}"]').check()
        elif kind == "combobox" or field.get("choice_control"):
            options = self.inspect_options(field["key"])
            option = resolve_option(field["label"], value, options)
            if option is None:
                options = self.inspect_options(field["key"], query=search_text(field["label"], value))
                option = resolve_option(field["label"], value, options)
            if option is None:
                raise BrowserBlocked("Select an option from this field's available choices.")
            self.choose_option(field["key"], option["label"])
        elif kind == "location":
            locator.fill(str(value))
            option = self.scope.locator('.dropdown-results').get_by_text(str(value), exact=True)
            try:
                option.wait_for(state="visible", timeout=5000)
                if option.count() != 1:
                    raise BrowserBlocked("Choose the intended location suggestion in the browser, then continue.")
                option.click()
            except Exception as exc:
                raise BrowserBlocked("Choose the intended location suggestion in the browser, then continue.") from exc
        elif kind in {"text", "email", "tel", "url", "textarea", "number", "search"}:
            locator.fill(str(value))
            locator.press("Tab")
        else:
            raise BrowserBlocked("Complete this control in the browser, then continue.")
        self.page.wait_for_timeout(200)

    def confirmation(self):
        self._check_page()
        selectors = ('#application_confirmation, .application-confirmation, .application-success, '
                     '[data-testid="application-confirmation"], [data-automation-id="applicationConfirmation"], '
                     '[data-automation-id="applicationSubmitted"], [data-automation-id="successMessage"]')
        for container in (self.scope, self.page):
            matches = container.locator(selectors)
            for index in range(matches.count()):
                element = matches.nth(index)
                if element.is_visible():
                    text = element.inner_text().strip()
                    if re.search(r"application (?:has been |was )?(?:submitted|received)|thank you for applying", text, re.I):
                        return {"url": self.page.url, "text": text[:400]}
        return None

    def submit(self):
        self._check_page()
        page = self.page_state()
        buttons = [c for c in page["controls"] if c["kind"] == "submit" and not c["disabled"]]
        if not page["can_submit"] or len(buttons) != 1:
            raise BrowserBlocked("A single final submit button could not be identified.")
        button = self.scope.locator(f'[data-northstar-action="{buttons[0]["id"]}"]')
        button.click(timeout=8000)  # Exactly one attempt, even if the response times out.

    def wait_confirmation(self):
        import time
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            proof = self.confirmation()
            if proof:
                return proof
            self.page.wait_for_timeout(500)
        return None

    def close(self):
        try:
            if self.browser is not None:
                self.save_login_state(force=True)
                self.browser.close()
        finally:
            self.playwright.stop()


def form_digest(fields):
    return hashlib.sha256(json.dumps([
        {key: field.get(key) for key in ("key", "label", "kind", "value", "required", "options")}
        for field in fields], sort_keys=True).encode()).hexdigest()

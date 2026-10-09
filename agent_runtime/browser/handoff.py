"""User-only control of an existing local browser; never a model tool.

Inputs and screenshots are ephemeral. The caller fences the task and dispatches
on the browser's owning thread before reaching this module.
"""
import base64
import time
from uuid import uuid4
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Literal

from agent_runtime.auto_apply.errors import BrowserBlocked


KEYS = {'Tab', 'Shift+Tab', 'Enter', 'Escape', 'Backspace', 'Delete',
        'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Home', 'End',
        'PageUp', 'PageDown', 'ControlOrMeta+A'}


class BrowserControlRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['start', 'frame', 'click', 'drag', 'scroll', 'key', 'text', 'tab', 'end']
    expected_version: int | None = Field(default=None, ge=1)
    session: str | None = Field(default=None, min_length=32, max_length=64)
    frame_id: str | None = Field(default=None, min_length=32, max_length=64)
    x: float | None = Field(default=None, ge=0, le=20000, allow_inf_nan=False)
    y: float | None = Field(default=None, ge=0, le=20000, allow_inf_nan=False)
    end_x: float | None = Field(default=None, ge=0, le=20000, allow_inf_nan=False)
    end_y: float | None = Field(default=None, ge=0, le=20000, allow_inf_nan=False)
    delta_y: float | None = Field(default=None, ge=-4000, le=4000, allow_inf_nan=False)
    key: str | None = Field(default=None, max_length=32)
    text: str | None = Field(default=None, min_length=1, max_length=2000, repr=False)
    tab_id: str | None = Field(default=None, min_length=32, max_length=64)

    @model_validator(mode='after')
    def required_arguments(self):
        required = {'start': ('expected_version',), 'click': ('x', 'y'),
                    'drag': ('x', 'y', 'end_x', 'end_y'), 'scroll': ('delta_y',),
                    'key': ('key',), 'text': ('text',), 'tab': ('tab_id',)}
        if any(getattr(self, k) is None for k in required.get(self.action, ())):
            raise ValueError('Missing browser control arguments.')
        if self.action != 'start' and not self.session:
            raise ValueError('Start browser control first.')
        if self.action not in {'start', 'frame', 'end'} and not self.frame_id:
            raise ValueError('Refresh the browser image first.')
        if self.action == 'key' and self.key not in KEYS:
            raise ValueError('Unsupported browser key.')
        return self


class LocalBrowserControl:
    def __init__(self, browser, scope):
        self.browser, self.scope = browser, scope
        self.session = uuid4().hex
        self.frame_id, self.page, self.url = None, None, None
        self.expires = time.monotonic() + 600
        self.tabs = {}
        self.watched = set()

    def _invalidate(self, *_):
        self.frame_id = None

    def frame(self):
        browser = self.browser
        if not browser.is_open():
            raise BrowserBlocked('The browser is closed. Close this view and resume the task.')
        browser._check_page()
        page = browser.page
        for tab in browser.context.pages:
            if tab.is_closed():
                continue
            if tab not in self.tabs.values():
                self.tabs[uuid4().hex] = tab
            if tab not in self.watched:
                tab.on('framenavigated', self._invalidate)
                self.watched.add(tab)
        self.tabs = {k: p for k, p in self.tabs.items() if not p.is_closed()}
        size = page.viewport_size or page.evaluate('({width:innerWidth,height:innerHeight})')
        # The existing preview masks passwords and one-time codes in all frames.
        image = browser.preview()
        self.page, self.url, self.size = page, page.url, size
        self.frame_id = uuid4().hex
        self.expires = time.monotonic() + 600
        return {'session': self.session, 'frame_id': self.frame_id,
                'image': 'data:image/jpeg;base64,' + base64.b64encode(image).decode('ascii'),
                **size, 'url': self._display_url(page.url),
                'tabs': [{'id': k, 'url': self._display_url(p.url), 'active': p == page}
                         for k, p in self.tabs.items()]}

    @staticmethod
    def _display_url(url):
        parts = urlsplit(url)
        return f'{parts.scheme}://{parts.netloc}{parts.path}'[:500]

    def act(self, request):
        if (request.frame_id != self.frame_id or not self.frame_id
                or self.page != self.browser.page or self.page.is_closed()
                or self.page.url != self.url):
            raise BrowserBlocked('The page changed. Refresh the browser view before acting.')
        page = self.page
        for x, y in ((request.x, request.y), (request.end_x, request.end_y)):
            if x is not None and (x >= self.size['width'] or y is None or y >= self.size['height']):
                raise BrowserBlocked('Choose a point inside the current browser image.')
        self.frame_id = None  # A frame can authorize at most one input action.
        if request.action == 'click':
            page.mouse.click(request.x, request.y)
        elif request.action == 'drag':
            page.mouse.move(request.x, request.y)
            page.mouse.down()
            try:
                page.mouse.move(request.end_x, request.end_y, steps=12)
            finally:
                page.mouse.up()
        elif request.action == 'scroll':
            if request.x is not None and request.y is not None:
                page.mouse.move(request.x, request.y)
            page.mouse.wheel(0, request.delta_y)
        elif request.action == 'key':
            page.keyboard.press(request.key)
        elif request.action == 'text':
            # Retain the mask if a site's Show password button changes the type.
            for frame in page.frames:
                try:
                    frame.evaluate("""() => {
                        let e=document.activeElement;
                        while(e?.shadowRoot?.activeElement)e=e.shadowRoot.activeElement;
                        if(e?.matches('input[type="password"],input[autocomplete="current-password"],input[autocomplete="new-password"],input[autocomplete="one-time-code"]'))
                            e.setAttribute('data-northstar-secret','true');
                    }""")
                except Exception:
                    pass  # Detached frames cannot be the active input target.
            page.keyboard.insert_text(request.text)
        elif request.action == 'tab':
            target = self.tabs.get(request.tab_id)
            if target is None or target.is_closed():
                raise BrowserBlocked('This tab is closed. Refresh the browser view.')
            self.browser.page = self.browser.scope = target
        page.wait_for_timeout(100)

    def close(self):
        for page in self.watched:
            page.remove_listener('framenavigated', self._invalidate)
        self.frame_id = None


def control_browser(browser, request, scope):
    """Scope includes task revision; resume/new feedback revokes old controls."""
    control = getattr(browser, '_local_control', None)
    if request.action == 'start':
        if control:
            control.close()
        control = browser._local_control = LocalBrowserControl(browser, scope)
    elif (not control or control.scope != scope or request.session != control.session
          or time.monotonic() > control.expires):
        raise BrowserBlocked('Browser control expired or the task resumed. Close this view and take control again.')
    if request.action == 'end':
        control.close()
        browser._local_control = None
        return {'closed': True}
    if request.action not in {'start', 'frame'}:
        control.act(request)
    return control.frame()

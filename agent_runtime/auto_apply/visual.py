"""Screenshot coordinates and real mouse/keyboard input in the application tab.

The model chooses targets from pixels. DOM hit testing here only enforces the
existing account/submission boundaries; it does not choose dropdown options.
Screenshots and their freshness tokens are ephemeral, never application memory.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from uuid import uuid4

from .browser import BrowserBlocked
from .navigation import action_kind

SECRET_SELECTOR = ('input[type="password"], input[autocomplete="one-time-code"], '
                   'input[name*="otp" i], input[name*="verificationCode" i]')

SCREEN_STATE = r"""() => ({url:location.href, width:innerWidth, height:innerHeight,
  scroll:[scrollX,scrollY], text:document.body?.innerText,
  scrolled:[...document.querySelectorAll('*')].filter(e=>e.scrollTop || e.scrollLeft)
    .map(e=>[e.tagName,e.id,e.scrollTop,e.scrollLeft]),
  controls:[...document.querySelectorAll('input,textarea,select,button,a,[role],[onclick],canvas,iframe')]
    .filter(e=>e.getClientRects().length).map(e=>{
      const r=e.getBoundingClientRect();
      return [e.tagName,e.id,e.getAttribute('role'),e.type==='password'?'':e.value,
        e.checked,e.getAttribute('aria-expanded'),e.scrollTop,e.scrollLeft,
        ...[r.x,r.y,r.width,r.height].map(Math.round)];})})"""

TARGET = r"""el => {
  const actionable=el.closest('button,a[href],input,textarea,select,[role="button"],[role="checkbox"],[role="radio"],label') || el;
  const e=actionable.tagName==='LABEL' && actionable.control ? actionable.control : actionable;
  return {tag:e.tagName, type:e.type || '', role:e.getAttribute('role') || '',
    label:(e.getAttribute('aria-label') || [...(e.labels || [])].map(l=>l.innerText).join(' ') || e.innerText || '').trim().slice(0,500),
    href:e.tagName==='A'?e.href:null, automation_id:e.getAttribute('data-automation-id'),
    action_id:e.getAttribute('data-northstar-action'), field_id:e.getAttribute('data-northstar-field'),
    expanded:e.getAttribute('aria-expanded')==='true',
    submits_form:(e.tagName==='BUTTON' || e.tagName==='INPUT') && ['submit','image'].includes(e.type) && !!e.form,
    secret:e.type==='password' || e.autocomplete==='one-time-code' || /otp|verificationcode/i.test(e.name || ''),
    editable:!e.readOnly && (e.isContentEditable || e.tagName==='TEXTAREA' || (e.tagName==='INPUT' && !['checkbox','radio','file','submit','button','hidden'].includes(e.type))),
    disabled:!!e.disabled || e.getAttribute('aria-disabled')==='true',
    choice:!!e.closest('[role="listbox"],[role="tree"],[role="menu"]') ||
      ['option','treeitem','menuitem'].includes(e.getAttribute('role')),
    checked:e.checked ?? e.getAttribute('aria-checked')};
}"""


class VisualBrowser:
    def __init__(self, browser):
        self.browser = browser
        self.screen = None
        self._stamp = None
        self._captured = 0

    @property
    def page(self):
        return self.browser.page

    def invalidate(self):
        self.screen = None

    def _check(self):
        self.browser._check_page()
        if self.browser.barrier():
            raise BrowserBlocked("Use the secure account form or manual verification before visual actions.")

    def _fingerprint(self):
        states = [frame.evaluate(SCREEN_STATE) for frame in self.page.frames]
        return hashlib.sha256(json.dumps(states, sort_keys=True).encode()).hexdigest()

    def capture(self):
        self._check()
        self.browser.observe()
        # CSS pixels make screenshot coordinates identical to Playwright input,
        # including high-DPI displays. Never resize without a coordinate map.
        masks = [frame.locator(SECRET_SELECTOR) for frame in self.page.frames]
        before = self._fingerprint()
        data = self.page.screenshot(type="png", full_page=False, scale="css", mask=masks, timeout=5000)
        after = self._fingerprint()
        size = self.page.evaluate("() => ({width:innerWidth,height:innerHeight})")
        if len(data) > 6_000_000:
            raise BrowserBlocked("The viewport image is too large. Reduce the application window size.")
        self.screen = {"screenshot_id":str(uuid4()), **size, "coordinate_system":"normalized_1000",
            "coordinate_mapping":"pixel_x=x*width/1000; pixel_y=y*height/1000; origin=top-left"}
        self._stamp, self._captured = after if before == after else None, time.monotonic()
        return {"image":data, "screen":self.screen}

    def validate(self, screenshot_id):
        self._check()
        if not self.screen or screenshot_id != self.screen["screenshot_id"] or time.monotonic()-self._captured > 120 or self._stamp != self._fingerprint():
            self.invalidate()
            raise BrowserBlocked("The screenshot is stale. Call view_browser for a fresh image before acting.")

    def point(self, x, y):
        if (not self.screen or any(isinstance(n,bool) or not isinstance(n,(int,float)) or not math.isfinite(n) for n in (x,y))
            or not 0 <= x < 1000 or not 0 <= y < 1000):
            raise BrowserBlocked("Coordinates must be within 0..1000 on the normalized screenshot grid.")
        return x*self.screen["width"]/1000, y*self.screen["height"]/1000

    def target(self, x, y):
        x,y = self.point(x,y)
        frame, px, py = self.page.main_frame, x, y
        # Coordinates are always relative to the outer viewport; hit testing
        # descends into same-tab frames, without supplying selectors to the model.
        for _ in range(8):
            handle = frame.evaluate_handle("""({x,y}) => {
                let e=document.elementFromPoint(x,y);
                while(e?.shadowRoot){const child=e.shadowRoot.elementFromPoint(x,y);if(!child || child===e)break;e=child;}
                return e;}""", {"x":px,"y":py}).as_element()
            if handle is None: raise BrowserBlocked("No visible target at these coordinates.")
            try:
                info = handle.evaluate(TARGET)
                child = handle.content_frame() if info["tag"] in {"IFRAME","FRAME"} else None
                if child is None: return info
                box = handle.bounding_box()
                inset = handle.evaluate("e=>({x:e.clientLeft,y:e.clientTop})")
                px, py = x-box["x"]-inset["x"], y-box["y"]-inset["y"]
                frame = child
            finally:
                handle.dispose()
        raise BrowserBlocked("The target is inside too many nested frames.")

    def focused(self):
        frame = self.page.main_frame
        for _ in range(8):
            handle = frame.evaluate_handle("""() => {let e=document.activeElement;
                while(e?.shadowRoot?.activeElement)e=e.shadowRoot.activeElement;return e;}""").as_element()
            if handle is None: raise BrowserBlocked("Focus a visible control first.")
            try:
                info = handle.evaluate(TARGET)
                child = handle.content_frame() if info["tag"] in {"IFRAME","FRAME"} else None
                if child is None: return info
                frame = child
            finally:
                handle.dispose()
        raise BrowserBlocked("Cannot identify the focused control.")

    @staticmethod
    def guard(target):
        kind = action_kind(target, has_fields=True)
        if target["secret"] or target["type"] == "file" or kind == "authentication":
            raise BrowserBlocked("Use the dedicated credential/upload tools for this control.")
        if kind == "submit" or target["submits_form"] and kind != "next":
            raise BrowserBlocked("Final submission requires application review; visual actions cannot submit.")
        if target["disabled"]:
            raise BrowserBlocked("This visual target is disabled.")

    def perform(self, name, args, *, text=None):
        # The caller validates freshness and semantic/source permissions first.
        if 'x' in args:
            args={**args}
            args['x'],args['y']=self.point(args['x'],args['y'])
            if name=='computer_drag':
                args['end_x'],args['end_y']=self.point(args['end_x'],args['end_y'])
        self.invalidate()
        if name == "computer_click":
            self.page.mouse.click(args["x"],args["y"],click_count=args["click_count"])
        elif name == "computer_move":
            self.page.mouse.move(args["x"],args["y"])
        elif name == "computer_scroll":
            self.page.mouse.move(args["x"],args["y"])
            self.page.mouse.wheel(args["delta_x"],args["delta_y"])
        elif name == "computer_drag":
            self.page.mouse.move(args["x"],args["y"])
            self.page.mouse.down()
            try: self.page.mouse.move(args["end_x"],args["end_y"],steps=12)
            finally: self.page.mouse.up()
        elif name == "computer_type":
            if args["replace"]: self.page.keyboard.press("ControlOrMeta+A")
            self.page.keyboard.insert_text(str(text))
        elif name == "computer_key":
            self.page.keyboard.press(args["key"])
        self.page.wait_for_timeout(350 if name != "computer_wait" else 800)
        self.browser.option_cache.clear()
        return self.capture()

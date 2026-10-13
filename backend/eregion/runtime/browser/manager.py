"""Serialize browser I/O on its owning thread and preserve task-scoped sessions."""
import time
from threading import RLock

from eregion.runtime.auto_apply.browser import ApplicationBrowser, BrowserBlocked
from eregion.runtime.auto_apply.worker import BrowserWorker
from .session import BrowserSession
from .tools import execute, VISUAL_NAMES


class BrowsingManager:
    def __init__(self, *, factory=None):
        self.factory = factory or (lambda url:ApplicationBrowser(url,purpose='browse'))
        self.sessions, self.states, self.previews = {},{},{}
        self.preview_times = {}
        self.lock = RLock()
        self.closed = False
        self.worker = BrowserWorker(self._pump)

    def _pump(self):
        for session in list(self.sessions.values()):
            try:session.browser.pump()
            except Exception:pass
        for task_id,session in list(self.sessions.items()):
            if time.monotonic()-self.preview_times.get(task_id,0)>=2:self._preview(task_id,session)

    def _preview(self,task_id,session):
        self.preview_times[task_id]=time.monotonic()
        try:
            image=session.browser.preview()
            with self.lock:self.previews[task_id]=image
        except Exception:pass

    def inspect(self,task_id):
        with self.lock:return self.states.get(task_id)

    def preview(self,task_id):
        with self.lock:return self.previews.get(task_id)

    def call(self,task_id,name,args,*,visual=False,active=lambda:True):
        if self.closed:raise BrowserBlocked('The browser service is stopping.')
        if name in VISUAL_NAMES and not visual:raise BrowserBlocked('Enable visual browser backup before taking a model screenshot.')
        return self.worker.submit(self._execute,task_id,name,args,active).result()

    def _execute(self,task_id,name,args,active):
        if not active():raise BrowserBlocked('New feedback or a pause arrived. Read the current task before browsing.')
        session = self.sessions.get(task_id)
        if session and not session.browser.is_open():
            session.browser.close();self.sessions.pop(task_id,None);session=None
        try:
            if session is None:
                if name!='browser_open':raise BrowserBlocked('Open a page with browser_open first. Browser tabs are recreated after a server restart.')
                session = BrowserSession(self.factory(args['url']))
                self.sessions[task_id] = session
                result = session.read()
            else:
                result = execute(session,name,args)
        except Exception as exc:
            if type(exc).__name__!='TargetClosedError' or not active():raise
            # One bounded recovery of a lost transport. Navigation is a safe GET;
            # other effects are never replayed. It is not a website auth block.
            url = args.get('url') if name=='browser_open' else (self.states.get(task_id) or {}).get('url')
            if not url:raise
            if session:
                try:session.browser.close()
                except Exception:pass
            self.sessions.pop(task_id,None)
            session = BrowserSession(self.factory(url))
            self.sessions[task_id] = session
            result = {**session.read(), 'recovery':{'kind':'closed_session','cause':'TargetClosedError',
                'attempts':1,'requested_tool':name,'action_replayed':False},
                'action_performed':name=='browser_open',
                'next':'Browser transport was recreated once. This is a fresh observation, not a site restriction. No previous click, typing, or other effect was replayed; choose a fresh control if still needed.'}
        with self.lock:self.states[task_id] = {k:v for k,v in result.items() if k!='image'}
        self._preview(task_id,session)
        return result

    def close_task(self,task_id):
        def close():
            session=self.sessions.pop(task_id,None)
            if session:session.browser.close()
            with self.lock:
                self.states.pop(task_id,None);self.previews.pop(task_id,None)
                self.preview_times.pop(task_id,None)
        return self.worker.submit(close)

    def set_visible(self,task_id,visible,*,active=lambda:True):
        def change():
            if not active():raise BrowserBlocked('The task changed. Refresh before switching browser mode.')
            session=self.sessions.get(task_id)
            if not session:raise BrowserBlocked('No research browser is open for this conversation yet.')
            session.browser.set_visible(visible)
            session=BrowserSession(session.browser)
            self.sessions[task_id]=session
            result=session.read()
            with self.lock:self.states[task_id]=result
            self._preview(task_id,session)
            return result
        return self.worker.submit(change).result()

    def browser_control(self, task_id, request, *, scope, active):
        from .handoff import control_browser
        def control():
            if self.closed or not active():
                raise BrowserBlocked('The task resumed or changed. Take control again.')
            session = self.sessions.get(task_id)
            if not session:
                raise BrowserBlocked('No research browser is open. Resume the task first.')
            session.observation = session.screen = None
            result = control_browser(session.browser, request, scope)
            if request.action=='end':
                # Control invalidates the old observation, but inspect() reads
                # states rather than preview pixels. Capture the actual page
                # once on this explicit user event before the agent resumes.
                observed=session.read()
                with self.lock:self.states[task_id]={k:v for k,v in observed.items() if k!='image'}
            self._preview(task_id, session)
            return result
        return self.worker.submit(control).result()

    def close(self):
        if self.closed:return
        self.closed=True
        self.worker.submit(lambda:[s.browser.close() for s in self.sessions.values()]).result()
        self.worker.shutdown()

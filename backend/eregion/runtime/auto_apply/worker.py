"""Keep Playwright's synchronous event pump alive while waiting for the user."""
from concurrent.futures import Future
from queue import Empty, Queue
from threading import Thread
from contextvars import copy_context


class BrowserWorker:
    def __init__(self, idle, *, name="application-browser"):
        self.queue = Queue()
        self.idle = idle
        self.thread = Thread(target=self._run, name=name, daemon=True)
        self.thread.start()

    def submit(self, function, *args):
        future = Future()
        self.queue.put((future, copy_context().run, (function, *args)))
        return future

    def _run(self):
        from .browser import start_worker_browsers, stop_worker_browsers
        start_worker_browsers()
        try:
            self._dispatch()
        finally:
            stop_worker_browsers()

    def _dispatch(self):
        while True:
            try:
                item = self.queue.get(timeout=.05)
            except Empty:
                try:
                    self.idle()
                except Exception:
                    pass
                continue
            if item is None:
                return
            future, function, args = item
            if future.set_running_or_notify_cancel():
                try:
                    future.set_result(function(*args))
                except BaseException as exc:
                    future.set_exception(exc)

    def shutdown(self, wait=True):
        self.queue.put(None)
        if wait:
            self.thread.join()


class WorkerPool:
    """Several browser threads. Playwright objects belong to the thread that made
    them, so every job for one application runs on that application's worker."""

    def __init__(self, size, idle):
        self.workers = []
        for index in range(max(1, size)):
            self.workers.append(BrowserWorker(lambda index=index: idle(index), name=f"application-browser-{index}"))

    def __len__(self):
        return len(self.workers)

    def current(self):
        """Index of the worker running the caller, or None off the pool."""
        from threading import current_thread
        return next((index for index, worker in enumerate(self.workers) if worker.thread is current_thread()), None)

    def submit(self, function, *args):
        # Work not tied to an application (tests, maintenance) uses the first worker.
        return self.workers[0].submit(function, *args)

    def shutdown(self, wait=True):
        for worker in self.workers:
            worker.shutdown(wait=False)
        if wait:
            for worker in self.workers:
                worker.thread.join()

"""Keep Playwright's synchronous event pump alive while waiting for the user."""
from concurrent.futures import Future
from queue import Empty, Queue
from threading import Thread


class BrowserWorker:
    def __init__(self, idle):
        self.queue = Queue()
        self.idle = idle
        self.thread = Thread(target=self._run, name="application-browser", daemon=True)
        self.thread.start()

    def submit(self, function, *args):
        future = Future()
        self.queue.put((future, function, args))
        return future

    def _run(self):
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

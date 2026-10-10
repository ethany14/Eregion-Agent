"""Interruptible provider requests; browser actions always stay on their owner thread."""
import time
from concurrent.futures import ThreadPoolExecutor, wait


class ModelInterrupted(Exception):
    pass


class ModelRequests:
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='agent-provider')

    def _detach(self, future):
        future.cancel()
        # Python cannot stop an in-flight SDK call. Its eventual result is
        # ignored; a fresh executor lets new steering proceed immediately.
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='agent-provider')

    def call(self, invoke, *, active, timeout=45, pump=None):
        if not active():
            raise ModelInterrupted()
        future = self.executor.submit(invoke)
        deadline, next_check = time.monotonic() + timeout, time.monotonic() + .1
        while not future.done():
            moment = time.monotonic()
            if moment >= next_check:
                if not active():
                    self._detach(future)
                    raise ModelInterrupted()
                next_check = time.monotonic() + .1
            if moment >= deadline:
                self._detach(future)
                raise TimeoutError('Model request deadline exceeded.')
            if pump:
                pump()  # Keep Playwright events on the browser's owner thread.
            else:
                # Wakes immediately on completion; no fixed sleep added to replies.
                wait([future], timeout=max(0, min(next_check, deadline) - time.monotonic()))
        # Always check fresh state before accepting even an immediately finished call.
        if not active():
            raise ModelInterrupted()
        return future.result()

    def close(self):
        self.executor.shutdown(wait=False, cancel_futures=True)

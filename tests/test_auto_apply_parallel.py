"""Parallel applications: one thread per run, one run at a time per employer site."""
import threading
import time

from agent_runtime.auto_apply.loop import ApplicationLoop, site_key
from agent_runtime.auto_apply.repository import ApplyRepository
from test_auto_apply import FakeBrowser, database, request, wait


class TimedBrowser(FakeBrowser):
    """Records which thread touched it and when it was busy."""
    log = []

    def __init__(self, url):
        super().__init__(url)
        self.url, self.threads = url, set()

    def observe(self):
        self.threads.add(threading.current_thread().name)
        started = time.monotonic()
        time.sleep(.15)
        TimedBrowser.log.append((self, started, time.monotonic()))
        return super().observe()

    def close(self):
        self.threads.add(threading.current_thread().name)
        super().close()


def overlaps(first, second):
    return any(a0 < b1 and b0 < a1 for u, a0, a1 in TimedBrowser.log if u == first
               for v, b0, b1 in TimedBrowser.log if v == second)


def run_two(database, first, second, workers=2):
    TimedBrowser.log = []
    browsers = []
    def factory(url):
        browsers.append(TimedBrowser(url))
        return browsers[-1]
    loop = ApplicationLoop(ApplyRepository(database.session_factory), browser_factory=factory, workers=workers)
    try:
        ids = [loop.start(request(url=first, idempotency_key="parallel-0001"))["run_id"],
               loop.start(request(url=second, idempotency_key="parallel-0002"))["run_id"]]
        assert [wait(loop, run_id)["status"] for run_id in ids] == ["awaiting_review", "awaiting_review"]
    finally:
        loop.close()
    assert len(browsers) == 2
    return browsers


def test_site_key_separates_employers_on_shared_ats_hosts():
    assert site_key("https://jobs.lever.co/acme/1") == site_key("https://jobs.lever.co/acme/2")
    assert site_key("https://jobs.lever.co/acme/1") != site_key("https://jobs.lever.co/globex/1")
    assert site_key("https://acme.wd5.myworkdayjobs.com/x/job/1") != site_key("https://globex.wd5.myworkdayjobs.com/x/job/1")


def test_different_employers_are_filled_in_parallel_each_on_one_thread(database):
    first, second = "https://jobs.lever.co/acme/role-1", "https://jobs.lever.co/globex/role-2"
    a, b = run_two(database, first, second)
    assert overlaps(a, b)
    # Every browser call for a run, including closing it, stays on its thread.
    for browser in (a, b):
        assert len(browser.threads) == 1 and browser.closed
    assert a.threads != b.threads


def test_one_employer_site_never_sees_parallel_runs(database):
    first, second = "https://jobs.lever.co/acme/role-1", "https://jobs.lever.co/acme/role-2"
    a, b = run_two(database, first, second)
    assert not overlaps(a, b)
    assert a.threads == b.threads


def test_single_worker_runs_one_application_at_a_time(database):
    first, second = "https://jobs.lever.co/acme/role-1", "https://jobs.lever.co/globex/role-2"
    a, b = run_two(database, first, second, workers=1)
    assert not overlaps(a, b)

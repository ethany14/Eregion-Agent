"""Overlap independent checks while keeping each provider reservation accounted for."""
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context

def parallel_checks(code_check, model_check):
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix='resume-verifier') as pool:
        model = pool.submit(copy_context().run, model_check)
        verdict = code_check()
        if not verdict.passed:
            # A running request cannot always be cancelled. Wait for accounting,
            # ignore its result/errors, and preserve the deterministic rejection.
            model.cancel()
            return verdict, None
        return verdict, model.result()

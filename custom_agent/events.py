"""Compatibility alias (unified loop M3): the module moved to job_agent.workflow.events.

The old import path resolves to the same module object, so state, ORM tables
and monkeypatches stay shared. Remove once no caller imports custom_agent.
"""
import sys

from job_agent.workflow import events as _module

sys.modules[__name__] = _module

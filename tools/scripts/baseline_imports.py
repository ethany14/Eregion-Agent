"""Adapt import statements in pre-layout source loaded for historical comparisons.

The historical source file/revision stays unchanged. Only dependency locations
are translated; no compatibility executor or module aliases enter production.
"""
import re

MODULE_MOVES = {
    'loop_engine': 'core.engine', 'loop_context': 'core.context',
    'loop_model': 'core.model', 'host_protocol': 'core.host_protocol',
    'task_loop': 'tasks.loop', 'task_host': 'tasks.host',
    'task_control': 'tasks.control', 'multi_agent': 'coordination',
}


def relocate_imports(source):
    for old, new in MODULE_MOVES.items():
        source = re.sub(
            r'(?m)^(\s*(?:from|import)\s+)agent_runtime\.' + old + r'(?=[.\s])',
            lambda match: match[1] + 'eregion.runtime.' + new,
            source,
        )
    # Historical source is only loaded by offline comparisons. Never register
    # old module names in sys.modules or ship legacy runtime shims.
    for old, new in {'agent_runtime': 'eregion.runtime', 'job_agent': 'eregion.domain',
                     'api': 'eregion.api', 'custom_agent': 'eregion.domain.workflow'}.items():
        source = re.sub(r'(?m)^(\s*(?:from|import)\s+)' + old + r'(?=[.\s])',
                        lambda match: match[1] + new, source)
    return source

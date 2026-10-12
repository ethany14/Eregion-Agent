"""Unified loop M7: production autonomy reaches only loop_engine.AgentLoop.

Checks the real import and call structure (AST), not file names:
- every AgentLoop construction resolves to agent_runtime.loop_engine.AgentLoop and
  happens only in the registered Hosts' owners;
- the single-step model decision (ToolCallingLoop.decide) is called only from a
  Host's invoke();
- provider requests enter only through the accounted provider layer
  (provider_call / adapter_attempt), and only job_agent.model builds chat clients;
- no production code imports the legacy custom_agent package.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = [p for folder in ('agent_runtime', 'api', 'job_agent') for p in (ROOT / folder).rglob('*.py')] \
    + [ROOT / 'main.py']


def _parse(path):
    return ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))


def _rel(path):
    return path.relative_to(ROOT).as_posix()


def _calls(tree, predicate):
    """(enclosing class, enclosing function) for each call matching predicate."""
    found = []

    def visit(node, cls=None, fn=None):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                visit(child, child.name, fn)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, cls, child.name)
            else:
                if isinstance(child, ast.Call) and predicate(child):
                    found.append((cls, fn))
                visit(child, cls, fn)
    visit(tree)
    return found


def _name(call):
    func = call.func
    return func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else None


def test_agent_loop_is_the_only_autonomous_kernel():
    sites = {}
    for path in PRODUCTION:
        tree = _parse(path)
        calls = _calls(tree, lambda c: _name(c) == 'AgentLoop')
        if not calls:
            continue
        imports = {(n.module, a.name) for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
        assert ('agent_runtime.loop_engine', 'AgentLoop') in imports, _rel(path)
        sites[_rel(path)] = sorted({c for c, _ in calls}, key=str)
    assert set(sites) == {'agent_runtime/task_loop.py', 'agent_runtime/auto_apply/runner.py',
                          'agent_runtime/sessions/coordinator.py', 'agent_runtime/tools/loop.py'}, sites


def test_model_decisions_are_made_only_inside_host_invoke():
    sites = set()
    for path in PRODUCTION:
        for cls, fn in _calls(_parse(path), lambda c: _name(c) == 'decide' and isinstance(c.func, ast.Attribute)):
            sites.add((_rel(path), cls, fn))
    assert sites == {('agent_runtime/sessions/host.py', 'SessionHost', 'invoke'),
                     ('agent_runtime/tools/loop.py', '_RunHost', 'invoke')}, sites


def test_provider_requests_enter_only_through_the_accounted_layer():
    entry = {name: set() for name in ('provider_call', 'adapter_attempt')}
    clients = set()
    for path in PRODUCTION:
        tree = _parse(path)
        for name in entry:
            if _calls(tree, lambda c, n=name: _name(c) == n):
                entry[name].add(_rel(path))
        if _calls(tree, lambda c: _name(c) in {'ChatOpenAI', 'ChatAnthropic', 'OpenAI', 'Anthropic'}
                  and isinstance(c.func, ast.Name)):
            clients.add(_rel(path))
    assert entry['provider_call'] == {'job_agent/model.py', 'agent_runtime/fast_decisions.py',
                                      'job_agent/jev_fit/transport.py'}, entry
    assert entry['adapter_attempt'] == {'job_agent/job_extraction.py', 'job_agent/workflow/handlers.py',
                                        'job_agent/model.py'}, entry
    assert clients <= {'job_agent/model.py'}, clients


def test_production_does_not_import_the_legacy_package():
    offenders = [_rel(p) for p in PRODUCTION for n in ast.walk(_parse(p))
                 if (isinstance(n, ast.ImportFrom) and (n.module or '').split('.')[0] == 'custom_agent')
                 or (isinstance(n, ast.Import) and any(a.name.split('.')[0] == 'custom_agent' for a in n.names))]
    assert offenders == []

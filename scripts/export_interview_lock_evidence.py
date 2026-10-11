"""Archive existing offline C16 results; no providers, Git writes, or overwrites."""
import argparse
import hashlib
import json
from pathlib import Path

from export_catalog_attempt_evidence import ROOT, describe


def external(path, expected=None):
    value = describe_xml_or_file(path)
    if expected is not None and value['sha256'] != expected:
        raise ValueError(f'Independent evidence hash changed: {path.name}')
    value['expected_sha256'] = expected
    value['origin'] = 'Independent supervisor workspace; read only, not executed by this exporter.'
    return value


def describe_xml_or_file(path):
    # Reuse XML parsing, while retaining the external path and original bytes.
    import xml.etree.ElementTree as ET
    raw = path.read_bytes()
    value = {'path': path.as_posix(), 'bytes': len(raw),
             'sha256': hashlib.sha256(raw).hexdigest()}
    if path.suffix == '.xml':
        tree = ET.fromstring(raw)
        suites = [tree] if tree.tag == 'testsuite' else list(tree.findall('testsuite'))
        totals = {k: sum(int(s.get(k, 0)) for s in suites)
                  for k in ('tests', 'failures', 'errors', 'skipped')}
        value.update(raw_suite_totals=totals,
                     passed=totals['tests']-totals['failures']-totals['errors']-totals['skipped'],
                     seconds=sum(float(s.get('time', 0)) for s in suites))
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--independent-root', type=Path, required=True)
    args = parser.parse_args()
    local_names = ['c16-lock-before-20261011', 'c16-lock-after-20261011',
                   'c16-lock-after-v2-20261011', 'c16-lock-integrated-20261011']
    artifacts = [describe(ROOT / 'tmp' / (name + suffix))
                 for name in local_names for suffix in ('.xml', '.log')]
    diag_path = ROOT / 'tmp/c16-lock-cancel-after-v1-diagnostic.json'
    diag = json.loads(diag_path.read_text(encoding='utf-8'))
    artifacts += [describe(diag_path), describe(ROOT / diag['database']['path'])]
    snapshots = []
    for directory in ['c16-lock-before-cases-20261011', 'c16-lock-after-cases-20261011',
                      'c16-lock-after-v2-cases-20261011', 'c16-lock-integrated-cases-20261011']:
        paths = sorted((ROOT / 'tmp' / directory).rglob('failure-before-question-release.json'))
        if len(paths) != 2:
            raise ValueError(f'Expected two actual event snapshots in {directory}, got {len(paths)}')
        for path in paths:
            data = json.loads(path.read_text(encoding='utf-8'))
            after = path.with_name('failure-after-question-release.json')
            artifacts.extend([describe(path), describe(after)])
            snapshots.append({'path': path.relative_to(ROOT).as_posix(),
                'question_owner': data['question_owner'],
                'question_still_blocked': data['question_still_blocked'],
                'feedback_provider_failed': data['feedback_provider_failed'],
                'failure_committed_before_question_release': data['failure_committed_before_question_release'],
                'session_status': data['session']['status'],
                'questions_completed': data['session']['questions_completed'],
                'jobs': [{'answer_id': j['answer_id'], 'question_id': j['question_id'],
                          'status': j['status']} for j in data['jobs']]})
    independent = [
        ('feedback-lock-before-independent-v2.xml', '1953c176b230ddaacc31ef4ad01548bd63527027387892ad336704f3d8299aad'),
        ('feedback-lock-after-independent.xml', '45c4e699c8b29bc48d480a2ef90bbac132191d4a228563492f84555e158abfd2'),
        ('c16-lock-regression-independent.xml', '65c978976157857ab6ab0af8992c26a4f2dc2b863f3b10c7bc649de27a559a0a'),
        ('c16-terminal-independent.xml', '451b35ecb3c076e09763d85607d7b63aaaab44b76bb1a0d9baaf0ee14d01e9e5'),
        ('inspect_interview_timing_db.json', 'f6d8bf593e19c5463173d6ed162e245b4171db9f718c66f41d830b4db3b44ab7'),
        ('interview-async-timing-independent.json', '5ca4e63281f91a285b21dd9a181717c978ca870434411d7bd4155af004ef147a'),
        ('test_feedback_failure_lock_independent.py', None),
    ]
    evidence = {
        'revision': '2026-10-11-interview-failure-lock-offline-r1',
        'scope': 'Production CareerService/controller/SQLite, event-gated synthetic providers. No network or paid latency test.',
        'real_api_calls': 0, 'paid_usage': None,
        'reproduction': 'Pause Q2 provider; Q1 feedback immediately raises ConnectError. Require FEEDBACK_FAILED committed within 2s before releasing Q2, with original answer/question IDs.',
        'root_cause': 'Deferred answer/evaluation paths held transition_lock across _ask RPC; feedback error persistence needed the same lock.',
        'fix': 'Separate question-draft mutex; deferred paths release transition_lock before question RPC. Short CAS commit sections preserve binding and bounded write-only retries.',
        'failure_progression': {
            'before': 'Three causal assertions failed; not three distinct defects. Independent v2 is valid before; earlier cwd setup failure is not product evidence.',
            'after_v1': '3 passed/1 failed. Actual SQLite CANCELLED(sequence7) then QUESTION_FAILED(sequence8), session failed/version8, queue failed ValueError. Not an end/report timeout defect.',
            'after_v2': '4 passed/7.751s after stale draft/exception terminal guards; original assertions and time limits unchanged.',
            'integrated': '95 passed/3 skipped/0 failure/0 error/63.389s. 98 total is not 98 passed. Seven new lock cases include cancel/end x late draft/failure.',
        },
        'terminal_fix': 'On question CAS conflict refresh current session; abandon draft if terminal or question changed. Error path also preserves terminal session. No extra answer/question and no rollback of completed count.',
        'cancel_after_v1_readonly_snapshot': diag,
        'event_snapshots': snapshots,
        'artifacts': artifacts,
        'independent': [external(args.independent_root / name, expected) for name, expected in independent],
        'overlap': 'Independent 21-case suite, single failure-lock case and four terminal cases overlap. Do not add them as unique coverage.',
        'limitations': [
            'Offline mechanism and local recovery only; C16 overall remains FAILED.',
            'Original acceptance-to-visible-feedback main p50=110.097s exceeds 30s; async real attempt failed with ConnectError/unknown usage. No new real latency result.',
            'Fast model ID not configured; <=10s untested. Full acceptance-to-visible clock including queue remains required.',
            'Fix covers deferred main-chat generation and feedback paths; direct synchronous control callers are not proven free of outer transition locks.',
            'A5 <=60s remains FAILED/user-deferred; no paid reruns/backend replay/employer submission.',
        ],
        'implementation_files': [describe(ROOT / p) for p in (
            'agent_runtime/mock_interview/controller.py', 'tests/test_remaining_interview_failure_lock.py')],
    }
    output = ROOT / 'docs/diagnostics/remaining-2026-10-11/interview-failure-lock-offline-r1.json'
    with output.open('x', encoding='utf-8') as stream:
        json.dump(evidence, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({'output': output.relative_to(ROOT).as_posix(),
                      'local_artifacts': len(artifacts), 'independent': len(independent)}))


if __name__ == '__main__':
    main()

"""F3 read-only inventory and conservative review candidates. Never delete or open DBs.

No subprocess/provider/SQLite calls. Existing tmp files are only stat'ed, except
JUnit result XML used to establish failures and a narrow regeneration recipe.
Writes are exclusive new audit outputs; neither output is a deletion instruction.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
ROOT_FILES = '(root files)'
TEXT_SUFFIXES = {'.md', '.json', '.py', '.js', '.mjs', '.toml', '.ini', '.yaml', '.yml'}
RAW_SUFFIXES = {'.json', '.jsonl', '.log', '.xml', '.png', '.jpg', '.jpeg', '.pdf', '.html', '.zip', '.session'}
DB_SUFFIXES = {'.db', '.sqlite', '.sqlite3', '.wal', '.shm'}
TMP_PATH = re.compile(r'(?<![\w/])tmp[/\\][^\s`\"\'<>|,;(){}\[\]]+')
CORRECTIONS = {
    'tmp/remaining-eight-offline-production-contract/test_offline_eight_job_producti0/eight-production-cold-warm.json':
    'tmp/remaining-eight-offline-production-contract/test_offline_eight_job_product0/eight-production-cold-warm.json',
}
RECIPE_GROUP = 'e5-screen-after-cases-20261011'
RECIPE_XML = 'tmp/e5-screen-after-20261011.xml'


def describe(path: Path, root: Path | None = None):
    raw = path.read_bytes()
    return {'path': path.relative_to(root).as_posix() if root else path.as_posix(),
            'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def group_for(name):
    parts = name.split('/')
    return parts[1] if len(parts) > 2 else ROOT_FILES


def inventory(root: Path):
    """No following junctions/symlinks, no silent rglob permission omissions."""
    files, errors, links = [], [], []
    base = root / 'tmp'
    pending = [base]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as stream:
                entries = list(stream)
        except OSError as exc:
            errors.append({'path': directory.relative_to(root).as_posix(), 'error': type(exc).__name__})
            continue
        for entry in entries:
            path = Path(entry.path)
            name = path.relative_to(root).as_posix()
            try:
                info = entry.stat(follow_symlinks=False)
                reparse = bool(getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 1024))
                if entry.is_symlink() or reparse:
                    links.append({'path': name, 'action': 'hold_link_not_followed'})
                elif entry.is_dir(follow_symlinks=False):
                    pending.append(path)
                elif entry.is_file(follow_symlinks=False):
                    files.append({'path': name, 'bytes': info.st_size, 'mtime_ns': info.st_mtime_ns,
                                  'group': group_for(name)})
            except OSError as exc:
                errors.append({'path': name, 'error': type(exc).__name__})
    return sorted(files, key=lambda f: f['path']), errors, sorted(links, key=lambda f: f['path'])


def text_sources(root: Path):
    sources = set(root.glob('*.md'))
    for directory in ['docs', 'tools/scripts', 'tools/evals', 'tests', 'backend/eregion']:
        for path in (root / directory).rglob('*'):
            if path.is_file() and path.suffix in TEXT_SUFFIXES and '__pycache__' not in path.parts:
                sources.add(path)
    return sorted(sources)


def normalize_reference(value):
    # JSON doubles Windows separators; only normalize syntax, never job URLs.
    name = re.sub(r'/+', '/', value.replace('\\', '/')).rstrip('.:，。；：')
    if not name.startswith('tmp/') or '..' in Path(name).parts:
        return None
    return name


def existing_prefix(root, name):
    """Recover a real file before prose such as '.xml:107' or '.xml保留'.

    Never shorten a full path which actually exists, including Unicode names.
    """
    if (root / name).exists():
        return name
    for match in re.finditer(r'\.(?:xml|json|jsonl|log|db|sqlite3?|png|pdf|html)\b|\.(?:xml|json|log)(?=[^\x00-\x7f])', name):
        prefix = name[:match.end()]
        if (root / prefix).is_file():
            return prefix
    return name


def scan_references(root: Path, sources, independent):
    refs, source_info, errors = defaultdict(list), [], []
    for path in sources:
        try:
            raw = path.read_bytes()
            text = raw.decode('utf-8-sig')
        except (OSError, UnicodeError) as exc:
            errors.append({'path': path.relative_to(root).as_posix(), 'error': type(exc).__name__})
            continue
        source_info.append({'path': path.relative_to(root).as_posix(), 'bytes': len(raw),
                            'sha256': hashlib.sha256(raw).hexdigest()})
        for number, line in enumerate(text.splitlines(), 1):
            for match in TMP_PATH.finditer(line):
                name = normalize_reference(match[0])
                if name:
                    name = existing_prefix(root, name)
                if name:
                    entry = {'source': path.relative_to(root).as_posix(), 'line': number, 'method': 'literal_static_path'}
                    if entry not in refs[name]:
                        refs[name].append(entry)
    # Independent map supplements literal scans, but existence/type are always
    # derived afresh. No trusted `exists` or `directory` flags from that JSON.
    for name, entry in independent.get('references', {}).items():
        name = normalize_reference(name)
        if not name:
            continue
        for source in entry.get('sources', []):
            if not isinstance(source, str) or '..' in Path(source).parts or not (root / source).is_file():
                errors.append({'path': str(source), 'error': 'InvalidIndependentReferenceSource'})
                continue
            refs[name].append({'source': source, 'line': None, 'method': 'independent_static_map'})
    result = []
    for name, locations in sorted(refs.items()):
        path = root / name
        exists, directory = path.exists(), path.is_dir()
        if exists:
            kind = 'existing_directory_subtree' if directory else 'existing_file'
        elif name in CORRECTIONS:
            kind = 'historical_report_typo_corrected'
        elif '...' in name:
            kind = 'truncated_or_dynamic_path_not_missing_evidence'
        elif name == 'tmp/repair-live-career-rerun':
            kind = 'documented_example_command_not_executed_evidence'
        elif name.startswith('tmp/f3-rebuild-e5-NEW'):
            kind = 'proposed_rebuild_not_executed_evidence'
        elif name.startswith('tmp/f2-audit-probe'):
            kind = 'auditor_ignore_probe_not_runtime_evidence'
        elif name.endswith('-'):
            kind = 'dynamic_template_prefix_not_complete_evidence_path'
        elif locations and all(loc['source'].startswith('tests/') for loc in locations):
            kind = 'synthetic_test_literal_not_target_evidence'
        else:
            kind = 'unresolved_static_path_review_required'
        result.append({'path': name, 'exists': exists, 'directory': directory, 'kind': kind,
                       'protect_descendants': bool(exists and directory), 'locations': locations,
                       **({'corrected_path': CORRECTIONS[name]} if name in CORRECTIONS else {})})
    return result, source_info, errors


def reference_hits(name, refs):
    return [r['path'] for r in refs if r['exists'] and
            (name == r['path'] or (r['protect_descendants'] and name.startswith(r['path'].rstrip('/') + '/')))]


def suite_result(path: Path):
    tree = ET.fromstring(path.read_bytes())
    suites = [tree] if tree.tag == 'testsuite' else list(tree.findall('testsuite'))
    totals = {k: sum(int(s.get(k, 0)) for s in suites) for k in ('tests', 'failures', 'errors', 'skipped')}
    cases = []
    for case in tree.iter('testcase'):
        status = ('failed' if case.find('failure') is not None else 'error' if case.find('error') is not None
                  else 'skipped' if case.find('skipped') is not None else 'passed')
        cases.append({'classname': case.get('classname', ''), 'name': case.get('name', ''), 'status': status})
    return totals, cases


def normalized_run(name):
    return name.removesuffix('.xml').replace('-cases-', '-').removesuffix('-cases')


def failed_run_groups(root, files):
    failures, errors = [], []
    groups = {f['group'] for f in files if f['group'] != ROOT_FILES}
    for file in files:
        if file['group'] != ROOT_FILES or not file['path'].endswith('.xml'):
            continue
        path = root / file['path']
        try:
            totals, _ = suite_result(path)
        except (OSError, ET.ParseError) as exc:
            errors.append({'path': file['path'], 'error': type(exc).__name__})
            continue
        if totals['failures'] or totals['errors']:
            key = normalized_run(path.stem)
            matched = sorted(g for g in groups if normalized_run(g) == key)
            failures.append({'xml': file['path'], 'totals': totals, 'protected_groups': matched,
                             'mapping': 'Exact run stem with optional -cases-; unmatched runs remain raw protected.'})
    return failures, errors


def regeneration_recipe(root):
    """Narrow, reviewed zero-provider fixture family, NOT all green directories."""
    xml = root / RECIPE_XML
    totals, cases = suite_result(xml)
    if totals['failures'] or totals['errors']:
        return None
    modules = {'tests.test_remaining_cover_style', 'tests.test_application_pack'}
    nodes = [c for c in cases if c['status'] == 'passed' and c['classname'] in modules]
    source_names = ['tests/test_remaining_cover_style.py', 'tests/test_application_pack.py',
                    'tests/test_career_flow.py', 'tests/test_job_workflow.py', 'tests/test_mock_interview.py',
                    'tests/fixtures/remaining_cover_style_failure.json', 'tests/fixtures/remaining_cover_style_revision.json']
    return {'recipe_id': 'e5-synthetic-success-fixtures', 'group': RECIPE_GROUP,
            'result_xml': describe(xml, root), 'result_totals': totals, 'passed_nodes': nodes,
            'sources': [describe(root / p, root) for p in source_names],
            'basis': [
                'career fixture builds career.db with synthetic resume, Discovery, fake_analyze, FakePackModel and scripted interview model; closes DB.',
                'application_pack setup builds pack.db and uses FakePackModel; migration test builds old.db with migrations only; closes DB.',
                'Exact temp naming matches pytest _mk_tmp: sanitized request.node.name[:30], numeric suffix. Ambiguous prefixes are held.',
                'Frozen original failure/revision JSON remains in tests/fixtures; only generated successful fixture DB is considered.',
            ],
            'proposed_rebuild_command': '.venv\\Scripts\\python.exe -X utf8 -m pytest -q -p no:cacheprovider tests/test_remaining_cover_style.py tests/test_application_pack.py -k "not real" --basetemp=tmp/f3-rebuild-e5-NEW --junitxml=tmp/f3-rebuild-e5-NEW.xml',
            'rebuild_executed': False,
            'rebuild_boundary': 'Semantically regenerated synthetic state, not identical UUID/time/DB bytes. Use a NEW basetemp; never overwrite evidence.',
            'live_excluded': '-k not real excludes both opt-in real writer/reviser tests even if live environment variables are set.'}


def recipe_for_file(name, recipe):
    if not recipe:
        return None
    parts = name.split('/')
    if len(parts) != 4 or parts[1] != recipe['group']:
        return None
    nodes = [c for c in recipe['passed_nodes'] if c['status'] == 'passed'
             and re.fullmatch(re.escape(re.sub(r'[\W]', '_', c['name'])[:30]) + r'\d+', parts[2])]
    if len(nodes) != 1:
        return None
    node = nodes[0]
    expected = ('career.db' if node['classname'] == 'tests.test_remaining_cover_style' else
                'old.db' if node['name'].startswith('test_application_pack_migration') else 'pack.db')
    if parts[3] != expected:
        return None
    return {'recipe_id': recipe['recipe_id'], 'node': node['classname'].replace('.', '/') + '.py::' + node['name'],
            'passed_result_xml': recipe['result_xml']['path']}


def classify(file, refs, failed_groups, recipe):
    name = file['path']
    hits = reference_hits(name, refs)
    regeneration = recipe_for_file(name, recipe)
    tags = []
    if hits:
        tags.append('report_archive_index_or_recovery_reference')
    if file['group'] in failed_groups:
        tags.append('original_failed_or_setup_error_run')
    if re.search(r'live|main.feedback|async.main|cold.warm', file['group'], re.I):
        tags.append('possible_paid_run_preserve_entire_group')
    if re.search(r'usage|ledger|transcript|summary|acceptance|screenshot|failure', Path(name).name, re.I):
        tags.append('raw_result_usage_or_failure_artifact')
    if regeneration and re.search(r'restart|restore|recovery|persisted_step', regeneration['node'], re.I):
        tags.append('synthetic_recovery_evidence_hold')
    if Path(name).suffix.lower() in {'.png', '.jpg', '.jpeg'}:
        tags.append('screenshot_visual_evidence')
    if Path(name).suffix.lower() in RAW_SUFFIXES:
        tags.append('raw_evidence_type_preserve')
    if (Path(name).suffix.lower() in DB_SUFFIXES or name.endswith(('-wal', '-shm', '-journal'))) and not regeneration:
        tags.append('database_or_sidecar_ownership_unproven_preserve')
    if hits or tags:
        decision = 'protected_keep'
    elif regeneration:
        decision = 'reproducible_success_fixture_review_candidate'
    else:
        decision = 'unproven_keep_review_required'
        tags.append('absence_of_reference_is_not_regeneration_evidence')
    return {**file, 'classification': decision, 'deletion_eligible': False,
            'protection_tags': tags, 'reference_keys': hits, 'regeneration': regeneration,
            'content_read': file['group'] == ROOT_FILES and name.endswith('.xml'), 'database_opened': False}


def build_audit(root, baseline, independent, sources=None):
    files, errors, links = inventory(root)
    refs, source_info, source_errors = scan_references(root, sources if sources is not None else text_sources(root), independent)
    failed_runs, xml_errors = failed_run_groups(root, files)
    recipe_error = None
    try:
        recipe = regeneration_recipe(root)
    except (OSError, ET.ParseError, KeyError) as exc:
        recipe, recipe_error = None, type(exc).__name__
    failed_groups = {g for run in failed_runs for g in run['protected_groups']}
    decisions = [classify(f, refs, failed_groups, recipe) for f in files]
    if errors or source_errors or xml_errors:
        for entry in decisions:
            if entry['classification'] == 'reproducible_success_fixture_review_candidate':
                entry['classification'] = 'unproven_keep_review_required'
                entry['protection_tags'].append('audit_errors_fail_closed')
    totals = Counter()
    classes, groups = {}, {}
    for entry in decisions:
        totals['files'] += 1; totals['bytes'] += entry['bytes']
        for target, key in [(classes, entry['classification']), (groups, entry['group'])]:
            data = target.setdefault(key, {'files': 0, 'bytes': 0})
            data['files'] += 1; data['bytes'] += entry['bytes']
    old_groups = baseline.get('groups', {})
    delta = {g: {'before': old_groups.get(g, {'files': 0, 'bytes': 0}),
                 'current': groups.get(g, {'files': 0, 'bytes': 0})}
             for g in sorted(set(groups) | set(old_groups))
             if {k: old_groups.get(g, {}).get(k, 0) for k in ('files', 'bytes')} != groups.get(g, {'files': 0, 'bytes': 0})}
    candidates = [e for e in decisions if e['classification'] == 'reproducible_success_fixture_review_candidate']
    return {'revision': '2026-10-11-f3-readonly-r1',
        'scope': 'Read-only cleanup candidate audit; all deletion_eligible=false, no database opens, provider calls, rebuilds or deletes.',
        'root': root.as_posix(), 'summary': {**dict(totals), 'groups': len(groups), 'classifications': classes,
            'candidate_files': len(candidates), 'candidate_bytes': sum(e['bytes'] for e in candidates),
            'deletion_eligible_files': 0, 'deleted_files': 0, 'real_api_calls': 0},
        'baseline_comparison': {'supervisor_files': baseline['files'], 'supervisor_bytes': baseline['bytes'],
            'supervisor_groups': len(old_groups), 'files_delta': totals['files']-baseline['files'],
            'bytes_delta': totals['bytes']-baseline['bytes'], 'changed_groups': delta},
        'errors': {'inventory': errors, 'source_read': source_errors, 'xml_read_or_parse': xml_errors},
        'links_not_followed': links, 'references': refs, 'reference_source_snapshots': source_info,
        'failed_runs': failed_runs, 'regeneration_recipe': recipe, 'recipe_error': recipe_error,
        'groups': groups, 'files': decisions,
        'limitations': [
            'No whole-dataset content hashes: byte sizes/mtimes are metadata snapshots, not verified 5.8GB byte identity.',
            'Only JUnit results and reference documents read; database contents/paid ledger completeness/runtime ownership not inspected. Unproven databases preserved.',
            'Directory references protect descendants. Generic/dynamic/partial paths remain review items; no-reference never grants deletion permission.',
            'Regeneration candidate is a review label, not approval. Failure originals, paid data, recovery evidence and images stay protected.',
            'No deletion mode or rebuild execution exists in this tool. F3 cleanup remains incomplete.',
        ]}


def write_new(path, data):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--independent-references', type=Path, required=True)
    parser.add_argument('--independent-e5-evidence', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--summary-output', type=Path, required=True)
    args = parser.parse_args()
    output, summary_output = args.output.resolve(), args.summary_output.resolve()
    if output == summary_output:
        raise ValueError('Full and summary outputs must be distinct new paths')
    for path in [output, summary_output]:
        path.relative_to(ROOT)
        if path.exists():
            raise ValueError('Refuse to overwrite audit revision')
    baseline = json.loads(args.baseline.read_text(encoding='utf-8'))
    if Path(baseline['root']).resolve() != (ROOT / 'tmp').resolve() or baseline['errors']:
        raise ValueError('Baseline root mismatch or baseline inventory errors')
    independent = json.loads(args.independent_references.read_text(encoding='utf-8'))
    if independent.get('errors'):
        raise ValueError('Independent references contain unresolved read errors')
    audit = build_audit(ROOT, baseline, independent)
    audit['inputs'] = [describe(args.baseline), describe(args.independent_references)]
    if args.independent_e5_evidence:
        data = json.loads(args.independent_e5_evidence.read_text(encoding='utf-8'))
        audit['inputs'].append(describe(args.independent_e5_evidence))
        verified = []
        for expected in data['files']:
            path = Path(expected['path'])
            observed = describe(path)
            if observed['sha256'] != expected['sha256']:
                raise ValueError('Independent E5/C16 artifact SHA mismatch')
            totals, _ = suite_result(path)
            if any(int(expected[k]) != totals[k] for k in totals):
                raise ValueError('Independent E5/C16 XML counts mismatch')
            verified.append({**observed, 'totals': totals, 'origin': 'Supervisor independent run, not re-executed.'})
        audit['independent_e5_c16_supplement'] = {'bundle_scope': data['scope'], 'verified_files': verified,
            'overlap': 'Previously archived C16 cases overlap. No sum into unique coverage; E5 five new contracts are offline only.'}
    after, recheck_errors, after_links = inventory(ROOT)
    before_identity = [(f['path'], f['bytes'], f['mtime_ns']) for f in audit['files']]
    after_identity = [(f['path'], f['bytes'], f['mtime_ns']) for f in after]
    if recheck_errors or before_identity != after_identity or after_links != audit['links_not_followed']:
        raise ValueError('tmp changed during read-only audit; no outputs written, rerun with new snapshot after settling')
    audit['metadata_recheck'] = {'same_file_paths_sizes_mtimes': True, 'read_errors': recheck_errors,
        'boundary': 'No SQLite opens or source file writes; atime and DB byte hashes not measured.'}
    audit['own_outputs_not_in_snapshot'] = [p.relative_to(ROOT).as_posix() for p in [output, summary_output]]
    for ref in audit['references']:
        if not ref['exists'] and ref['path'] in audit['own_outputs_not_in_snapshot']:
            ref['kind'] = 'planned_current_audit_output_excluded_from_snapshot'
    write_new(output, audit)
    compact = {k: v for k, v in audit.items() if k not in {'files', 'reference_source_snapshots', 'references'}}
    compact['full_local_manifest'] = describe(output, ROOT)
    compact['reference_scan'] = {'sources': len(audit['reference_source_snapshots']),
        'existing_files': sum(r['exists'] and not r['directory'] for r in audit['references']),
        'existing_directories': sum(r['directory'] for r in audit['references']),
        'unresolved_or_historical_paths': [r for r in audit['references'] if not r['exists']]}
    compact['candidates'] = [e for e in audit['files'] if e['classification'] == 'reproducible_success_fixture_review_candidate']
    compact['source_snapshot_boundary'] = 'Exact paths/line references and source hashes are in the full local manifest; this is a snapshot, not proof of all dynamic recovery references.'
    write_new(summary_output, compact)
    print(json.dumps({'output': output.relative_to(ROOT).as_posix(),
        'summary_output': summary_output.relative_to(ROOT).as_posix(), 'summary': audit['summary'],
        'errors': audit['errors'], 'recipe_error': audit['recipe_error'],
        'baseline_delta': {k: v for k, v in audit['baseline_comparison'].items() if k != 'changed_groups'}}, indent=2))
    return int(any(audit['errors'].values()))


if __name__ == '__main__':
    raise SystemExit(main())

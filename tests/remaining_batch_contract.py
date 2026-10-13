"""Shared offline/live cold-resolver acceptance; aliases are evidence, not calls."""
from collections import Counter

from eregion.domain.jev_fit.resolve import locate


def resolver_coverage(raws, outputs, requests, evidence):
    originals = {f'job{i}:{m["requirement_id"]}': (job, m)
        for i, (job, raw) in enumerate(raws.items()) for m in raw['matches'] if m['status'] == 'unknown'}
    aliases = {}
    consistent = True
    for output in outputs.values():
        mapping = output.get('resolver', {}).get('batch_requirement_aliases', {})
        if aliases and aliases != mapping:
            consistent = False
        aliases = mapping
    primary = [rid for request in requests for rid in request['primary_wire_ids']]
    decisions = {d['requirement_id']: d for request in requests for d in request['decisions']}
    flattened = [rid for ids in aliases.values() for rid in ids]
    exact = Counter(flattened) == Counter(list(originals))
    predicates = True
    legal = set(outputs) == set(raws)
    per_job = {job: {} for job in raws}
    for wire, (job, target) in originals.items():
        owner = next((p for p, ids in aliases.items() if wire in ids), None)
        representative = originals.get(owner)
        predicates &= bool(representative) and (
            ' '.join(target['text'].split()), target['level']) == (
            ' '.join(representative[1]['text'].split()), representative[1]['level'])
        decision = decisions.get(owner)
        output = outputs.get(job, {})
        match = next((m for m in output.get('matches', []) if m['requirement_id'] == target['requirement_id']), None)
        unit = next((u for u in output.get('extraction', []) if u['id'] == target['requirement_id']), {})
        if decision and not decision['is_candidate_requirement']:
            status = (match or {}).get('status')
            valid = status == 'unknown' and unit.get('classification') != 'context'
        else:
            status = (match or {}).get('status')
            valid = status in {'matched', 'partial', 'missing', 'needs_confirmation', 'unknown'}
            if not decision:
                valid &= status == 'unknown'
            elif decision['status'] in {'matched', 'partial'} and not decision['personal_condition']:
                span = locate(decision.get('evidence_quote'), evidence)
                if span is None:
                    valid &= status == 'unknown'
                else:
                    valid &= status == decision['status'] and any(
                        citation.get('exact_text') == evidence[span[0]:span[1]] and citation.get('spans') == [list(span)]
                        for citation in (match or {}).get('citations', []))
            else:
                valid &= status == ('needs_confirmation' if decision['personal_condition'] else decision['status'])
        legal &= valid
        per_job[job][target['requirement_id']] = {'status': status, 'valid': bool(valid), 'primary': owner}
    checks = {
        'primary_ids_match_alias_keys': Counter(primary) == Counter(list(aliases)),
        'aliases_consistent_across_jobs': consistent,
        'aliases_cover_every_original_requirement_once': exact,
        'resolver_eight_job_prefixes': {rid.split(':')[0] for rid in flattened} == {f'job{i}' for i in range(8)},
        'aliases_preserve_complete_predicate_and_level': bool(predicates),
        'every_original_target_has_legal_result': bool(legal),
        'primary_replies_complete': set(primary) == set(decisions),
    }
    return {'checks': checks, 'primary_ids': primary, 'batch_requirement_aliases': aliases, 'targets': per_job}

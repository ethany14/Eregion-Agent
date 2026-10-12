"""Compare fixed-base and implementation pytest XML without hiding sandbox failures."""
from collections import Counter
import json
from pathlib import Path
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parents[3]
raw = root / '.codex-runs/opt-v3-stage2'

def read(path):
    result = {}
    for case in ET.parse(path).getroot().iter('testcase'):
        name = case.attrib['classname'].removeprefix('tests.') + '::' + case.attrib['name']
        status, reason = 'passed', ''
        for tag in ('failure','error','skipped'):
            node = case.find(tag)
            if node is not None:
                status, reason = tag, node.attrib.get('message','')
                break
        result[name] = {'status':status, 'reason':reason}
    return result

base, head = read(raw/'base.xml'), read(raw/'head.xml')
fail = lambda value: value['status'] in {'failure','error'}
new = {k:v for k,v in head.items() if fail(v) and (k not in base or not fail(base[k]))}
# Explicit final targeted reruns, if needed, remain visible alongside raw results.
reruns = {}
for lane in ('base','head'):
    path = raw / ('final-rerun-' + lane + '.xml')
    if path.exists(): reruns[lane] = read(path)
resolved = {k:v for k,v in new.items() if reruns.get('head',{}).get(k,{}).get('status') == 'passed'}
reproduced = {k:v for k,v in new.items() if reruns.get('base',{}).get(k) == v}
remaining = {k:v for k,v in new.items() if k not in resolved and k not in reproduced}
final = dict(head)
for filename in ('verified-off.xml','final-unit.xml','final-byte.xml','final-rerun-head.xml'):
    if (raw/filename).exists(): final.update(read(raw/filename))
report = {'final_combined_counts':dict(Counter(v['status'] for v in final.values())),
    'additional_final_tests':sorted(set(final)-set(head)),
    'base':'6691b0bb75651aa71d40b8287f086411623025a9',
    'base_counts':dict(Counter(v['status'] for v in base.values())),
    'head_counts':dict(Counter(v['status'] for v in head.values())),
    'base_failures':{k:v for k,v in base.items() if fail(v)},
    'head_failures':{k:v for k,v in head.items() if fail(v)},
    'initial_new_failures':new,'resolved_by_final_rerun':resolved,
    'reproduced_on_fixed_base':reproduced,'new_failures':remaining,
    'reruns':reruns,
    'skips':{k:v['reason'] for k,v in head.items() if v['status']=='skipped'},
    'new_skips':{k:v for k,v in head.items() if v['status']=='skipped' and base.get(k,{}).get('status')!='skipped'},
    'changed_skip_reasons':{k:v['reason'] for k,v in head.items() if v['status']=='skipped' and k in base and base[k]['status']=='skipped' and base[k]['reason']!=v['reason']},
    'removed_base_tests':sorted(set(base)-set(head))}
Path(__file__).with_name('regression.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
print(json.dumps({k:report[k] for k in ('base_counts','head_counts','initial_new_failures','new_failures','new_skips','changed_skip_reasons','removed_base_tests')},indent=2))
if remaining or report['new_skips'] or report['changed_skip_reasons'] or report['removed_base_tests']:
    raise SystemExit(1)

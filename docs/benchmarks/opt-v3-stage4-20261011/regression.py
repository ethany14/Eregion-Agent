"""Compare fixed-base and implementation JUnit outcomes without hiding failures."""
import json
import xml.etree.ElementTree as ET
from pathlib import Path

root = Path(__file__).resolve().parents[3] / '.codex-runs/opt-v3-stage4'
def parse(name):
    tree=ET.parse(root/name)
    failures, skips, passed = {}, {}, []
    for case in tree.iter('testcase'):
        key=case.get('classname')+'::'+case.get('name')
        nodes=[(kind,case.find(kind)) for kind in ('failure','error')]
        failed=False
        for kind,node in nodes:
            if node is not None:
                failures[key]={'kind':kind,'message':node.get('message',''),'text':node.text or ''}
                failed=True
        skip=case.find('skipped')
        if skip is not None: skips[key]=skip.get('message','')
        elif not failed: passed.append(key)
    return {'failures':failures,'skips':skips,'passed':passed}
base,head=parse('base.xml'),parse('head.xml')
result={'base_commit':'566f5642f921347df0446b7c40aa52d80ccbeaa9',
    'base':base,'implementation':head,
    'new_failures':sorted(head['failures'].keys()-base['failures'].keys()),
    'changed_failure_messages':{k:[base['failures'][k]['message'],head['failures'][k]['message']]
        for k in base['failures'].keys() & head['failures'].keys()
        if (base['failures'][k]['kind'],base['failures'][k]['message']) != (head['failures'][k]['kind'],head['failures'][k]['message'])},
    'added_skips':sorted(head['skips'].keys()-base['skips'].keys()),
    'removed_skips':sorted(base['skips'].keys()-head['skips'].keys()),
    'changed_skip_reasons':{k:[base['skips'][k],head['skips'][k]]
        for k in base['skips'].keys() & head['skips'].keys() if base['skips'][k]!=head['skips'][k]}}
(root/'regression.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
summary={k:v for k,v in result.items() if k not in ('base','implementation')}
for name,run in [('base',base),('implementation',head)]:
    summary[name]={'passed':len(run['passed']),'skipped':len(run['skips']),
        'failures':{k:{'kind':v['kind'],'message':v['message']} for k,v in run['failures'].items()},
        'skip_reasons':run['skips']}
Path(__file__).with_name('regression.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in summary.items() if k not in ('base','implementation')},indent=2))
for name in ('base','implementation'):
    r=summary[name]
    print(name, r['passed'], 'passed;',r['skipped'],'skipped;',len(r['failures']),'failures/errors')
assert not result['new_failures'], result['new_failures']
assert not result['added_skips'] and not result['changed_skip_reasons']

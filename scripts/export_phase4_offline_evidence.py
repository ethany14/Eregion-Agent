"""Freeze free offline repair evidence; never overwrite a previous audit."""
import hashlib
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    names=['remaining-phase4-replay-before','remaining-phase4-recovery-before-v2',
        'remaining-phase4-replay-after','remaining-phase4-replay-after-v2',
        'remaining-phase4-cached-import-before','remaining-phase4-replay-integrated',
        'remaining-phase4-replay-integrated-v2','remaining-phase4-challenge-before',
        'remaining-phase4-replay-chrome-final','remaining-cover-v8-offline']
    runs=[]
    for name in names:
        path=Path('tmp')/(name+'.xml');root=ET.parse(path).getroot()
        suites=root.findall('testsuite') if root.tag!='testsuite' else [root]
        runs.append({'path':path.as_posix(),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'counts':{k:sum(int(s.get(k,0)) for s in suites) for k in ('tests','failures','errors','skipped')},
            'seconds':sum(float(s.get('time',0)) for s in suites),
            'failures':[{'test':c.get('name'),'text':(f.text or '')[:3200]}
                for c in root.iter('testcase') for f in c if f.tag in {'failure','error'}],
            'skips':[{'test':c.get('name'),'reason':f.get('message')}
                for c in root.iter('testcase') for f in c if f.tag=='skipped']})
    failure=Path('docs/diagnostics/remaining-2026-10-11/analyst-phase4-recovery-failure-and-usage.json')
    original=json.loads(failure.read_text(encoding='utf-8'))
    for artifact in original['artifacts']:
        assert hashlib.sha256(Path(artifact['path']).read_bytes()).hexdigest()==artifact['sha256']
    volume=json.loads(Path('tmp/remaining-phase4-request-replay-v2/request-volume.json').read_text(encoding='utf-8'))
    from agent_runtime.application_pack.style import cover_revision_notes
    from agent_runtime.application_pack.workflow import PACK_PROMPT_VERSION
    cover_path=Path('tests/fixtures/remaining_cover_style_revision.json')
    cover=json.loads(cover_path.read_text(encoding='utf-8'))
    result={'scope':'No new provider calls. Synthetic SQLite/HTTP and route-intercepted local Chrome; frozen actual model artifacts are replay evidence only.',
        'original_failure_files_unchanged':True,'original_failure':failure.as_posix(),
        'boundary':'Only the last24 tool arguments/results; full52 ledger sizes/costs/action labels do not reconstruct missing early arguments.',
        'classification':{'remaining-phase4-replay-before':'11 reached assertions plus one fixture null instead of omitted recommendations; not 12 independent product defects.',
            'remaining-phase4-replay-after':'11 passed; remaining failure same fixture null, not product semantics.',
            'remaining-phase4-recovery-before-v2':'Frozen prior production function with faithful fixture reaches 8/8 blocked pending assertion.',
            'remaining-phase4-replay-integrated':'Bad test filename; collection did not execute product tests.',
            'remaining-phase4-cached-import-before':'Production SQLite import wrongly blocked despite captured same-target body.',
            'remaining-phase4-challenge-before':'Actual local Chrome fails to identify Verifying you are human wording.'},
        'runs':runs,'request_volume':volume,
        'cover_style':{'prompt_version':PACK_PROMPT_VERSION,'fixture':cover_path.as_posix(),
            'sha256':hashlib.sha256(cover_path.read_bytes()).hexdigest(),'provenance':cover['provenance'],
            'original_verification':cover['verification'],'original_usage':cover['usage'],
            'advisory_notes':cover_revision_notes(cover['content']),
            'status':'Still failed/pending human style review and new real model evidence; notes are not grounding or an aesthetic PASS. No paid writer/reviser rerun.'}}
    path=Path('docs/diagnostics/remaining-2026-10-11/phase4-offline-and-cover-v8-evidence.json')
    if path.exists():raise FileExistsError(path)
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'path':str(path),'original_files_unchanged':True,
        'runs':[{k:r[k] for k in ('path','counts','seconds')} for r in runs]}))


if __name__=='__main__':main()

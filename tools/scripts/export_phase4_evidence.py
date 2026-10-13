"""Compact local Phase 4 failure/pass provenance, retaining original files."""
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET


def main():
    names=['remaining-phase4-before','remaining-phase4-seniority-before','remaining-phase4-after',
        'remaining-phase4-intent-before','remaining-phase4-intent-after','remaining-phase4-detail-before',
        'remaining-phase4-tail-before','remaining-phase4-tail-before-v2','remaining-phase4-browser-before',
        'remaining-phase4-workday-identity-before','remaining-phase4-complete-local',
        'remaining-phase4-chrome-before','remaining-phase4-chrome-after','remaining-phase4-final',
        'remaining-phase4-disclosure-fixed','remaining-phase4-ddg-before','remaining-phase4-ddg-after',
        'remaining-phase4-cross-tool-before','remaining-phase4-acquisition-after',
        'remaining-phase4-acquisition-final','remaining-phase4-acquisition-boundaries',
        'remaining-fit-shared-quote-before','remaining-fit-shared-quote-final']
    rows=[]
    for name in names:
        path=Path('tmp')/(name+'.xml')
        if not path.exists():raise FileNotFoundError(path)
        root=ET.parse(path).getroot();suites=root.findall('testsuite') if root.tag!='testsuite' else [root]
        rows.append({'path':path.as_posix(),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'counts':{key:sum(int(s.get(key,'0')) for s in suites) for key in ('tests','failures','errors','skipped')},
            'seconds':sum(float(s.get('time','0')) for s in suites),
            'skips':[{'test':c.get('name'),'reason':skip.get('message')} for c in root.iter('testcase') for skip in c if skip.tag=='skipped'],
            'failures':[{'test':c.get('name'),'kind':failure.tag,'text':(failure.text or '')[:5000]}
                for c in root.iter('testcase') for failure in c if failure.tag in {'failure','error'}]})
    destination=Path('docs/diagnostics/remaining-2026-10-11/phase4-and-shared-quote-evidence.json')
    if destination.exists():raise FileExistsError(destination)
    destination.write_text(json.dumps({'scope':'Local SQLite, synthetic HTTP/browser, one local Chrome control chain; separate public probe. No paid provider calls in these tests.',
        'classification':{'remaining-phase4-before':'Board product failure; seniority case fixture missing read_job.',
            'remaining-phase4-seniority-before':'Corrected real read/import/score fixture exposes product acceptance of Staff.',
            'remaining-phase4-after':'Restart fixture used a different scoring signature, not a regression in the score guard.',
            'remaining-phase4-tail-before':'Pytest reserved parameter collection error; corrected in v2.',
            'remaining-phase4-chrome-before':'Actual cached-state product recovery failure after user control.',
            'remaining-phase4-final':'Readable Indeed name rejected because full hostname was required; fixed, other 131 passed.'},
        'runs':rows},ensure_ascii=False,indent=2),encoding='utf-8')
    print(str(destination))


if __name__=='__main__':main()

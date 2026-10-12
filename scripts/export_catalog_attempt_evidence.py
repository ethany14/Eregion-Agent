"""Export compact, offline evidence. Never overwrite a prior revision or read .env."""
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET


ROOT=Path(__file__).resolve().parents[1]
XMLS=[
    'remaining-main-analysis-before','remaining-main-matching-before-v2',
    'remaining-main-analysis-after','remaining-main-analysis-adjacent-first',
    'remaining-main-analysis-adjacent-v3','remaining-main-normalization-before',
    'remaining-partial-overlap-before','remaining-match-identity-before',
    'remaining-main-partial-final','remaining-main-offline-final-v2','remaining-fixed-catalogue-offline',
    'catalog-attempt-before-v2-20261011','catalog-attempt-after-first-20261011',
    'catalog-attempt-local-v3-20261011','catalog-attempt-local-v4-20261011',
    'catalog-attempt-integrated-v1-20261011','catalog-attempt-integrated-v3-20261011',
    'catalog-batch-before-20261011','catalog-batch-after-20261011','catalog-batch-adjacent-final-20261011',
    'catalog-batch-no-config-final-20261011',
    'plural-identity-before-20261011','plural-identity-after-20261011',
]


def describe(path):
    raw=path.read_bytes()
    result={'path':path.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(raw).hexdigest(), 'bytes':len(raw)}
    if path.suffix=='.xml':
        tree=ET.fromstring(raw)
        suites=[tree] if tree.tag=='testsuite' else list(tree.findall('testsuite'))
        result['raw_suite_totals']={key:sum(int(s.get(key,0)) for s in suites)
            for key in ('tests','failures','errors','skipped')}
        result['seconds']=sum(float(s.get('time',0)) for s in suites)
        result['failures']=[{'case':case.get('classname','')+'::'+case.get('name',''),
            'message':node.get('message','')[:400]} for case in tree.iter('testcase')
            for node in [*case.findall('failure'),*case.findall('error')]]
        result['skipped']=[{'case':case.get('classname','')+'::'+case.get('name',''),
            'reason':node.get('message','')} for case in tree.iter('testcase') for node in case.findall('skipped')]
    return result


def main():
    paths=[ROOT/'tmp'/f'{name}.xml' for name in XMLS]
    paths += [ROOT/'tmp'/name for name in (
        'catalog-attempt-before-20261011.log','catalog-attempt-integrated-v2-20261011.log')]
    output=ROOT/'docs/diagnostics/remaining-2026-10-11/catalogue-attempt-offline-r1.json'
    evidence={'revision':'2026-10-11-catalogue-attempt-offline-r1',
        'scope':'Production service/handlers/cache with synthetic adapters or MockTransport only; no real provider calls.',
        'real_api_calls':0, 'paid_usage':None,
        'default_binding':'OPEN/pending real user route choice; explicit trusted catalogue input is implemented, not default integration.',
        'quality':'A1 stability/A2 calibration/A3 human gold/A4 AUC remain unmeasured; no thresholds changed.',
        'catalogue':{'identity':'Complete JobAnalysis.model_dump including every JobRequirement field; exact body hash and version. Provenance is descriptive only.',
            'source':'Jev ledger exact span + documented leading bullet/Required/Preferred cleanup only; full ledger bounds/unique IDs validated.',
            'cache':'Complete payload hash plus producer signature; persistent match isolation and zero new attempts after restart.'},
        'counts':{'provider':'Each provider_call boundary, including failures and retries; nested adapters do not duplicate it.',
            'adapter':'Fallback per custom analyzer/structured transport invocation only when no concrete provider child was observed. Explicit source=adapter, tokens remain unknown; not a claim of paid provider usage.',
            'shared_multibatch':'25 bullet requirements preserved: resume1 + extraction4 + matching2 = 7, not old summary4.',
            'retry':'resume1 + job1 + matching timeout1 + retry1 = 4, not old summary3.',
            'warm':'0 new attempts, empty attempt list; historical spend not copied into current request.',
            'route':'Fast transport explicitly model_route=fast; other matching/extraction attempts main. ContextVars propagate across extraction/matching workers.',
            'unknown':'Absent token counts remain absent; failed unknown usage retained in result/exception capture and independent durable ledger. Adapter fallback does not fabricate durable provider rows.',
            'boundary':'SDK-internal HTTP retries beneath a provider boundary are not separately observable here; cold runner requires SDK retries=0.'},
        'failure_notes':{
            'remaining-main-analysis-before':'One matching test had invalid missing source fields before reaching retry; corrected matching-before-v2 records actual timeout failure.',
            'remaining-main-analysis-adjacent-first':'33 default Temp permission errors are environment failures, not passes; two assertions separately fixed.',
            'catalog-attempt-before-20261011.log':'System Python lacked pytest; no test ran, not a product failure.',
            'catalog-attempt-before-v2-20261011':'10 failed/9 passed: omitted catalogue fields/provenance identity and retry undercount reproduced.',
            'catalog-attempt-local-v3-20261011':'3 failed/37 passed: strict raw-span equality rejected legitimate Jev prefix cleanup; known exact transformation now checked.',
            'catalog-attempt-local-v4-20261011':'1 failed/39 passed: non-requirement ledger span corruption was not rejected; all ledger spans now validated.',
            'catalog-attempt-integrated-v2-20261011.log':'Nonexistent tests/test_model.py caused collection abort; no test ran.',
            'catalog-attempt-integrated-v1-20261011':'133 passed/4 skipped, not 137 passed.',
            'catalog-attempt-integrated-v3-20261011':'139 passed/4 skipped. Chrome opt-in skips retained; not browser or live model evidence.'},
        'artifacts':[describe(p) if p.exists() else {'path':p.relative_to(ROOT).as_posix(),'missing':True} for p in paths]}
    evidence['batch_preflight']={'before':'7 failures: Jev silently ignored supplied catalogues; main mixed batch lacked whole-batch preflight.',
        'after':'7 passed; invalid catalogue rejected before any scheduler spy call. Adjacent 47 passed +4 subtests passed.',
        'scope':'Offline spies and MockTransport, not default-route selection.'}
    evidence['C11']={'input':'Two real saved application IDs share one current posting and one durable run.',
        'before':'Actual SQLite + synthetic browser: started_count=2 despite only one durable application run.',
        'fix':'Track each encountered run in the batch. started_count/opened_or_reused_count count unique durable runs; resolved_request_count counts successful request entries.',
        'after':'29 passed, including zero new starts on replay; no real model/browser/employer claim.'}
    code=['job_agent/requirement_catalog.py','api/services/fit_analysis_service.py',
        'agent_runtime/provider_usage.py','job_agent/workflow/handlers.py','job_agent/job_extraction.py',
        'job_agent/model.py','agent_runtime/fast_decisions.py','agent_runtime/career/harness.py']
    evidence['implementation_files']=[describe(ROOT/p) for p in code]
    with output.open('x',encoding='utf-8') as stream:json.dump(evidence,stream,ensure_ascii=False,indent=2)
    print(output.relative_to(ROOT).as_posix())


if __name__=='__main__':main()

"""Bounded read-only public ATS probe; never creates a model or submits forms."""
import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import time
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from eregion.runtime.career.discovery import JobDiscovery


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    output=parser.parse_args().output
    if output.exists():raise ValueError('Preserve the existing probe; choose a new evidence path.')
    discovery=JobDiscovery();results=[]
    for board in ({'platform':'ashby','company':'linear'},
        {'platform':'workday','company':'nvidia','host':'nvidia.wd5.myworkdayjobs.com','site':'NVIDIAExternalCareerSite'}):
        started=time.perf_counter();row={'board':board}
        try:
            search=discovery.search('engineer',boards=[board]);row['search']=search
            if search['jobs']:
                job=discovery.job(search['jobs'][0]['url'])
                row['detail']={k:v for k,v in job.items() if k!='description'}
                row['detail'].update(description_chars=len(job['description']),description_sha256=hashlib.sha256(job['description'].encode()).hexdigest())
                row['detail_body']=job['description']
                row['status']='search_and_target_detail_read'
            else:row['status']='no_detail_verified'
        except Exception as exc:
            row.update(status='failed',error_type=type(exc).__name__)
            if getattr(exc,'response',None) is not None:row['http_status']=exc.response.status_code
        row['elapsed_seconds']=time.perf_counter()-started;results.append(row)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps({'at':datetime.now(UTC).isoformat(),'scope':'Public read-only ATS source probe; no search completeness, fit or employer application claim.',
        'provider_calls':0,'results':results},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps([{k:r[k] for k in ('board','status','error_type','elapsed_seconds') if k in r} for r in results]))


if __name__=='__main__':main()

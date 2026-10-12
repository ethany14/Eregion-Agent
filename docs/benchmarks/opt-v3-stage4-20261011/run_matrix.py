"""Run stage-4 gates offline, with legacy and stage-2 optimized request settings."""
import os
import subprocess
import sys
from pathlib import Path

root=Path(__file__).resolve().parents[3]
output=root/'.codex-runs/opt-v3-stage4'
output.mkdir(parents=True,exist_ok=True)
for mode in ('default','stage2'):
    env=dict(os.environ)
    env.pop('OPT_TEST_ROOT',None)
    for flag in ('SNAPSHOT_REFS','STABLE_TOOLS','PROMPT_TRIM'):
        env['JOB_AGENT_OPT_'+flag]='0' if mode=='default' else '1'
    env['JOB_AGENT_OPT_HISTORY_POLICY']='current' if mode=='default' else 'checkpoint'
    env['OPT_STAGE4_OUTPUT']=str(output/('measurements' if mode=='default' else 'measurements-stage2'))
    with (output/(mode+'.log')).open('w',encoding='utf-8') as log:
        result=subprocess.run([sys.executable,str(Path(__file__).with_name('run_offline.py')),
            'tests/test_opt_v3_stage4.py','-q','-ra','-p','no:cacheprovider',
            '--basetemp='+str(output/(mode+'-temp')),
            '--junitxml='+str(output/(mode+'.xml'))],cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT)
    print(mode,result.returncode,flush=True)
    if result.returncode: raise SystemExit(result.returncode)
subprocess.run([sys.executable,str(Path(__file__).with_name('summarize.py'))],check=True,cwd=root)

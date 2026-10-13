from pathlib import Path
import os,sys,json,time
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
os.environ['JOB_AGENT_HIDDEN_BROWSER']='headless'
from eregion.runtime.auto_apply.browser import ApplicationBrowser
from eregion.runtime.auto_apply.agent import AgentTools
from eregion.runtime.auto_apply.autofill import autofill
from eregion.runtime.fast_decisions import configured_decisions

BODY='''<h1>Nested synthetic application</h1><form onsubmit="event.preventDefault();window.submits++">
<label id="referral-label">How did you hear about us?</label>
<button type="button" id="referral" role="combobox" aria-labelledby="referral-label" aria-controls="menu" aria-expanded="false" aria-required="true"
onclick="document.getElementById('menu').hidden=false;this.setAttribute('aria-expanded','true')">Select one</button>
<div id="menu" role="listbox" hidden><div role="option" aria-expanded="false" onclick="openJobs()">Job Boards</div>
<div role="option">University</div><div role="option">Company website</div></div>
<button type="submit">Submit application</button></form><script>
window.submits=0;window.paths=[];
function openJobs(){window.paths.push('Job Boards');document.getElementById('referral').textContent='Job Boards';
document.getElementById('menu').innerHTML='<div role="option" onclick="pick(this)">LinkedIn</div><div role="option" onclick="pick(this)">Indeed</div>';}
function pick(el){window.paths.push(el.textContent);let b=document.getElementById('referral');b.textContent=el.textContent;b.setAttribute('aria-expanded','false');document.getElementById('menu').hidden=true;}
</script>'''
class Browser(ApplicationBrowser):
 def _guard_request(self,route):route.fulfill(content_type='text/html',body=BODY)

def main():
    b=Browser('https://jobs.lever.co/synthetic/nested',headless=True)
    service=configured_decisions(environ={**os.environ,'TYPESAFE_ENABLED':'true'})
    try:
     field=next(f for f in b.observe() if 'hear' in f['label'].lower())
     state={'profile':{},'answers':{field['key']:'LinkedIn'},'automation_mode':'hybrid','chat_revision':0}
     s=AgentTools(b,state,autofill=lambda:autofill(b,state,lambda:b''),active=lambda:True)
     calls=[]
     def evaluate(state,questions):
      result=service.evaluate(state,questions,purpose='nested-smoke');calls.append({**result.metadata(),'answers':result.answers});return result
     s.fast_choices=evaluate
     s.observe();start=time.monotonic();result=s.execute('autofill',{})
     snapshot=s.observe()
     report={'seconds':round(time.monotonic()-start,3),'result':result,'paths':b.page.evaluate('window.paths'),
             'value':b.page.locator('#referral').text_content(),'pending_paths':s._unresolved_paths(),
             'calls':calls,'submits':b.page.evaluate('window.submits')}
     out=Path(os.environ['NORTHSTAR_SMOKE_DIR']);(out/'nested.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
     b.page.screenshot(path=str(out/'nested.png'),full_page=True)
     print(json.dumps(report),flush=True)
     if report['value']!='LinkedIn':
      from eregion.runtime.auto_apply.agent import HybridApplicationAgent
      os.environ['TYPESAFE_ENABLED']='true'
      state['messages']=[{'id':'synthetic','role':'user','text':'Fill the observed application using the already saved answer. Explore the category if needed. Stop before final submission.'}]
      n={'model':0,'tool':0};actions=[]
      def reserve(kind):n[kind]+=1;return n[kind]<16
      result=HybridApplicationAgent().run(b,state,autofill=lambda:autofill(b,state,lambda:b''),active=lambda:True,
        reserve=reserve,report=lambda fs,name,k,result:actions.append({'tool':name,'result':result}),checkpoint=lambda **u:state.update(u))
      report.update(fallback=result,actions=actions,counts=n,value=b.page.locator('#referral').text_content(),paths=b.page.evaluate('window.paths'),submits=b.page.evaluate('window.submits'))
      (out/'nested.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
      b.page.screenshot(path=str(out/'nested.png'),full_page=True)
      print(json.dumps(report),flush=True)
     if 'fallback' in report: assert report['fallback']['reason']=='ready'
     assert report['value']=='LinkedIn' and report['paths']==['Job Boards','LinkedIn'] and not report['submits']
    finally:b.close()

if __name__ == '__main__':
    main()

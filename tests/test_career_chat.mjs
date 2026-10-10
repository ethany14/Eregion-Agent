import test from 'node:test';
import assert from 'node:assert/strict';
import {careerRoute,renderCareerResults} from '../web_app/career-chat.js';

test('Jev uncertainty renders a range, unresolved count and unmet conditions without a false zero',()=>{
  const el=(tag,text='',className='')=>({tag,text,className,children:[],append(...n){this.children.push(...n);},replaceChildren(){this.children=[];}});
  const container=el('div');
  renderCareerResults({container,el,button:t=>el('button',t),send:()=>{},review:()=>{},item:{career:true,jobs:[{
    application_id:'range',title:'Analyst',match_score:null,score_range:[65,80],analysis_status:'needs_review',
    requirement_counts:{matched:4,partial:1,missing:1,unknown:2},
    match_overview:{confirmed_condition:[{requirement:'Work onsite',satisfied:false}]}
  }]}});
  const all=n=>[n,...n.children.flatMap(all)], texts=all(container).map(n=>n.text);
  assert.ok(texts.includes('65–80'));
  assert.ok(texts.includes('unresolved'));
  assert.ok(texts.includes('Unmet conditions: Work onsite.'));
  assert.ok(!texts.includes('0'));
});

test('career chat keeps credential, preview and memory calls on the exact browser attempt',()=>{
  const current={run_id:'task',career:true,application_run_id:'browser-1'},options={enabled:true,current};
  assert.equal(careerRoute('',undefined,options).url,'/api/career/tasks');
  assert.equal(careerRoute('/task/chat',{text:'hello'},options).url,'/api/career/tasks/task/chat');
  for(const action of ['account','account-mode','preview','memory'])
    assert.equal(careerRoute(`/task/${action}`,{},options).url,`/api/auto-apply/browser-1/${action}`);
  const password={password:'synthetic-password'};
  assert.equal(careerRoute('/task/account',password,options).body,password);
  assert.deepEqual(careerRoute('/task/continue',{confirm_submit:true},options).body,{confirm_submit:true,application_run_id:'browser-1'});
  assert.equal(careerRoute('/candidate',{},options).url,'/api/auto-apply/candidate');
  assert.equal(careerRoute('/old/chat',{},options).url,'/api/auto-apply/old/chat');
  assert.throws(()=>careerRoute('/task/account',{}, {...options,current:{...current,application_run_id:null}}));
  assert.equal(careerRoute('/task/preview',undefined,{...options,current:{...current,application_run_id:null,
    preview_url:'/api/career/tasks/task/browser/preview'}}).url,'/api/career/tasks/task/browser/preview');
});

test('job text, materials and interview feedback are inert and have human-readable controls',()=>{
  const calls=[],node=(tag,text='')=>({tag,text,children:[],append(...nodes){this.children.push(...nodes);},replaceChildren(){this.children=[];}});
  const button=(text,action)=>({...node('button',text),action});
  const container=node('div');
  const item={career:true,jobs:[{title:'<img onerror=alert(1)>',application_id:'job',status:'saved',match_score:88}],
    materials:[{pack_id:'pack',items:[{pack_item_id:'doc',artifact_type:'cover_letter',status:'awaiting_review',text:'<script>untrusted</script>'}]}],
    interviews:[{latest_feedback:{overall_score:3,strengths:['Grounded example'],improvement_areas:['Add result']},
      report:{average_scores:{overall:3},practice_priorities:['Be specific'],question_answer_summaries:[]}}]};
  renderCareerResults({container,item,el:node,button,send:t=>calls.push(t),review:()=>calls.push('approve')});
  const all=n=>[n,...n.children.flatMap(all)],nodes=all(container);
  assert.ok(nodes.some(n=>n.text==='<script>untrusted</script>'));
  assert.ok(nodes.some(n=>n.text==='Add result'));
  assert.ok(nodes.some(n=>n.href==='/api/packs/pack/items/doc/cover-letter.pdf'));
  nodes.find(n=>n.text==='Approve this version').action();assert.deepEqual(calls,['approve']);
});

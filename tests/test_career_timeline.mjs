import test from 'node:test';
import assert from 'node:assert/strict';
import {careerTimeline} from '../frontend/web_app/career-chat.js';

const at=n=>`2026-10-09T10:${String(n).padStart(2,'0')}:00Z`;
const message=(id,n,role='assistant')=>({id,at:at(n),role});
const card=(id,n)=>({id,dataset:{resultKey:id,resultAt:n==null?'':at(n)}});
const ids=values=>values.map(v=>v.id);

test('job, material and interview results stay at the turns that produced them',()=>{
  const messages=[message('request',0,'user'),message('fit',2),message('materials',4),message('next',8,'user'),message('reply',9)];
  const cards=[card('job',1),card('doc',3),card('question',7)];
  assert.deepEqual(ids(careerTimeline(messages,cards)),['request','job','fit','doc','materials','question','next','reply']);
  assert.deepEqual(ids(careerTimeline([...messages,message('later',10)],cards)).slice(-3),['next','reply','later']);
  assert.deepEqual(ids(careerTimeline(messages,cards.map(c=>structuredClone(c)))),ids(careerTimeline(messages,cards)));
});

test('legacy undated results do not pin themselves below newer messages',()=>{
  const messages=[{id:'u',role:'user'},{id:'a',role:'assistant'},{id:'later',role:'user'}];
  assert.deepEqual(ids(careerTimeline(messages,[card('job')])),['u','a','job','later']);
  assert.deepEqual(ids(careerTimeline([],[card('job')])),['job']);
});


test('database UTC timestamps without offsets stay chronological in a local timezone',()=>{
  const previous=process.env.TZ;process.env.TZ='America/New_York';
  try{
    const result=card('job');result.dataset.resultAt='2026-10-09T10:01:00';
    assert.deepEqual(ids(careerTimeline([message('u',0,'user'),message('a',2),message('next',3)],[result])),['u','job','a','next']);
  }finally{if(previous===undefined)delete process.env.TZ;else process.env.TZ=previous;}
});

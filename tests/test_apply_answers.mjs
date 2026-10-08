import test from 'node:test';
import assert from 'node:assert/strict';
import {AnswerDrafts,renderAnswerBatch} from '../web_app/apply-answers.js';

class Element {
  constructor(tag,text=''){this.tag=tag;this.textContent=text;this.children=[];this.attrs={};this.events={};}
  append(...nodes){this.children.push(...nodes);}
  setAttribute(k,v){this.attrs[k]=v;}
  addEventListener(k,f){this.events[k]=f;}
  querySelectorAll(tags){return this.children.flatMap(n=>[...(tags.split(',').includes(n.tag)?[n]:[]),...n.querySelectorAll(tags)]);}
  async fire(event){if(!this.disabled)return this.events[event]?.({preventDefault(){}});}
}
const el=(tag,text)=>new Element(tag,text);
const button=(text,action)=>{const b=el('button',text);b.addEventListener('click',action);return b;};
const fields=[{key:'a',label:'English?',kind:'select',options:[{label:'Yes',value:'1'},{label:'No',value:'2'}]},
  {key:'b',label:'Consent',kind:'checkbox'},{key:'c',label:'Discovery channel',kind:'text'}];

test('select all questions, then submit once including an explicit false',async()=>{
  const drafts=new AnswerDrafts(),container=el('div'),calls=[];
  renderAnswerBatch({container,id:'A',fields,drafts,busy:false,submit:async answers=>{calls.push(answers);return true;},el,button});
  const form=container.children[0],buttons=form.querySelectorAll('button'),text=form.querySelectorAll('input')[0];
  await buttons[0].fire('click');await buttons[3].fire('click');
  assert.equal(calls.length,0);assert.equal(buttons.at(-1).disabled,true);
  text.value='LinkedIn';await text.fire('input');assert.equal(buttons.at(-1).disabled,false);
  await form.fire('submit');await form.fire('submit');
  assert.deepEqual(calls,[{a:'Yes',b:false,c:'LinkedIn'}]);assert.deepEqual(drafts.payload('A'),{});
});

test('polling and failed submission preserve choices; changed questions and another run do not reuse them',async()=>{
  const drafts=new AnswerDrafts(),container=el('div');
  renderAnswerBatch({container,id:'A',fields,drafts,busy:false,submit:async()=>false,el,button});
  drafts.set('A','a','No');drafts.set('A','b',false);drafts.set('A','c','University');
  drafts.sync('A',structuredClone(fields));assert.equal(drafts.complete('A'),true);
  drafts.sync('B',fields);assert.equal(drafts.complete('B'),false);
  const again=el('div');renderAnswerBatch({container:again,id:'A',fields,drafts,busy:false,submit:async()=>false,el,button});
  await again.children[0].fire('submit');assert.deepEqual(drafts.payload('A'),{a:'No',b:false,c:'University'});
  drafts.sync('A',[{...fields[0],label:'Different question'},fields[1]]);
  assert.deepEqual(drafts.payload('A'),{b:false});
});

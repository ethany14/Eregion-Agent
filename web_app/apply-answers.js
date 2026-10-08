// Option clicks only edit a draft; submit sends the whole group once.
export class AnswerDrafts {
  constructor(){this.runs=new Map();}
  sync(id,fields){
    const previous=this.runs.get(id)||new Map(),next=new Map();
    for(const f of fields){const signature=JSON.stringify([f.label,f.kind,f.group,f.options]);const old=previous.get(f.key);next.set(f.key,old?.signature===signature?old:{signature,value:undefined});}
    this.runs.set(id,next);return next;
  }
  set(id,key,value){const entry=this.runs.get(id)?.get(key);if(entry)entry.value=value;}
  clear(id){this.runs.delete(id);}
  payload(id){return Object.fromEntries([...(this.runs.get(id)||[])].filter(([,v])=>v.value!==undefined&&String(v.value).trim()!=='').map(([k,v])=>[k,v.value]));}
  complete(id){const entries=this.runs.get(id);return Boolean(entries?.size&&Object.keys(this.payload(id)).length===entries.size);}
}

export function renderAnswerBatch({container,id,fields,drafts,busy,submit,el,button}){
  fields=fields.filter(f=>!['file','password'].includes(f.kind));
  if(!fields.length)return;
  const entries=drafts.sync(id,fields),form=el('form','','answer-batch');
  const commit=el('button','Submit answers & continue','primary-button');commit.type='submit';
  const progress=el('p','','fine-print');
  const update=()=>{commit.disabled=busy||!drafts.complete(id);progress.textContent=`${Object.keys(drafts.payload(id)).length} of ${fields.length} answered. Your selections are sent together.`;};
  for(const f of fields){
    const row=el('div','','question-choice'),label=el('label',f.label,'question-label');row.append(label);
    const value=entries.get(f.key).value;
    const options=f.kind==='checkbox'?[{label:'Yes',value:true},{label:'No',value:false}]:(f.options||[]).filter(o=>!o.disabled&&String(o.value)!=='');
    if(options.length&&options.length<=6){
      const choices=el('div','','question-actions');choices.setAttribute('role','group');choices.setAttribute('aria-label',f.label);
      for(const option of options){const answer=f.kind==='checkbox'?option.value:option.label;const b=button(option.label,()=>{drafts.set(id,f.key,answer);for(const other of choices.children)other.setAttribute('aria-pressed','false');b.setAttribute('aria-pressed','true');update();});b.disabled=busy;b.setAttribute('aria-pressed',String(value===answer));choices.append(b);}row.append(choices);
    }else{
      const input=el(options.length?'select':'input');input.disabled=busy;input.id=`batch-${id}-${fields.indexOf(f)}`;label.htmlFor=input.id;
      if(options.length){const placeholder=el('option','Choose an answer');placeholder.value='';input.append(placeholder);for(const o of options){const n=el('option',o.label);n.value=o.label;input.append(n);}}
      else{input.type='text';input.maxLength=10000;input.placeholder='Your answer';}
      input.value=value??'';input.addEventListener(options.length?'change':'input',()=>{drafts.set(id,f.key,input.value);update();});row.append(input);
    }
    form.append(row);
  }
  form.append(progress,commit);update();
  form.addEventListener('submit',async event=>{event.preventDefault();if(commit.disabled)return;commit.disabled=true;for(const n of form.querySelectorAll('input,select,button'))n.disabled=true;if(await submit(drafts.payload(id)))drafts.clear(id);else{for(const n of form.querySelectorAll('input,select,button'))n.disabled=busy;update();}});
  container.append(form);
}

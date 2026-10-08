import {AnswerDrafts,renderAnswerBatch} from './apply-answers.js';
const answerDrafts=new AnswerDrafts();
const $ = s => document.querySelector(s);
const el = (tag,text='',cls='') => {const n=document.createElement(tag);n.textContent=text;n.className=cls;return n;};
const terminal=new Set(['submitted','submission_unknown','cancelled','failed']);
const labels={first_name:'First name',last_name:'Last name',email:'Email',phone:'Phone',linkedin:'LinkedIn',github:'GitHub',website:'Website',school:'School',degree:'Degree',country:'Country',city:'City'};
const statuses={queued:'Continuing the application',running:'Working on your application',needs_input:'Waiting for your input',awaiting_review:'Ready for your review',submitting:'Submitting once — waiting for confirmation',submitted:'Application received',submission_unknown:'Check the employer confirmation',cancelled:'Application cancelled',failed:'Application stopped'};
const newDraft=()=>({id:crypto.randomUUID(),url:'',messages:[],field:null,lastText:'',payload:null});
let draft=newDraft(),profile={},resume=null,selected=null,current=null,attempts=[],epoch=0,serial=0,poll=null;
let chatBusy=false,actionBusy=false,extracting=false,starting=false,extractionVersion=0,previewUrl=null,logSignature='',actionSignature='',failedMessage=null;
const optimistic=new Map();
let visualPreferenceRun=null,restoring=true,candidateWrites=Promise.resolve();
function persistCandidate(extra={}){
  const payload={profile:structuredClone(profile),...extra};
  const pending=candidateWrites.catch(()=>{}).then(()=>request('/candidate',payload));
  candidateWrites=pending;return pending;
}
async function removeResume(){
  extractionVersion++;resume=null;profile={};draft.id=crypto.randomUUID();draft.payload=null;$('#resume-file').value='';render();
  candidateWrites=candidateWrites.catch(()=>{}).then(()=>request('/candidate',undefined,'DELETE'));
  try{await candidateWrites;}catch(e){error(e.message);}
}

async function request(path='',body,method=body===undefined?'GET':'POST') {
  const response=await fetch(`/api/auto-apply${path}`,{method,headers:{'Content-Type':'application/json'},...(body===undefined?{}:{body:JSON.stringify(body)}),signal:AbortSignal.timeout(path==='/resume-profile'?120000:30000)});
  const data=await response.json();if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'Please check the job link and profile details.');return data;
}
function error(text=''){$('#apply-error').textContent=text;$('#apply-error').hidden=!text;}
function company(item){try{const u=new URL(item.url);return /greenhouse\.io$|lever\.co$/.test(u.hostname)?u.pathname.split('/').filter(Boolean)[0]:u.hostname.endsWith('.myworkdayjobs.com')?u.hostname.split('.')[0]:u.hostname;}catch{return 'Application';}}
function button(text,action,cls='secondary-button'){const b=el('button',text,cls);b.type='button';b.addEventListener('click',action);return b;}
function bottom(){const n=$('#chat-scroll');n.scrollTop=n.scrollHeight;}
function workspace(open=true){$('#browser-panel').hidden=!open;$('#browser-toggle').setAttribute('aria-expanded',String(open));if(open&&current)refreshPreview(current);}
function select(id){selected=id;current=attempts.find(a=>a.run_id===id)||null;epoch++;logSignature='';actionSignature='';$('#chat-text').value='';$('#history-panel').classList.remove('open');$('#browser-preview').hidden=true;$('#preview-placeholder').hidden=false;error();render();refresh();}
function reset(url=''){selected=null;current=null;epoch++;draft=newDraft();draft.url=url;logSignature='';actionSignature='';failedMessage=null;$('#chat-text').value='';$('#history-panel').classList.remove('open');$('#browser-preview').hidden=true;$('#preview-placeholder').hidden=false;error();restoring=true;render();if(url)addDraft('user',url);restoreCandidate();}
async function refresh(){
  clearTimeout(poll);const ticket=++serial;
  try{const result=await request();if(ticket!==serial)return;attempts=result.attempts;current=selected?attempts.find(a=>a.run_id===selected)||null:null;render();if(current&&!$('#browser-panel').hidden)await refreshPreview(current);}
  catch(e){if(ticket===serial)error(e.message);}finally{if(ticket===serial)poll=setTimeout(refresh,2000);}
}
function render(){
  if(current&&current.run_id!==visualPreferenceRun){$('#visual-fallback').checked=Boolean(current.visual_fallback);visualPreferenceRun=current.run_id;}
  $('#attempts').replaceChildren();
  for(const item of attempts){const b=button('',()=>select(item.run_id),'attempt');b.setAttribute('aria-current',String(selected===item.run_id));b.append(el('strong',company(item)),el('small',statuses[item.status]||item.status));$('#attempts').append(b);}
  const local=selected?optimistic.get(selected)||[]:[];
  const messages=current?[...(current.messages||[]),...local.filter(m=>!current.messages?.some(s=>s.id===m.id))]:draft.messages;
  $('#welcome').hidden=Boolean(current||messages.length);
  const signature=JSON.stringify(messages);
  if(signature!==logSignature){logSignature=signature;const s=$('#chat-scroll'),near=s.scrollHeight-s.scrollTop-s.clientHeight<120;$('#agent-messages').replaceChildren();for(const m of messages){const bubble=el('div','',`message ${m.role}`);bubble.dataset.messageId=m.id;bubble.append(el('span',m.role==='user'?'You':'Northstar','speaker'),el('p',m.text));$('#agent-messages').append(bubble);}if(near)requestAnimationFrame(bottom);}
  $('#chat-title').textContent=current?`Applying at ${company(current)}`:'Your next opportunity';
  $('#agent-status').textContent=extracting?'Reading your resume…':current?(current.pause_requested?'Paused — send “continue” when ready':statuses[current.status]):'A little less paperwork. A step closer.';
  $('#pause-agent').hidden=!current||terminal.has(current.status)||current.status==='submitting';$('#pause-agent').textContent=current?.pause_requested?'Resume':'Pause';$('#pause-agent').disabled=actionBusy;
  $('#send-message').disabled=chatBusy||starting||restoring||current?.status==='submitting';$('#attach-resume').disabled=extracting||restoring;$('#profile-toggle').disabled=extracting||restoring;
  const attachment=$('#attachment');attachment.replaceChildren();attachment.hidden=!resume&&!extracting;
  if(extracting)attachment.append(el('span','Reading your resume…'));else if(resume){attachment.append(el('span',`▤ ${resume.name}`),button('×',removeResume,'quiet-button'));}
  decisions();renderWorkspace();
}
function addDraft(role,text){draft.messages.push({id:crypto.randomUUID(),role,text});render();requestAnimationFrame(bottom);}
function ask(text){if(draft.messages.at(-1)?.text!==text)addDraft('assistant',text);}
function decisions(){
  const container=$('#conversation-actions');const sig=JSON.stringify([current?.run_id,current?.status,current?.pause_requested,current?.message,current?.account_request,current?.pending_fields,current?.fields,chatBusy,actionBusy,starting]);
  if(sig===actionSignature)return;actionSignature=sig;container.replaceChildren();if(!current)return;
  const item=current,id=item.run_id;
  if(['running','queued','submitting'].includes(item.status)){container.append(el('p',item.message,'status-line'));return;}
  if(item.status==='awaiting_review'){
    const box=el('div','','decision');box.append(el('h3','Your application is ready'),el('p',`Review the answers for ${company(item)}. I’ll submit once when you confirm.`));const actions=el('div','','actions');
    actions.append(button('Review answers',()=>{workspace();$('#answer-list').parentElement.open=true;}));const submit=button('Submit application',()=>act('continue',{confirm_submit:true},id),'primary-button');submit.disabled=chatBusy||actionBusy;actions.append(submit);box.append(actions);container.append(box);return;
  }
  if(item.pause_requested){const box=el('div','','decision');box.append(el('p','Paused. You can use the separate Chrome window; I won’t act until you resume.'),button('Resume',()=>send('continue')));container.append(box);return;}
  if(item.status==='needs_input'){
    if(item.account_request){const box=el('div','','decision');box.append(el('p',item.message),el('strong',item.account_request.origin),button(item.account_request.mode==='register'?'Create candidate account':'Sign in securely',()=>openAccount(item)));const other=item.account_request.mode==='register'?'login':'register';box.append(button(other==='register'?'Create an account instead':'Use an existing account',()=>act('account-mode',{origin:item.account_request.origin,mode:other},id)));container.append(box);return;}
    const last=[...(item.messages||[])].reverse().find(m=>m.role==='assistant'&&Array.isArray(m.question_keys));const keys=(last?.question_keys||[]).filter(key=>item.pending_fields?.includes(key)??true);
    renderAnswerBatch({container,id,fields:keys.map(key=>item.fields.find(f=>f.key===key)).filter(Boolean),drafts:answerDrafts,busy:chatBusy||actionBusy,submit:answers=>act('continue',{answers},id),el,button});
    if(!keys.length){const box=el('div','','decision');box.append(el('p',item.message));const actions=el('div','','actions');actions.append(button('Try again',()=>send('continue')),button('Open browser',()=>workspace()));box.append(actions);container.append(box);}
  }
  if(terminal.has(item.status)){const box=el('div','','decision');box.append(el('h3',statuses[item.status]),el('p',item.confirmation?.text||item.message),button('Next application',()=>reset()));container.append(box);}
}
function renderWorkspace(){
  $('#task-plan').replaceChildren();$('#browser-actions').replaceChildren();$('#answer-list').replaceChildren();
  $('#take-over').hidden=!current||terminal.has(current.status)||current.status==='submitting';$('#cancel-attempt').hidden=$('#take-over').hidden;
  $('#browser-caption').textContent=current?`${company(current)} · ${statuses[current.status]}. Live snapshots; use the separate Chrome window for direct interaction.`:'The application browser will appear here.';
  if(!current)return;
  for(const step of current.task_plan||[])$('#task-plan').append(el('li',step));if(!current.task_plan?.length)$('#task-plan').append(el('li',current.status==='awaiting_review'?'Review the completed application':current.message));
  const names={view_browser:'Look at browser',computer_click:'Click visible target',computer_move:'Move pointer',computer_scroll:'Scroll browser',computer_drag:'Drag visible control',computer_type:'Type confirmed answer',computer_key:'Press key',computer_wait:'Wait for page',resolve_field:'Adapt answer to this form',explore_option:'Explore option category',click_page_action:'Navigate application',autofill:'Fill known details',inspect_field:'Read options',search_options:'Search options',choose_option:'Choose option',type_from_source:'Type answer',use_chat_answer:'Apply your answer',click_field:'Open control',view_field:'Inspect control',ready_for_review:'Check completion',request_input:'Ask for missing information',say:'Update',observe:'Inspect page',update_plan:'Update plan'};
  for(const a of [...(current.actions||[])].slice(-20).reverse())$('#browser-actions').append(el('li',`${names[a.tool]||a.tool} · ${a.label} · ${a.outcome}`));
  const answers=new Map((current.review_fields||[]).map(f=>[f.key,f]));for(const f of current.fields)answers.set(f.key,f);
  for(const f of answers.values()){const row=el('div','','answer');row.append(el('strong',f.label),el('p',typeof f.value==='boolean'?(f.value?'Yes':'No'):String(f.value||'Not filled')));const decision=current.field_decisions?.[f.key];if(decision?.mode==='default')row.append(el('small',`Agent default: ${decision.reason}`));if(!terminal.has(current.status)&&current.status!=='submitting'&&f.kind!=='file')row.append(button('Correct in chat',()=>{$('#chat-text').value=`For “${f.label}”, use `;$('#chat-text').focus();},'quiet-button'));$('#answer-list').append(row);}
}
async function refreshPreview(item){if(terminal.has(item.status))return;try{const r=await fetch(`/api/auto-apply/${item.run_id}/preview`,{cache:'no-store',signal:AbortSignal.timeout(5000)});if(r.status!==200)return;const blob=await r.blob();if(current?.run_id!==item.run_id)return;if(previewUrl)URL.revokeObjectURL(previewUrl);previewUrl=URL.createObjectURL(blob);$('#browser-preview').src=previewUrl;$('#browser-preview').hidden=false;$('#preview-placeholder').hidden=true;}catch{/* A preview delay does not stop the task. */}}
async function encode(file){if(!(file instanceof File)||!file.size||file.size>10*1024*1024)throw new Error('Attach a PDF resume no larger than 10 MB.');const bytes=new Uint8Array(await file.arrayBuffer());let binary='';for(let i=0;i<bytes.length;i+=32768)binary+=String.fromCharCode(...bytes.subarray(i,i+32768));return btoa(binary);}
$('#resume-file').addEventListener('change',async event=>{
  const file=event.target.files[0];if(!file)return;if(current)reset();draft.id=crypto.randomUUID();draft.payload=null;const version=++extractionVersion,id=draft.id;extracting=true;error();addDraft('user',`Attached ${file.name}`);
  try{const encoded=await encode(file);if(version!==extractionVersion)return;resume={name:file.name,encoded};profile={};const result=await request('/resume-profile',{resume_base64:encoded,resume_name:file.name});if(version!==extractionVersion)return;profile=result.profile||{};await persistCandidate({resume_base64:encoded,resume_name:file.name,extracted:!result.warning});if(draft.id===id&&!selected){const name=[profile.first_name,profile.last_name].filter(Boolean).join(' ');ask(`I’ve saved your resume${name?` for ${name}`:''} for future applications.${profile.education?.length?` Found ${profile.education.length} education records; review them in Your details.`:''}${result.warning?' Some details need your help to complete.':''}`);}}
  catch(e){error(e.message);}finally{if(version===extractionVersion){extracting=false;render();if(!selected)advance();}}
});
function jobLink(text){return text.match(/https:\/\/[^\s<>"）)]+/)?.[0]?.replace(/[.,;，。；]+$/,'')||'';}
async function advance(){
  if(current||extracting||starting||restoring)return;
  if(!resume){ask('Attach your resume PDF here, and I’ll use it to prepare the application.');return;}
  if(!draft.url){ask('Send the job page you’d like to apply to. I can open the application and work through its steps with you.');return;}
  draft.field=['first_name','last_name','email'].find(k=>!profile[k]?.trim())||null;
  if(draft.field){ask(`What ${labels[draft.field].toLowerCase()} should I use? Send just that detail.`);return;}
  const id=draft.id,version=epoch;starting=true;render();ask('I have what I need to start. I’ll open the application and keep you updated here.');
  try{await candidateWrites;draft.payload ||= {url:draft.url,profile:{...profile},resume_base64:resume.encoded,resume_name:resume.name,auto_submit:false,automation_mode:'hybrid',consent_policy:'ask',reuse_answers:$('#reuse-answers').checked,visual_fallback:$('#visual-fallback').checked,idempotency_key:id,initial_message:draft.lastText||`Apply to ${draft.url} using ${resume.name}.`};const item=await request('',draft.payload);if(epoch===version&&draft.id===id){selected=item.run_id;current=item;logSignature='';actionSignature='';}await refresh();}
  catch(e){error(e.message);if(draft.id===id)ask('I couldn’t open this application yet. Check the message above, then send a corrected job link or tell me to try again.');}finally{starting=false;render();}
}
async function prepare(text){
  const id=draft.id;draft.lastText=text;addDraft('user',text);const url=jobLink(text);
  if(url){draft.url=url;draft.id=crypto.randomUUID();draft.payload=null;await advance();return;}
  if(/^(continue|start|go|retry|开始|继续|重试)[.!。！]?$/i.test(text)){await advance();return;}
  if(/^(pause|stop|暂停|停止)[.!。！]?$/i.test(text)){draft.url='';ask('Paused. Send the job link again when you want me to start.');return;}
  const result=await request('/prepare-message',{text,field:draft.field});if(draft.id!==id||selected)return;
  if(Object.keys(result.profile||{}).length){Object.assign(profile,result.profile);await persistCandidate();draft.field=null;draft.id=crypto.randomUUID();draft.payload=null;ask('Got it. I’ve updated your saved details.');await advance();}else ask(result.message||'Send a job link or attach your resume to get started.');
}
async function send(text,key=null,expectedRun=null){
  text=text.trim();if(!text||chatBusy||starting)return;if(expectedRun&&current?.run_id!==expectedRun)return;
  if(current&&terminal.has(current.status)){const url=jobLink(text);if(url){reset(url);return;}error('Start a new application to continue chatting.');return;}
  if(current?.status==='submitting')return;
  if(current&&/^(submit|confirm and submit|提交|确认提交)[.!。！]?$/i.test(text)){error('Use “Submit application” on the review card to confirm this application.');return;}
  chatBusy=true;error();const runId=current?.run_id,version=epoch;render();
  try{if(!runId)await prepare(text);else{const id=failedMessage?.runId===runId&&failedMessage.text===text&&failedMessage.key===key?failedMessage.id:crypto.randomUUID();optimistic.set(runId,[{id,role:'user',text}]);render();bottom();failedMessage={id,text,key,runId};await request(`/${runId}/chat`,{text,field_key:key,message_id:id,visual_fallback:$('#visual-fallback').checked});failedMessage=null;optimistic.delete(runId);await refresh();}if(epoch===version&&$('#chat-text').value.trim()===text)$('#chat-text').value='';}
  catch(e){if(runId)optimistic.delete(runId);error(e.message);}finally{chatBusy=false;render();}
}
async function act(action,body,id=current?.run_id){if(!current||current.run_id!==id||actionBusy||chatBusy)return false;const version=current.version;actionBusy=true;error();render();try{await request(`/${id}/${action}`,{expected_version:version,...body});if(body.answers)answerDrafts.clear(id);await refresh();return true;}catch(e){error(e.message);await refresh();return false;}finally{actionBusy=false;render();}}

let accountTarget=null;
function openAccount(item){
  const auth=item.account_request;accountTarget={id:item.run_id,origin:auth.origin,mode:auth.mode};
  $('#account-form').reset();$('#account-origin').textContent=auth.origin;
  $('#account-instructions').textContent=auth.instructions||'';
  $('#account-title').textContent=auth.mode==='register'?'Create your candidate account':'Sign in to your candidate account';
  $('#account-username').value=profile.email||'';$('#account-password').autocomplete=auth.mode==='register'?'new-password':'current-password';
  $('#account-submit').textContent=auth.mode==='register'?'Create account & continue':'Sign in & continue';
  $('#account-consents').replaceChildren();
  for(const c of auth.consents){const label=el('label',c.label,'check-row'),input=el('input');input.type='checkbox';input.dataset.key=c.key;input.required=c.required;label.prepend(input);$('#account-consents').append(label);}
  $('#account-dialog').showModal();
}
$('#account-close').addEventListener('click',()=>$('#account-dialog').close());
$('#account-dialog').addEventListener('close',()=>{$('#account-form').reset();accountTarget=null;});
$('#account-form').addEventListener('submit',async event=>{
  event.preventDefault();if(actionBusy||!accountTarget)return;
  const target=accountTarget;if(current?.run_id!==target.id||!current.account_request||current.account_request.origin!==target.origin||current.account_request.mode!==target.mode){$('#account-dialog').close();error('The account request changed. Reopen the current account form.');return;}
  const body={expected_version:current.version,origin:target.origin,mode:target.mode,username:$('#account-username').value,password:$('#account-password').value,consents:Object.fromEntries([...document.querySelectorAll('#account-consents input')].map(i=>[i.dataset.key,i.checked]))};
  $('#account-dialog').close();actionBusy=true;error();render();
  try{await request(`/${target.id}/account`,body);await refresh();}catch(e){error(e.message);}finally{body.password='';actionBusy=false;render();}
});
$('#agent-chat-form').addEventListener('submit',event=>{event.preventDefault();send($('#chat-text').value);});
$('#chat-text').addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();$('#agent-chat-form').requestSubmit();}});
$('#attach-resume').addEventListener('click',()=>$('#resume-file').click());$('#new-chat').addEventListener('click',()=>reset());
$('#pause-agent').addEventListener('click',()=>send(current?.pause_requested?'continue':'pause'));
$('#browser-toggle').addEventListener('click',()=>workspace($('#browser-panel').hidden));$('#browser-close').addEventListener('click',()=>workspace(false));
$('#take-over').addEventListener('click',()=>send('pause'));$('#cancel-attempt').addEventListener('click',()=>act('cancel',{}));
$('#history-toggle').addEventListener('click',()=>$('#history-panel').classList.toggle('open'));
const educationLabels={school:'School / university',degree:'Degree',field_of_study:'Major / field of study',start_date:'Start date (as written on resume)',end_date:'End / expected graduation date',graduation_status:'Graduation status (if known)'};
function educationEditor(record={}){
  const row=el('fieldset','','education-record');row.dataset.id=record.id||'';row.append(el('legend','Education'));
  for(const [key,text] of Object.entries(educationLabels)){const label=el('label',text),input=el('input');input.dataset.component=key;input.value=record[key]||'';input.maxLength=['school','degree','field_of_study'].includes(key)?300:100;label.append(input);row.append(label);}
  row.append(button('Remove education',()=>row.remove(),'quiet-button'));$('#education-fields').append(row);
}
$('#profile-toggle').addEventListener('click',()=>{
  $('#profile-fields').replaceChildren();for(const [key,label]of Object.entries(labels)){if(['school','degree'].includes(key)&&profile.education?.length)continue;const row=el('label',label),input=el('input');input.name=key;input.value=profile[key]||'';input.type=key==='email'?'email':'text';row.append(input);$('#profile-fields').append(row);}
  $('#education-fields').replaceChildren();for(const record of profile.education||[])educationEditor(record);$('#profile-dialog').showModal();
});
$('#add-education').addEventListener('click',()=>educationEditor());
$('#profile-close').addEventListener('click',()=>$('#profile-dialog').close());
$('#profile-form').addEventListener('submit',async event=>{
  event.preventDefault();const form=event.currentTarget,save=form.querySelector('[type=submit]');save.disabled=true;
  const education=[...form.querySelectorAll('.education-record')].map(row=>({id:row.dataset.id,...Object.fromEntries([...row.querySelectorAll('[data-component]')].map(i=>[i.dataset.component,i.value.trim()]))}));
  const hadEducation=Boolean(profile.education?.length);profile={...profile,...Object.fromEntries(new FormData(form)),education};
  if(education.length){profile.school=education[0].school;profile.degree=education[0].degree;}else if(hadEducation){profile.school='';profile.degree='';}
  try{const result=await persistCandidate();profile=result.profile;$('#profile-dialog').close();if(!current){draft.id=crypto.randomUUID();draft.payload=null;ask('Your details are saved for future applications.');advance();}}catch(e){error(e.message);}finally{save.disabled=false;}
});
$('#answer-memory').addEventListener('toggle',async()=>{if(!$('#answer-memory').open||!current)return;const id=current.run_id;try{const{memories}=await request(`/${id}/memory`);if(current?.run_id!==id)return;$('#memory-list').replaceChildren();if(!memories.length)$('#memory-list').append(el('p','No answers remembered yet.'));for(const m of memories){const row=el('div','','answer');row.append(el('strong',m.question),el('p',String(m.value)),button('Forget',async()=>{try{await request(`/${id}/memory/${m.memory_id}`,undefined,'DELETE');row.remove();}catch(e){error(e.message);}},'quiet-button'));$('#memory-list').append(row);}}catch(e){error(e.message);}});
async function restoreCandidate(){
  const version=extractionVersion;
  try{
    const saved=await request('/candidate');if(version!==extractionVersion)return;profile=saved.profile||{};
    if(saved.resume_base64){resume={name:saved.resume_name||'resume.pdf',encoded:saved.resume_base64};render();
      if(saved.needs_extraction){extracting=true;render();const result=await request('/resume-profile',{resume_base64:resume.encoded,resume_name:resume.name});if(version!==extractionVersion)return;profile={...result.profile};await persistCandidate({resume_base64:resume.encoded,resume_name:resume.name,extracted:!result.warning});}
    }
  }catch(e){error(`Could not restore saved details: ${e.message}`);}finally{restoring=false;if(version===extractionVersion)extracting=false;render();if(draft.url)advance();}
}
const initialUrl=new URLSearchParams(location.search).get('url');if(initialUrl){draft.url=initialUrl;draft.lastText=initialUrl;addDraft('user',initialUrl);}render();refresh();restoreCandidate();

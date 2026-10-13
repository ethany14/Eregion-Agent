// Full-page views next to the conversation: the Archive (archived and trash), The Road and The Forge.
import {api,organise,deleteForever,emptyTrash,confirmDialog,openMenu,toast} from './conversations.js';

const DAY=24*60*60*1000,RETENTION_DAYS=30;
const stageLabels={saved:'Saved',analyzing:'Analyzing',analysis_failed:'Analysis failed',needs_evidence:'Needs your evidence',
  materials_ready:'Materials ready',ready_to_apply:'Ready to apply',applied:'Applied',interviewing:'Interviewing',
  offer:'Offer',rejected:'Rejected',withdrawn:'Withdrawn',archived:'Archived'};
const shortDate=iso=>{try{return new Date(iso).toLocaleDateString('en',{month:'short',day:'numeric'});}catch{return '';}};

function header(ctx,title,extra=[]){
  const {el}=ctx,top=el('header','','page-top'),h=el('h1',title);
  const tools=el('div','','page-tools');tools.append(...extra);
  top.append(ctx.menuToggle(),h,tools);return top;
}

function describe(item){
  const job=item.jobs?.[0];
  if(job)return [job.company,stageLabels[job.status]].filter(Boolean).join(' · ');
  return item.application_run_id?'Browser application':'Conversation only';
}

// ---- Archived and Trash share one list with selection and a bulk bar ----
async function conversationList(ctx,container,kind){
  const {el,button,icon,groups}=ctx,trash=kind==='trash';
  const selected=new Set();let items=[],query='';
  const search=el('input','','page-search');search.type='search';search.placeholder='Search';search.setAttribute('aria-label','Search conversations');
  const tools=[search];
  if(trash){const empty=button('Empty Trash',async()=>{
    if(!items.length)return;
    if(!await confirmDialog({title:'Empty Trash?',text:`${items.length} ${items.length===1?'conversation':'conversations'} will be deleted permanently. This can’t be undone. Applications and materials are kept.`,confirmLabel:'Empty Trash',danger:true}))return;
    try{await emptyTrash();toast('Trash emptied');await load();}catch(e){ctx.error(e.message);}
  },'text-button');tools.push(empty);}
  const body=el('div','','page-body narrow'),note=el('p',trash?`Conversations in Trash are deleted permanently after ${RETENTION_DAYS} days. Applications and materials are never deleted with them.`:'Archived conversations are hidden from the sidebar. Sending a message to one brings it back.','page-note');
  const bulk=el('div','','bulk-bar'),list=el('div','','check-list');bulk.hidden=true;
  body.append(note,bulk,list);
  // Archived and Trash are two tabs of one Archive.
  const top=header(ctx,'Archive',tools),tabs=el('div','','page-tabs');tabs.setAttribute('role','group');tabs.setAttribute('aria-label','Archive');
  for(const [name,label] of [['archived','Archived'],['trash','Trash']]){
    const tab=button(label,()=>ctx.show(name),name===kind?'on':'');tab.dataset.view=name;tab.setAttribute('aria-pressed',String(name===kind));tabs.append(tab);
  }
  top.querySelector('h1').after(el('span',trash?'deleted for good after 30 days':'set aside, never lost','page-sub'),tabs);
  container.replaceChildren(top,body);

  const act=async(label,run)=>{try{await run([...selected]);selected.clear();await load();ctx.refresh();toast(label);}catch(e){ctx.error(e.message);}};
  function drawBulk(){
    bulk.hidden=!selected.size;bulk.replaceChildren();if(!selected.size)return;
    bulk.append(el('span',`${selected.size} selected`));
    const tools=el('div','','bulk-actions'),add=(label,name,fn,cls='')=>{const b=button('',fn,cls);b.append(icon(name),el('span',label));tools.append(b);return b;};
    add('Restore','restore',()=>act('Restored',ids=>Promise.all(ids.map(id=>organise(id,trash?{trashed:false}:{archived:false})))));
    if(trash){
      add('Delete permanently','trash',async()=>{
        const n=selected.size,name=n===1?`“${items.find(i=>selected.has(i.run_id))?.title}”`:`${n} conversations`;
        if(!await confirmDialog({title:'Delete permanently?',text:`${name} and ${n===1?'its':'their'} chat history will be removed for good. This can’t be undone. Applications and materials are kept.`,confirmLabel:'Delete permanently',danger:true}))return;
        act('Deleted permanently',ids=>Promise.all(ids.map(deleteForever)));
      });
    }else{
      const move=add('Move to group','folder',()=>openMenu(move,[...groups().map(g=>({label:g.name,action:()=>act(`Moved to ${g.name}`,ids=>Promise.all(ids.map(id=>organise(id,{group_id:g.group_id}))))})),
        {label:'No group',action:()=>act('Removed from group',ids=>Promise.all(ids.map(id=>organise(id,{group_id:null}))))}]));
      add('Move to Trash','trash',()=>act('Moved to Trash',ids=>Promise.all(ids.map(id=>organise(id,{trashed:true})))));
    }
    bulk.append(tools);
  }
  function draw(){
    list.replaceChildren();
    const visible=items.filter(i=>!query||`${i.title} ${describe(i)}`.toLowerCase().includes(query));
    if(!visible.length){list.append(el('p',query?'No conversations match your search.':trash?'Trash is empty.':'Nothing archived.','page-empty'));return;}
    for(const item of visible){
      const row=el('label','','check-row-item'),box=el('input');box.type='checkbox';box.checked=selected.has(item.run_id);
      box.addEventListener('change',()=>{box.checked?selected.add(item.run_id):selected.delete(item.run_id);drawBulk();});
      const when=trash?Math.max(0,RETENTION_DAYS-Math.floor((Date.now()-Date.parse(item.trashed_at))/DAY)):null;
      const date=el('span',trash?`${when} ${when===1?'day':'days'} left`:`Archived ${shortDate(item.archived_at)}`,'when');
      if(trash&&when<=3)date.classList.add('soon');
      row.append(box,el('span',item.title,'title'),el('span',trash?`Deleted ${shortDate(item.trashed_at)}`:describe(item),'meta'),date);
      list.append(row);
    }
  }
  async function load(){
    try{items=(await api(`/api/career/tasks?view=${trash?'trash':'archived'}`)).attempts.filter(a=>a.career);}
    catch(e){ctx.error(e.message);items=[];}
    for(const id of [...selected])if(!items.some(i=>i.run_id===id))selected.delete(id);
    draw();drawBulk();ctx.counts();
  }
  search.addEventListener('input',()=>{query=search.value.trim().toLowerCase();draw();});
  await load();
}

export async function renderPage(name,container,ctx){
  if(name==='alerts'){const {jobAlertsPage}=await import('./job-alerts.js');return jobAlertsPage(ctx,container,header);}
  if(name==='archived'||name==='trash')return conversationList(ctx,container,name);
  const pages=await import('./insights.js');
  if(name==='applications')return pages.applicationsPage(ctx,container,header);
  if(name==='materials')return pages.materialsPage(ctx,container,header);
}

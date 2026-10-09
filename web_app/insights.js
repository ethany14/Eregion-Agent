// Applications (overview and board) and the Materials library.
import {api,openMenu,toast} from './conversations.js';

const LABELS={saved:'Saved',analyzing:'Analyzing',analysis_failed:'Analysis failed',needs_evidence:'Needs evidence',
  materials_ready:'Materials ready',ready_to_apply:'Ready to apply',applied:'Applied',interviewing:'Interviewing',
  offer:'Offer',rejected:'Rejected',withdrawn:'Withdrawn',archived:'Archived'};
const STAGE={saved:1,analyzing:1,analysis_failed:1,needs_evidence:2,materials_ready:2,ready_to_apply:2,applied:3,interviewing:4,offer:5,rejected:3,withdrawn:3,archived:0};
const COLUMNS=[['Saved',['saved','analyzing','analysis_failed']],['Preparing',['needs_evidence','materials_ready','ready_to_apply']],
  ['Applied',['applied']],['Interviewing',['interviewing']],['Offer',['offer']],['Rejected',['rejected']]];
const CLOSED_COLUMN=['Withdrawn & archived',['withdrawn','archived']];
const FUNNEL_LABELS={saved:'Saved',analyzed:'Analyzed',applied:'Applied',interviewing:'Interviewing',offer:'Offer'};
const RAMP=['var(--ramp-5)','var(--ramp-4)','var(--ramp-3)','var(--ramp-2)','var(--ramp-1)'];
const fmtDate=(iso,opts={month:'short',day:'numeric'})=>{try{return new Date(iso).toLocaleDateString('en',opts);}catch{return '';}};
function relative(iso){
  const days=Math.floor((Date.now()-Date.parse(iso))/864e5);
  return days<=0?'Today':days===1?'Yesterday':days<7?`${days}d ago`:fmtDate(iso);
}
function remember(key,fallback){try{return localStorage.getItem(key)||fallback;}catch{return fallback;}}
function store(key,value){try{localStorage.setItem(key,value);}catch{/* Storage is optional. */}}

// ================= Applications =================
export async function applicationsPage(ctx,container,header){
  const {el,button,icon}=ctx;
  let mode=remember('northstar.applicationsMode','overview'),weeks=Number(remember('northstar.applicationsWeeks','10')),filter='active',data=null,showClosed=false;
  const seg=el('div','','segmented');seg.setAttribute('role','group');seg.setAttribute('aria-label','Layout');
  const modes={overview:button('Overview',()=>setMode('overview'),''),board:button('Board',()=>setMode('board'),'')};
  seg.append(modes.overview,modes.board);
  const range=el('select','','page-select');range.setAttribute('aria-label','Time range');
  for(const n of [4,10,26]){const o=el('option',`Last ${n} weeks`);o.value=String(n);range.append(o);}range.value=String(weeks);
  range.addEventListener('change',()=>{weeks=Number(range.value);store('northstar.applicationsWeeks',range.value);load();});
  const closedToggle=el('label','','page-check');const closedBox=el('input');closedBox.type='checkbox';
  closedToggle.append(closedBox,el('span','Show withdrawn & archived'));closedBox.addEventListener('change',()=>{showClosed=closedBox.checked;draw();});
  const top=header(ctx,'Applications',[range,closedToggle]);top.querySelector('h1').after(seg);
  const body=el('div','','page-body');container.replaceChildren(top,body);

  function setMode(next){mode=next;store('northstar.applicationsMode',next);draw();}
  async function load(){
    try{data=await api(`/api/applications/overview?weeks=${weeks}`);}catch(e){ctx.error(e.message);data=null;}
    draw();
  }
  function draw(){
    for(const [name,b] of Object.entries(modes))b.setAttribute('aria-pressed',String(mode===name));
    range.hidden=mode!=='overview';closedToggle.hidden=mode!=='board';
    body.replaceChildren();
    if(!data){body.append(el('p','Applications could not be loaded.','page-empty'));return;}
    if(!data.applications.length){
      const empty=el('div','','page-empty');empty.append(el('p','No applications yet. Share a job link in a conversation and it will appear here.'));
      empty.append(button('Start a conversation',()=>ctx.send(''),'primary-button'));body.append(empty);return;
    }
    mode==='board'?drawBoard():drawOverview();
  }

  function drawOverview(){
    const needs=ctx.needsYou(),t=data.totals,waiting=data.applications.filter(a=>needs.has(a.application_id)).length;
    const kpis=el('div','','kpis');
    for(const [value,label,cls] of [[t.tracked,'Tracked'],[t.applied,'Applied'],[t.interviewing,'Interviewing'],
      [t.response_rate==null?'–':t.response_rate,'Response rate',t.response_rate==null?'':'pct'],[waiting,'Need you','signal']]){
      const k=el('div','',`kpi ${cls||''}`),num=el('strong',String(value),'kpi-value');if(cls==='pct')num.append(el('sup','%'));
      k.append(num,el('span',label,'kpi-label'));
      if(cls==='signal'&&waiting){k.classList.add('link');k.tabIndex=0;k.setAttribute('role','button');
        const go=()=>{filter='needs';draw();body.querySelector('.ftabs')?.scrollIntoView({behavior:'smooth'});};k.addEventListener('click',go);k.addEventListener('keydown',e=>{if(e.key==='Enter')go();});}
      kpis.append(k);
    }
    const charts=el('div','','charts');charts.append(funnelChart(),weeklyChart());
    body.append(kpis,charts,tableSection(needs));
  }

  function chartShell(title,note,draw,rows){
    const card=el('section','','chart'),head=el('div','','chart-head'),table=button('Table',()=>{showTable=!showTable;render();},'text-button chart-toggle');
    let showTable=false;head.append(el('h3',title),el('span',note,'chart-note'),table);
    const area=el('div');card.append(head,area);
    function render(){table.textContent=showTable?'Chart':'Table';table.setAttribute('aria-pressed',String(showTable));area.replaceChildren(showTable?dataTable(rows):draw());}
    render();return card;
  }
  function dataTable(rows){
    const tableNode=el('table','','mini-table'),thead=el('thead'),tr=el('tr');
    for(const h of rows[0])tr.append(el('th',h));thead.append(tr);tableNode.append(thead);
    const tbody=el('tbody');for(const r of rows.slice(1)){const row=el('tr');for(const c of r)row.append(el('td',String(c)));tbody.append(row);}
    tableNode.append(tbody);return tableNode;
  }
  function funnelChart(){
    const max=Math.max(1,...data.funnel.map(s=>s.count));
    const rows=[['Stage','Count','From previous'],...data.funnel.map((s,i)=>[FUNNEL_LABELS[s.stage],s.count,i&&data.funnel[i-1].count?`${Math.round(100*s.count/data.funnel[i-1].count)}%`:'–'])];
    return chartShell('Pipeline','Saved → Offer',()=>{
      const list=el('div','','funnel');
      data.funnel.forEach((s,i)=>{
        const row=el('div','','fr'),track=el('div','','track'),bar=el('span','','bar');
        bar.style.width=`${Math.max(s.count?1.5:0,72*s.count/max)}%`;bar.style.background=RAMP[i];
        const prev=i?data.funnel[i-1].count:0,rate=i&&prev?`${Math.round(100*s.count/prev)}%`:'';
        bar.title=`${FUNNEL_LABELS[s.stage]}: ${s.count}${rate?` (${rate} of previous stage)`:''}`;
        track.append(bar,el('b',String(s.count)));if(rate)track.append(el('small',rate));
        row.append(el('span',FUNNEL_LABELS[s.stage]),track);list.append(row);
      });
      return list;
    },rows);
  }
  function weeklyChart(){
    const counts=data.weekly.map(w=>w.count),max=Math.max(1,...counts),total=counts.reduce((a,b)=>a+b,0);
    const rows=[['Week of','Applications sent'],...data.weekly.map(w=>[fmtDate(w.week_start),w.count])];
    return chartShell('Sent per week',`${total} total`,()=>{
      const wrap=el('div','','weeks-wrap'),plot=el('div','','weeks'),labels=el('div','','wl'),tip=el('div','','chart-tip');tip.hidden=true;
      const every=data.weekly.length>12?4:2;
      data.weekly.forEach((w,i)=>{
        const last=i===data.weekly.length-1,col=el('div','','week'),bar=el('i','',last?'now':'');
        bar.style.height=w.count?`${100*w.count/max}%`:'2px';
        if(last&&w.count)bar.append(el('em',String(w.count)));
        col.tabIndex=0;col.setAttribute('aria-label',`Week of ${fmtDate(w.week_start)}: ${w.count} sent`);
        const show=()=>{const end=new Date(Date.parse(w.week_start)+6*864e5);tip.replaceChildren(el('b',`${fmtDate(w.week_start)} – ${fmtDate(end)}`),el('span',`${w.count} ${w.count===1?'application':'applications'} sent`));
          tip.hidden=false;const r=col.getBoundingClientRect(),p=wrap.getBoundingClientRect();tip.style.left=`${Math.min(r.left-p.left+r.width/2,p.width-90)}px`;tip.style.top=`${Math.max(0,r.top-p.top+col.offsetHeight-bar.offsetHeight-58)}px`;col.classList.add('hover');};
        const hide=()=>{tip.hidden=true;col.classList.remove('hover');};
        col.addEventListener('pointerenter',show);col.addEventListener('pointerleave',hide);col.addEventListener('focus',show);col.addEventListener('blur',hide);
        col.append(bar);plot.append(col);
        // The neighbour of "This week" stays blank so the two labels never collide.
        labels.append(el('span',last?'This week':i%every===0&&i<data.weekly.length-2?fmtDate(w.week_start):''));
      });
      wrap.append(plot,labels,tip);return wrap;
    },rows);
  }

  function tableSection(needs){
    const section=el('section','','app-table'),tabs=el('div','','ftabs'),apps=data.applications;
    const groups={active:a=>!['rejected','withdrawn','archived'].includes(a.status),all:a=>a.status!=='archived',
      needs:a=>needs.has(a.application_id),interviewing:a=>a.status==='interviewing',rejected:a=>a.status==='rejected',withdrawn:a=>a.status==='withdrawn'};
    const names={active:'Active',all:'All',needs:'Need you',interviewing:'Interviewing',rejected:'Rejected',withdrawn:'Withdrawn'};
    for(const [key,test] of Object.entries(groups)){
      const n=apps.filter(test).length;if(key==='needs'&&!n)continue;
      const b=button('',()=>{filter=key;draw();},key===filter?'on':'');b.append(el('span',names[key]),el('b',String(n)));b.setAttribute('aria-pressed',String(key===filter));tabs.append(b);
    }
    const rows=apps.filter(groups[filter]||groups.active).sort((a,b)=>b.updated_at.localeCompare(a.updated_at));
    const table=el('table','','tbl'),head=el('tr');
    for(const [label,cls] of [['Company','w-co'],['Role',''],['Stage',''],['Match','w-num'],['Updated','w-date']])head.append(el('th',label,cls));
    const thead=el('thead');thead.append(head);table.append(thead);const tbody=el('tbody');
    for(const a of rows){
      const tr=el('tr'),co=el('td','','co'),stage=el('td'),pips=el('span','','pips');
      co.append(el('span',a.company||'Unknown company'));if(needs.has(a.application_id))co.append(el('span','','dot'));
      for(let i=1;i<=5;i++)pips.append(el('i','',i<=STAGE[a.status]?'f':''));
      stage.append(pips,el('span',LABELS[a.status]||a.status,['rejected','withdrawn'].includes(a.status)?'muted':''));
      tr.append(co,el('td',a.title||'—'),stage,el('td',a.match_score==null?'—':String(Math.round(a.match_score)),'num'),el('td',relative(a.updated_at),'mut'));
      tr.tabIndex=0;tr.setAttribute('role','link');tr.setAttribute('aria-label',`Open ${a.company||'application'} ${a.title||''}`);
      const open=()=>ctx.openApplication(a.application_id);tr.addEventListener('click',open);tr.addEventListener('keydown',e=>{if(e.key==='Enter')open();});
      tbody.append(tr);
    }
    table.append(tbody);
    section.append(tabs,rows.length?table:el('p','Nothing here.','page-empty'));return section;
  }

  // ---- Board ----
  async function move(app,target){
    try{
      await api(`/api/applications/${encodeURIComponent(app.application_id)}/status`,{method:'PATCH',
        body:{target_status:target,expected_version:app.version,...(target==='applied'?{applied_at:new Date().toISOString()}:{})}});
      toast(`${app.company||'Application'} moved to ${LABELS[target]}`);
    }catch(e){toast(`Couldn’t move ${app.company||'this application'}: ${e.message}`);}
    await load();
  }
  function cardMenu(app,anchor){
    const moves=(app.next_statuses||[]).filter(s=>s!=='analyzing').map(s=>({label:`Move to ${LABELS[s]}`,action:()=>move(app,s),danger:s==='archived'}));
    openMenu(anchor,[{label:'Open conversation',action:()=>ctx.openApplication(app.application_id)},...(moves.length?[{separator:true},...moves]:[])]);
  }
  function drawBoard(){
    const needs=ctx.needsYou(),board=el('div','','board'),columns=showClosed?[...COLUMNS,CLOSED_COLUMN]:COLUMNS;
    board.style.setProperty('--cols',String(columns.length));
    let dragging=null;
    const cols=columns.map(([title,statuses])=>{
      const col=el('section','','bcol'),items=data.applications.filter(a=>statuses.includes(a.status)).sort((a,b)=>b.updated_at.localeCompare(a.updated_at));
      const h=el('h4',title);h.append(el('span',String(items.length)));col.append(h);
      const list=el('div','','bcol-list');col.append(list);
      col.addEventListener('dragover',e=>{if(dragging&&statuses.some(s=>dragging.next_statuses.includes(s))){e.preventDefault();col.classList.add('drop-ok');}});
      col.addEventListener('dragleave',e=>{if(!col.contains(e.relatedTarget))col.classList.remove('drop-ok');});
      col.addEventListener('drop',e=>{e.preventDefault();col.classList.remove('drop-ok');const target=statuses.find(s=>dragging?.next_statuses.includes(s));if(dragging&&target)move(dragging,target);});
      for(const a of items){
        const card=el('article','',['rejected','withdrawn','archived'].includes(a.status)?'bcard closed':'bcard');card.draggable=true;
        if(needs.has(a.application_id))card.append(el('span','','dot'));
        const more=button('',()=>cardMenu(a,more),'more');more.append(icon('dots'));more.setAttribute('aria-label',`Options for ${a.company||'application'}`);more.setAttribute('aria-haspopup','menu');
        const open=button('',()=>ctx.openApplication(a.application_id),'bcard-open');open.append(el('b',a.company||'Unknown company'),el('span',a.title||'','role'));
        const foot=el('div','','ft');
        foot.append(el('span',a.match_score==null?LABELS[a.status]:`Match ${Math.round(a.match_score)}`),el('span',relative(a.updated_at)));
        card.append(open,foot,more);
        card.addEventListener('dragstart',e=>{dragging=a;e.dataTransfer.effectAllowed='move';e.dataTransfer.setData('text/plain',a.application_id);card.classList.add('dragging');
          for(const [c,[,s]] of cols.map((c,i)=>[c,columns[i]]))c.classList.toggle('drop-blocked',!s.some(x=>a.next_statuses.includes(x))&&!s.includes(a.status));});
        card.addEventListener('dragend',()=>{dragging=null;card.classList.remove('dragging');for(const c of cols)c.classList.remove('drop-blocked','drop-ok');});
        list.append(card);
      }
      if(!items.length)list.append(el('p','—','bcol-empty'));
      return col;
    });
    board.append(...cols);
    body.append(el('p','Drag a card to update its stage, or use its ⋯ menu. Only moves the application allows are accepted.','page-note'),board);
  }
  await load();
}

// ================= Materials =================
export async function materialsPage(ctx,container,header){
  const {el,button,icon}=ctx;
  let items=[],typeFilter='all',statusFilter='',query='',selected=null,candidate=null,detail=null,versionIndex=null;
  const search=el('input','','page-search');search.type='search';search.placeholder='Search materials';search.setAttribute('aria-label','Search materials');
  const upload=button('',()=>document.querySelector('#resume-file')?.click(),'text-button');upload.append(icon('plus'),el('span','Upload resume'));
  const top=header(ctx,'Materials',[search,upload]),layout=el('div','','mat'),filters=el('nav','','mfil'),list=el('div','','mlist'),preview=el('aside','','mprev');
  filters.setAttribute('aria-label','Filter materials');layout.append(filters,list,preview);container.replaceChildren(top,layout);
  search.addEventListener('input',()=>{query=search.value.trim().toLowerCase();drawList();});

  const status=m=>m.stale?'outdated':m.status==='approved'?'approved':m.status==='awaiting_review'?'review':m.status==='failed'?'failed':'draft';
  const statusText={approved:'Approved',review:'Needs review',outdated:'Outdated',failed:'Needs attention',draft:'In progress'};
  async function load(){
    try{
      const [mats,cand]=await Promise.all([api('/api/materials'),api('/api/auto-apply/candidate').catch(()=>null)]);
      items=mats.materials;candidate=cand?.resume_base64?cand:null;
    }catch(e){ctx.error(e.message);items=[];}
    if(selected&&!items.some(m=>m.pack_item_id===selected.pack_item_id))selected=null;
    if(!selected&&items.length)await choose(items[0],false);
    drawFilters();drawList();drawPreview();
  }
  function drawFilters(){
    filters.replaceChildren();
    const types=[['all','All',items.length+(candidate?1:0)],['base','Base resume',candidate?1:0],['tailored_resume','Tailored resumes'],['cover_letter','Cover letters'],['application_answer','Application answers']];
    for(const [key,label,n] of types){
      const count=n??items.filter(m=>m.artifact_type===key).length;if(key==='application_answer'&&!count)continue;
      const b=button('',()=>{typeFilter=key;drawFilters();drawList();},typeFilter===key?'on':'');b.append(el('span',label),el('span',String(count),'n'));b.setAttribute('aria-pressed',String(typeFilter===key));filters.append(b);
    }
    filters.append(el('p','Status','side-label'));
    for(const key of ['approved','review','outdated']){
      const count=items.filter(m=>status(m)===key).length;
      const b=button('',()=>{statusFilter=statusFilter===key?'':key;drawFilters();drawList();},statusFilter===key?'on':'');b.append(el('span',statusText[key]),el('span',String(count),'n'));b.setAttribute('aria-pressed',String(statusFilter===key));filters.append(b);
    }
  }
  const thumb=()=>{const t=el('span','','thumb');for(const w of [100,100,70,100])t.append(Object.assign(el('i'),{style:`width:${w}%`}));return t;};
  function drawList(){
    list.replaceChildren();
    if(candidate&&['all','base'].includes(typeFilter)&&!statusFilter&&(!query||candidate.resume_name.toLowerCase().includes(query))){
      list.append(el('p','Base','mg'));
      const row=button('',()=>{selected={base:true};detail=null;drawList();drawPreview();},selected?.base?'mi on':'mi');
      const text=el('span','','t');text.append(el('b',candidate.resume_name||'resume.pdf'),el('small','Your original resume · used for every application'));
      row.append(thumb(),text);list.append(row);
    }
    const visible=typeFilter==='base'?[]:items.filter(m=>(typeFilter==='all'||m.artifact_type===typeFilter)&&(!statusFilter||status(m)===statusFilter)
      &&(!query||`${m.label} ${m.company} ${m.title} ${m.source_question||''}`.toLowerCase().includes(query)));
    let group='';
    for(const m of visible){
      const g=`${m.company||'Unknown company'} · ${m.title||''}`;if(g!==group){group=g;list.append(el('p',g,'mg'));}
      const row=button('',()=>choose(m),selected?.pack_item_id===m.pack_item_id?'mi on':'mi'),text=el('span','','t');
      text.append(el('b',m.artifact_type==='application_answer'&&m.source_question?m.source_question:m.label),el('small',`Version ${m.version} · ${relative(m.updated_at)}`));
      row.append(thumb(),text,el('span',statusText[status(m)],`st ${status(m)}`));list.append(row);
    }
    if(!visible.length&&!(candidate&&['all','base'].includes(typeFilter)))list.append(el('p',items.length?'No materials match.':'No materials yet. Ask for a tailored resume in a conversation.','page-empty'));
  }
  async function choose(m,draw=true){
    selected=m;detail=null;versionIndex=null;if(draw){drawList();drawPreview();}
    try{detail=await api(`/api/materials/${encodeURIComponent(m.pack_id)}/${encodeURIComponent(m.pack_item_id)}`);}catch(e){ctx.error(e.message);}
    if(selected===m&&draw)drawPreview();
  }
  function drawPreview(){
    preview.replaceChildren();
    if(!selected){preview.append(el('p','Select a document to preview it.','page-empty'));return;}
    if(selected.base){
      preview.append(el('h2',candidate.resume_name||'Resume'),el('p','Your original resume. Tailored versions always trace back to it.','sub'));
      const actions=el('div','','actions');
      const download=button('',()=>{const bytes=Uint8Array.from(atob(candidate.resume_base64),c=>c.charCodeAt(0)),url=URL.createObjectURL(new Blob([bytes],{type:'application/pdf'}));
        const a=Object.assign(document.createElement('a'),{href:url,download:candidate.resume_name||'resume.pdf'});a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);},'primary-button');
      download.append(icon('dl'),el('span','Download PDF'));
      actions.append(download,button('Replace',()=>document.querySelector('#resume-file')?.click(),'secondary-button'));preview.append(actions);return;
    }
    const m=selected;
    preview.append(el('h2',m.artifact_type==='application_answer'&&m.source_question?m.source_question:m.label),el('p',[m.company,m.title].filter(Boolean).join(' · '),'sub'));
    const versions=detail?.versions||[];const shown=versions[versionIndex??versions.length-1];
    const vers=el('div','','vers');
    versions.forEach((v,i)=>{const b=button(`v${v.version}${i===versions.length-1?' · current':''}`,()=>{versionIndex=i;drawPreview();},(versionIndex??versions.length-1)===i?'on':'');vers.append(b);});
    if(m.verified!=null)vers.append(el('span',m.verified?'Every claim verified against your resume':`${m.issues} ${m.issues===1?'claim needs':'claims need'} attention`,m.verified?'verify':'verify warn'));
    preview.append(vers);
    const sheet=el('div','','sheet');sheet.append(el('pre',shown?.text||(detail?'This version has no text yet.':'Loading…')));preview.append(sheet);
    const actions=el('div','','actions'),s=status(m);
    if(s==='review'){const approve=button('Approve this version',async()=>{approve.disabled=true;
      try{await api(`/api/packs/${encodeURIComponent(m.pack_id)}/items/${encodeURIComponent(m.pack_item_id)}/approve`,{method:'POST',body:{expected_version:m.version,idempotency_key:`library-approve:${m.pack_item_id}:${m.version}`}});toast('Approved');await load();}
      catch(e){ctx.error(e.message);approve.disabled=false;}},'primary-button');actions.append(approve);}
    if(s==='outdated'){const regen=button('Regenerate',async()=>{regen.disabled=true;regen.textContent='Regenerating…';
      try{await api(`/api/packs/${encodeURIComponent(m.pack_id)}/items/${encodeURIComponent(m.pack_item_id)}/regenerate`,{method:'POST',body:{expected_version:m.version,idempotency_key:`library-regenerate:${m.pack_item_id}:${m.version}`}});toast('Regenerated');await load();}
      catch(e){ctx.error(e.message);regen.disabled=false;regen.textContent='Regenerate';}},'primary-button');actions.append(regen);}
    if(m.pdf){const a=el('a','','secondary-button');a.href=m.pdf;a.append(icon('dl'),el('span','Download PDF'));actions.append(a);}
    actions.append(button('Open conversation',()=>ctx.openApplication(m.application_id),'secondary-button'),
      button('Copy text',async()=>{try{await navigator.clipboard.writeText(shown?.text||'');toast('Copied');}catch{toast('Select the text to copy it');}},'secondary-button'));
    if(s==='review')actions.append(button('Request changes',()=>ctx.openApplication(m.application_id,`I want to revise the ${m.label.toLowerCase()} for ${m.company||'this job'}. Ask me what I would like to change.`),'secondary-button'));
    preview.append(actions);
  }
  await load();
}

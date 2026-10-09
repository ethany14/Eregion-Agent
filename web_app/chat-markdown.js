import {Lexer} from './vendor/marked-18.1.0.js';

// Render a deliberately small set of semantic DOM elements. HTML tokens remain
// inert text, and images never cause background requests to third-party hosts.
const entities={amp:'&',lt:'<',gt:'>',quot:'"',apos:"'",nbsp:'\u00a0',copy:'©',ndash:'–',mdash:'—'};
function decode(text=''){
  return String(text).replace(/&(#x[\da-f]+|#\d+|[a-z]+);/gi,(source,key)=>{
    if(key[0]!=='#')return Object.hasOwn(entities,key)?entities[key]:source;
    const value=key[1].toLowerCase()==='x'?parseInt(key.slice(2),16):Number(key.slice(1));
    return value>0&&value<=0x10ffff&&!(value>=0xd800&&value<=0xdfff)?String.fromCodePoint(value):'\ufffd';
  });
}

export function safeMarkdownLink(href){
  const value=decode(href).trim();
  if(/[\u0000-\u0020\u007f]/.test(value))return null;
  // Relative paths must stay on this application; protocol-relative links are
  // not needed for generated answers. No data:, javascript:, or file: URLs.
  if(/^\/(?![\/\\])/.test(value))return value;
  try{const url=new URL(value);return ['https:','http:','mailto:'].includes(url.protocol)?url.href:null;}
  catch{return null;}
}

export function renderMarkdown(source,doc=document){
  const root=doc.createElement('div');root.className='message-body';
  const element=(tag,parent)=>{const node=doc.createElement(tag);parent.append(node);return node;};
  const text=(parent,value)=>parent.append(doc.createTextNode(decode(value)));
  function render(tokens,parent,depth=0){
    if(depth>24){for(const token of tokens)text(parent,token.raw||token.text||'');return;}
    for(const token of tokens){
      switch(token.type){
        case 'space':break;
        case 'paragraph':render(token.tokens,element('p',parent),depth+1);break;
        case 'heading':{
          // Keep headings inside the conversation's hierarchy and scale.
          const heading=element(token.depth<=2?'h3':'h4',parent);
          render(token.tokens,heading,depth+1);break;
        }
        case 'text':
          if(token.tokens)render(token.tokens,parent,depth+1);else text(parent,token.text);
          break;
        case 'escape':text(parent,token.text);break;
        case 'strong':case 'em':case 'del':render(token.tokens,element(token.type,parent),depth+1);break;
        case 'codespan':element('code',parent).textContent=token.text;break;
        case 'br':element('br',parent);break;
        case 'hr':element('hr',parent);break;
        case 'code':{
          const frame=element('div',parent);frame.className='code-block';
          if(token.lang){const label=element('div',frame);label.className='code-language';label.textContent=token.lang.split(/\s/)[0].slice(0,40);}
          const pre=element('pre',frame);pre.tabIndex=0;
          element('code',pre).textContent=token.text;break;
        }
        case 'blockquote':render(token.tokens,element('blockquote',parent),depth+1);break;
        case 'list':{
          const list=element(token.ordered?'ol':'ul',parent);
          if(token.ordered&&Number.isSafeInteger(token.start)&&token.start>0)list.start=token.start;
          for(const item of token.items){
            const li=element('li',list);
            if(item.task){
              li.className='task-list-item';
              const check=element('input',li);check.type='checkbox';check.checked=Boolean(item.checked);check.disabled=true;
              check.setAttribute('aria-label',check.checked?'Completed':'Not completed');
            }
            render(item.tokens,li,depth+1);
          }
          break;
        }
        case 'link':case 'image':{
          const href=safeMarkdownLink(token.href);
          const target=href?element('a',parent):element('span',parent);
          if(href){target.href=href;target.target='_blank';target.rel='noopener noreferrer';target.referrerPolicy='no-referrer';}
          if(token.type==='image')text(target,token.text||'Image');
          else render(token.tokens||[{type:'text',text:token.text}],target,depth+1);
          break;
        }
        case 'table':{
          const wrapper=element('div',parent);wrapper.className='message-table';wrapper.tabIndex=0;
          wrapper.setAttribute('role','region');wrapper.setAttribute('aria-label','Scrollable comparison table');
          const table=element('table',wrapper),row=element('tr',element('thead',table));
          token.header.forEach((cell,index)=>{const th=element('th',row);th.scope='col';if(token.align[index])th.style.textAlign=token.align[index];render(cell.tokens,th,depth+1);});
          const body=element('tbody',table);
          for(const cells of token.rows){const tr=element('tr',body);cells.forEach((cell,index)=>{
            const td=element('td',tr);if(token.align[index])td.style.textAlign=token.align[index];render(cell.tokens,td,depth+1);
          });}
          break;
        }
        // Never execute HTML supplied by a model, a job page, or a document.
        default:text(parent,token.raw||token.text||'');
      }
    }
  }
  try{render(Lexer.lex(String(source??''),{gfm:true,breaks:true}),root);}
  catch{root.replaceChildren();const fallback=element('p',root);fallback.className='plain-message';fallback.textContent=String(source??'');}
  return root;
}

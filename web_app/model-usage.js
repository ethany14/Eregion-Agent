// Counts reported by providers. Missing usage is explicit, never estimated as zero.
export function usageText(usage){
  if(!usage?.calls)return '';
  const count=n=>Number(n||0).toLocaleString('en-US');
  const known=usage.calls-usage.unknown_usage_calls;
  const tokens=known?`${count(usage.input_tokens)} input / ${count(usage.output_tokens)} output tokens reported`:'Token counts unavailable';
  const missing=usage.unknown_usage_calls?` · ${count(usage.unknown_usage_calls)} ${usage.unknown_usage_calls===1?'call':'calls'} without complete usage`:'';
  const discarded=usage.discarded?` · ${count(usage.discarded)} discarded`:'';
  return `${count(usage.calls)} model ${usage.calls===1?'call':'calls'} · ${tokens}${missing}${discarded}`;
}

export function renderUsage(container,usage){
  container.replaceChildren();container.hidden=!usage?.calls;
  if(!usage?.calls)return;
  const heading=document.createElement('summary');heading.textContent='Usage by task';container.append(heading);
  const list=document.createElement('ul');
  for(const group of usage.groups||[]){
    const item=document.createElement('li');
    item.textContent=`${group.purpose.replaceAll('_',' ')} · ${group.model}: ${usageText(group)}`;
    list.append(item);
  }
  container.append(list);
}

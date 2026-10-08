"""Source-backed education records and coverage of repeated form entries."""
import calendar
import hashlib
import json
import re

COMPONENTS = ("school","degree","field_of_study","start_date","end_date","graduation_status",
              "start_year","start_month","end_year","end_month")


def normalize_records(records):
    result=[];seen=set();ids=set()
    for record in records:
        value={k:str(record.get(k) or '').strip() for k in COMPONENTS[:6]}
        if not any(value.values()):continue
        fingerprint=json.dumps(value,sort_keys=True)
        if fingerprint in seen:continue
        seen.add(fingerprint)
        identifier=record.get('id') or 'edu-'+hashlib.sha256(fingerprint.encode()).hexdigest()[:16]
        if identifier in ids:identifier+='-'+str(len(result))
        ids.add(identifier);result.append({'id':identifier,**value})
    return result


def date_parts(text):
    text=str(text).strip().casefold()
    years=re.findall(r'\b(?:19|20)\d{2}\b',text)
    result={'year':years[0]} if len(years)==1 else {}
    for month in range(1,13):
        if re.search(r'\b(?:'+calendar.month_name[month].lower()+'|'+calendar.month_abbr[month].lower()+r')\b',text):
            result['month']=str(month);break
    iso=re.fullmatch(r'((?:19|20)\d{2})[-/](0?[1-9]|1[0-2])',text)
    reverse=re.fullmatch(r'(0?[1-9]|1[0-2])[-/]((?:19|20)\d{2})',text)
    if iso:result.update(year=iso[1],month=str(int(iso[2])))
    if reverse:result.update(year=reverse[2],month=str(int(reverse[1])))
    return result


def facts(profile):
    result={}
    for record in profile.get('education',[]):
        values={k:record.get(k,'') for k in COMPONENTS[:6]}
        for part in ('start','end'):
            values.update({f'{part}_{k}':v for k,v in date_parts(values[f'{part}_date']).items()})
        for component,value in values.items():
            if value:result[f"education:{record['id']}:{component}"]=value
    return result


def binding(field,state):
    saved=state.get('education_bindings',{}).get(field['key'])
    if not saved:return None
    if saved.get('field')!={k:field.get(k) for k in ('key','dom_id','label','group')}:return None
    return saved


def bound_value(field,state):
    saved=binding(field,state)
    return facts(state['profile']).get(saved['source_ref']) if saved else None


def repeatable(page):
    return any(c.get('kind')=='add_entry' and re.search(r'education|school|academic',
        c.get('label','')+' '+c.get('section','')+' '+str(c.get('automation_id') or ''),re.I) for c in (page or {}).get('controls',[]))


def gaps(state,fields,page,*,final=False):
    """Once a repeatable education section is offered, don't skip known records.

    Completion uses the bound fields' actual values, including optional fields.
    It does not turn an agent's 'done' statement into evidence of filling them.
    """
    from .autofill import desired_answer,matches
    records=state['profile'].get('education',[])
    if not records:return []
    current=any(binding(f,state) for f in fields)
    multiple=repeatable(page) or (state.get('education_required') and (current or final))
    if not current and not multiple:return []
    all_fields={f['key']:f for f in state.get('review_fields',[]) if final}
    all_fields.update({f['key']:f for f in fields})
    represented=set();pending=[]
    for field in all_fields.values():
        item=binding(field,state)
        if not item:continue
        value=desired_answer(field,state)
        if value is None:continue
        if matches(field,value):
            if item['component']=='school':represented.add(item['education_id'])
        else:pending.append(field['label'])
    if multiple:
        pending.extend(f"Add/complete education: {r.get('school') or r['id']} ({r.get('degree','')})"
            for r in records if r['id'] not in represented)
    # These columns commonly remain optional even when the resume supplies them.
    # The model assigns their record/component; they must not be silently skipped.
    for field in fields:
        if binding(field,state):continue
        label=field.get('label','').lower()
        component=next((name for name,pattern in [('school',r'\b(school|university|college|institution)\b'),('degree',r'\bdegree\b'),('field_of_study',r'field of study|major|discipline')] if re.search(pattern,label)),None)
        if component and any(r.get(component) for r in records):pending.append('Map education field: '+field['label'])
        education_section=re.search(r'education|academic|school',field.get('section',''),re.I)
        if education_section and re.search(r'\b(from|to|start|end|graduation)\b',label+' '+field.get('group',''),re.I) and re.search(r'year|month|date',label,re.I):
            component='start' if re.search(r'\b(from|start)\b',label+' '+field.get('group',''),re.I) else 'end'
            part='month' if 'month' in label else 'year' if 'year' in label else 'date'
            if any((r.get(component+'_date') if part=='date' else date_parts(r.get(component+'_date','')).get(part)) for r in records):pending.append('Map education date: '+field['label'])
    return list(dict.fromkeys(pending))

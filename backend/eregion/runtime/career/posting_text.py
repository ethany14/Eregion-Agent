"""Source-bound LinkedIn job section, with original text retained for audit."""
import re


def header(text):
    """Read the URL-bound opening header, never a company address later in the JD."""
    lines=[m for m in re.finditer(r'[^\n]+',text or '') if m[0].strip()]
    if len(lines)<3:return {}
    company,title,place=[m[0].strip() for m in lines[:3]]
    if any(len(v)>240 for v in (company,title,place)) or title.casefold()=='about the job':return {}
    match=re.fullmatch(r'(.+?)\s+·\s+(?:Reposted\s+)?(?:\d+\s+(?:minute|hour|day|week|month|year)s?\s+ago|Just now|Today|Yesterday)\b.*',place,re.I)
    if not match:return {}
    location=match[1].strip()
    return {'company':company,'title':title,'location':location,
            'metadata_evidence':{field:{'quote':m[0].strip(),'start':m.start()+len(m[0])-len(m[0].lstrip()),
                                        'end':m.start()+len(m[0].rstrip())}
                                 for field,m in zip(('company','title','location'),lines[:3])}}


def scope(text):
    start=re.search(r'(?im)^\s*About the job\s*$',text or '')
    if not start:return {'text':text or '', 'start':0,'end':len(text or ''),'bounded':False}
    offset=start.end()
    stop=re.search(r'(?im)^\s*(?:Set alert for similar jobs|About the company|More jobs|'
                   r'Unlock hiring insights[^\n]*|Applicant (?:seniority|education) level)\s*$',text[offset:])
    end=offset+stop.start() if stop else len(text)
    body=text[offset:end];left=len(body)-len(body.lstrip());right=len(body.rstrip())
    return {'text':body.strip(),'start':offset+left,'end':offset+right,'bounded':True}


def qualification_lines(text):
    """Inspect the complete scoped JD once, not just its first eight matching lines."""
    lines=[]
    for m in re.finditer(r'[^\n]+',text or ''):
        if re.search(r'\byears?\b|entry[- ]level|junior|graduate|qualification|requirements|'
                     r'work location|based in|located in|work from',m[0],re.I):
            lines.append({'quote':m[0][:400],'start':m.start(),'end':min(m.end(),m.start()+400)})
    # Put explicit experience evidence ahead of generic headings/benefits.
    lines.sort(key=lambda v:not bool(re.search(r'\b\d+\s*[-–+]?\s*\d*\s+years?\b',v['quote'],re.I)))
    return lines[:12]

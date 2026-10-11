"""Read-only public job discovery. No candidate data or cookies are sent here."""
import html
import base64
import ipaddress
import json
import re
import socket
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlsplit

import httpx
from agent_runtime.auto_apply.contracts import public_https_url


def location_matches(requested, observed):
    """Compare explicit city/state components; do not conflate a state and city."""
    from agent_runtime.auto_apply.matching import US_STATES
    requested,observed=requested.casefold(),observed.casefold()
    parts=[p.strip() for p in requested.split(',')]
    def state(value):
        value=re.sub(r'\s+\d{5}(?:-\d{4})?$', '',value.strip())
        return US_STATES.get(value,value if value in US_STATES.values() else None)
    def city(value):return {'new york city':'new york','nyc':'new york'}.get(value.strip(),value.strip())
    if len(parts)<2 or not state(parts[1]):return requested in observed
    for address in observed.split(';'):
        candidate=[p.strip() for p in address.split(',')]
        # A bare matching city is a candidate, not proof of its state. Preserve
        # the source location unchanged for the final posting/eligibility check.
        if len(candidate)<2:
            if city(parts[0])==city(candidate[0]):return True
            continue
        if len(candidate)>2 and candidate[2] not in {'us','usa','united states','united states of america'}:continue
        if city(parts[0])==city(candidate[0]) and state(parts[1])==state(candidate[1]):return True
    return False


class PageText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.links, self.link = [],[],None
        self.skip = 0

    def handle_starttag(self,tag,attrs):
        attrs = dict(attrs)
        if tag in {'script','style','noscript','svg'}:self.skip += 1
        if tag=='a' and attrs.get('href'):self.link = [attrs['href'],[]]
        if tag in {'p','div','li','h1','h2','h3','br'} and not self.skip:self.parts.append('\n')

    def handle_endtag(self,tag):
        if tag in {'script','style','noscript','svg'}:self.skip = max(0,self.skip-1)
        if tag=='a' and self.link:
            self.links.append({'url':self.link[0],'title':' '.join(self.link[1]).strip()})
            self.link = None

    def handle_data(self,data):
        if not self.skip:
            self.parts.append(data)
            if self.link:self.link[1].append(data)

    @property
    def text(self):
        return re.sub(r'[ \t]+',' ',''.join(self.parts)).strip()


def plain(source):
    parser = PageText()
    parser.feed(html.unescape(source or ''))
    return parser.text


def job_location(value):
    """Render JSON-LD Place/PostalAddress values as a readable job location."""
    if isinstance(value, list):
        return "; ".join(dict.fromkeys(filter(None, (job_location(item) for item in value))))
    if isinstance(value, str):
        return plain(value)
    if not isinstance(value, dict):
        return ""
    address = value.get("address", value)
    if isinstance(address, str):
        return plain(address)
    if not isinstance(address, dict):
        return plain(value.get("name", ""))
    parts = []
    for key in ("addressLocality", "addressRegion", "addressCountry"):
        part = address.get(key)
        if isinstance(part, dict):part = part.get("name", "")
        if isinstance(part, str) and part.strip():parts.append(plain(part))
    return ", ".join(dict.fromkeys(parts)) or plain(value.get("name", ""))


def seniority_warning(query,title):
    from .search_policy import seniority
    requested,actual=seniority(query),seniority(title)
    if requested and actual and requested!=actual:
        return {'requested':requested,'actual':actual,'message':f'Requested {requested}; this result is {actual}. Verify the level before recommending it.'}


def board_source(board):
    """A board tenant, not a shared ATS API host, is the recovery identity."""
    platform=str(board.get('platform','')).casefold()
    company=str(board.get('company','')).casefold()
    if platform=='workday':
        return f"ats:workday:{company}:{str(board.get('host','')).casefold()}:{board.get('site','')}"
    return f'ats:{platform}:{company}'


class JobDiscovery:
    def __init__(self, *, transport=None, resolver=socket.getaddrinfo):
        self.transport,self.resolver = transport,resolver

    def read(self,url,*,method='GET',json_body=None):
        # Validate each redirect before following it; refuse private DNS targets.
        with httpx.Client(transport=self.transport,timeout=20,follow_redirects=False,trust_env=False,
                headers={'User-Agent':'eregion/1.0 (public job research)'}) as client:
            for _ in range(5):
                url = public_https_url(url)
                addresses = self.resolver(urlsplit(url).hostname,443,type=socket.SOCK_STREAM)
                if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
                    raise ValueError('Job research can only read public internet pages.')
                with client.stream(method,url,json=json_body) as response:
                    if response.is_redirect:
                        if method!='GET':raise ValueError('Public board API redirected; switch source.')
                        url = urljoin(url,response.headers.get('location',''))
                        continue
                    response.raise_for_status()
                    chunks,total = [],0
                    for chunk in response.iter_bytes():
                        total += len(chunk)
                        if total>2_000_000:raise ValueError('This page is too large. Read a specific job page instead.')
                        chunks.append(chunk)
                    body=b''.join(chunks).decode(response.encoding or 'utf-8',errors='replace')
                    if re.search(r'<title[^>]*>\s*(?:just a moment|access denied|sign in|log in)|/cdn-cgi/challenge-platform/|'
                            r'<form[^>]+id=[\"\'](?:challenge-form|anomaly-form)[\"\']',body,re.I):
                        raise ValueError('Source blocked by a bot challenge or login wall. Switch to a public board; headless browsers may be blocked.')
                    return body,url
        raise ValueError('The job page redirected too many times.')

    def search(self,query,location='',boards=None,limit=10,excluded_hosts=(),excluded_sources=()):
        if not isinstance(query,str) or not 0<len(query)<=400:raise ValueError('Use a short job-search query.')
        limit = min(20,max(1,int(limit)))
        results, failures, sources_checked, skipped_sources = [],[],[],[]
        for board in (boards or [])[:5]:
            source=board_source(board)
            # Ashby/Greenhouse/Lever share API hosts across independent tenants.
            # A blocked company must never exclude other companies on that host.
            host=str(board.get('host','')).casefold()
            if source in excluded_sources or (board.get('platform')=='workday' and host and host in excluded_hosts):
                skipped_sources.append(source)
                continue
            sources_checked.append({**board,'source':source})
            try:
                platform,company = board['platform'],board['company']
                if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',company):raise ValueError('Invalid company board token.')
                if platform=='greenhouse':
                    body,_ = self.read(f'https://boards-api.greenhouse.io/v1/boards/{company}/jobs')
                    jobs = json.loads(body)['jobs']
                    items = [{'url':j['absolute_url'],'title':j['title'],'company':company,
                        'location':j.get('location',{}).get('name','')} for j in jobs]
                elif platform=='lever':
                    body,_ = self.read(f'https://api.lever.co/v0/postings/{company}?mode=json')
                    items = [{'url':j['hostedUrl'],'title':j['text'],'company':company,
                        'location':j.get('categories',{}).get('location','')} for j in json.loads(body)]
                elif platform=='ashby':
                    body,_=self.read(f'https://api.ashbyhq.com/posting-api/job-board/{company}')
                    items=[{'url':j['jobUrl'],'title':j['title'],'company':company,
                        'location':j.get('location','')} for j in json.loads(body)['jobs'] if j.get('isListed',True)]
                elif platform=='workday':
                    host,site=board.get('host',''),board.get('site','')
                    if not re.fullmatch(re.escape(company)+r'\.wd\d+\.myworkdayjobs\.com',host):raise ValueError('Use this tenant\'s public Workday host.')
                    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',site):raise ValueError('Use a public Workday site token.')
                    body,_=self.read(f'https://{host}/wday/cxs/{company}/{site}/jobs',method='POST',
                        json_body={'appliedFacets':{},'limit':20,'offset':0,'searchText':query})
                    items=[{'url':f'https://{host}/{site}'+j['externalPath'],'title':j['title'],'company':company,
                        'location':j.get('locationsText','')} for j in json.loads(body)['jobPostings']
                        if j.get('externalPath','').startswith('/job/')]
                else:raise ValueError('Board platform must be greenhouse, lever, ashby or workday.')
                words = re.findall(r'\w+',query.casefold())
                results += [item for item in items if any(w in item['title'].casefold() for w in words)
                    and (not location or location_matches(location,item['location']))]
            except Exception as exc:failures.append({'board':board,'source':source,'error':type(exc).__name__,
                'blocked':isinstance(exc,httpx.HTTPStatusError) and exc.response.status_code in {401,403,429} or 'blocked' in str(exc).casefold(),
                'next':'Switch to another public source. Headless browsing can trigger bot protection.'})
        if not boards:
            exclusions=[host for host in excluded_hosts if re.fullmatch(r'[a-z0-9.-]+',host)][:8]
            terms=f'{query} {location} jobs careers'+''.join(f' -site:{host}' for host in exclusions)
            role_terms=set(re.findall(r'[a-z]+',query.casefold()))-{
                'senior','junior','sr','jr','remote','us','usa','in','the','and','or','jobs','job','careers','career'}
            for engine in ('https://html.duckduckgo.com/html/','https://www.bing.com/search'):
                if engine in excluded_sources:
                    skipped_sources.append(engine)
                    continue
                sources_checked.append(engine)
                query_url=engine+'?'+urlencode({'q':terms})
                try:
                    body,_ = self.read(query_url)
                    parser = PageText();parser.feed(body)
                    for link in parser.links:
                        url = link['url']
                        if url.startswith('//'):url = 'https:'+url
                        query_args = parse_qs(urlsplit(url).query)
                        url = query_args.get('uddg',[url])[0]
                        if urlsplit(url).hostname=='www.bing.com' and urlsplit(url).path=='/ck/a':
                            value=query_args.get('u',[''])[0]
                            if value.startswith('a1'):
                                try:url=base64.urlsafe_b64decode(value[2:]+'='*(-len(value[2:])%4)).decode()
                                except (ValueError,UnicodeError):continue
                        host=urlsplit(url).hostname or ''
                        if not link['title'] or not url.startswith('https://') or any(
                                host==domain or host.endswith('.'+domain) for domain in ('duckduckgo.com','bing.com','microsoft.com')):continue
                        try:url = public_https_url(url)
                        except ValueError:continue
                        if any(host==excluded or host.endswith('.'+excluded) for excluded in exclusions):continue
                        # Search engines can return only the first query word
                        # (e.g. junior dictionaries or senior living). Such links
                        # are not job candidates and must not stop source recovery.
                        observed=set(re.findall(r'[a-z]+',(link['title']+' '+urlsplit(url).path).casefold()))
                        if role_terms and len(role_terms & observed)<min(2,len(role_terms)):continue
                        results.append({'url':url,'title':link['title'],'company':'','location':'','source':'public_search','source_engine':engine})
                    if results:break
                    failures.append({'source':engine,'error':'no_extracted_results','blocked':False,
                        'next':'No posting links extracted; trying another public source, not verified absence of jobs.'})
                except (ValueError,httpx.HTTPError) as exc:
                    failures.append({'source':engine,'error':type(exc).__name__,'blocked':
                        'blocked' in str(exc).casefold() or isinstance(exc,httpx.HTTPStatusError) and exc.response.status_code in {401,403,429},
                        'next':'Switch public source. A search bot challenge does not mean no jobs exist; headless browsing may be blocked.'})
        unique = {item['url']:item for item in results}
        for item in unique.values():
            warning=seniority_warning(query,item['title'])
            if warning:item['seniority_warning']=warning
        return {'jobs':list(unique.values())[:limit], 'errors':failures,
            'sources_checked':sources_checked,'skipped_sources':skipped_sources,
            'note':'Read each result to verify a current job posting before saving or scoring it.' if unique else
                'These search engines are blocked or repeatedly returned no extracted links in this user turn. '
                'Changing only query wording cannot recover them. Use browser on another public source or specify '
                'public Greenhouse/Lever/Ashby/Workday company boards. Public details are already authorized; '
                'this is not proof of no vacancies.' if skipped_sources and not sources_checked else
                'No verified results. Change query or read public Greenhouse/Lever/Ashby/Workday company boards. Public detail pages are already authorized; continue recovery without asking permission. Do not invent jobs.'}

    def job(self,url):
        url = public_https_url(url)
        parts = urlsplit(url);segments = parts.path.strip('/').split('/')
        if parts.hostname=='jobs.ashbyhq.com' and len(segments)>=2 and re.fullmatch(r'[A-Za-z0-9_-]{1,100}',segments[0]):
            from .alerts import job_key
            body,_=self.read(f'https://api.ashbyhq.com/posting-api/job-board/{quote(segments[0],safe="")}')
            jobs=[j for j in json.loads(body)['jobs'] if j.get('jobUrl') and job_key(j['jobUrl'])==job_key(url)]
            if len(jobs)!=1 or not jobs[0].get('isListed',True):raise ValueError('The requested posting is not uniquely listed on this public Ashby board.')
            job=jobs[0];description=job.get('descriptionPlain') or plain(job.get('descriptionHtml',''))
            if not job.get('title') or len(description)<100:raise ValueError('The public Ashby record has no complete target job body.')
            return {'url':url,'title':job['title'],'company':segments[0],'location':job.get('location',''),
                'description':description,'body_scope':'ashby_posting_record'}
        tenant=re.fullmatch(r'([a-z0-9_-]+)\.wd\d+\.myworkdayjobs\.com',parts.hostname or '')
        site_index=1 if segments and re.fullmatch(r'[a-z]{2}-[A-Z]{2}',segments[0]) else 0
        if tenant and len(segments)>site_index+2 and segments[site_index+1]=='job':
            company,site=tenant[1],segments[site_index]
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',site):raise ValueError('Use the public Workday site token.')
            path='/'+ '/'.join(segments[site_index+1:])
            body,_=self.read(f'https://{parts.hostname}/wday/cxs/{company}/{site}{path}')
            job=json.loads(body)['jobPostingInfo']
            if job.get('externalPath') and job['externalPath'].rstrip('/')!=path.rstrip('/'):
                raise ValueError('Workday returned a different posting identity; do not import it.')
            description=plain(job.get('jobDescription',''))
            if not job.get('title') or len(description)<100:raise ValueError('The public Workday record has no complete target job body.')
            return {'url':url,'title':job['title'],'company':company,'location':job.get('location',''),
                'description':description,'body_scope':'workday_posting_record'}
        if parts.hostname in {'boards.greenhouse.io','job-boards.greenhouse.io'} and len(segments)>=3 and segments[1]=='jobs':
            body,_ = self.read(f'https://boards-api.greenhouse.io/v1/boards/{quote(segments[0],safe="")}/jobs/{quote(segments[2],safe="")}')
            data = json.loads(body)
            return {'url':url,'title':data['title'],'company':data.get('company_name',segments[0]),
                'location':data.get('location',{}).get('name',''),'description':plain(data.get('content',''))[:45000]}
        if parts.hostname in {'jobs.lever.co','jobs.eu.lever.co'} and len(segments)>=2:
            api_host = 'api.eu.lever.co' if parts.hostname=='jobs.eu.lever.co' else 'api.lever.co'
            body,_ = self.read(f'https://{api_host}/v0/postings/{quote(segments[0],safe="")}/{quote(segments[1],safe="")}?mode=json')
            data = json.loads(body)
            text = data.get('descriptionPlain') or plain(data.get('description',''))
            text += '\n'+'\n'.join(plain(item.get('text','')+'\n'+item.get('content','')) for item in data.get('lists',[]))
            text += '\n'+plain(data.get('additional',''))
            return {'url':url,'title':data['text'],'company':segments[0],
                'location':data.get('categories',{}).get('location',''),'description':text[:45000]}
        body,url = self.read(url)
        structured = []
        for script in re.findall(r'<script[^>]+type=[\"\']application/ld\+json[\"\'][^>]*>(.*?)</script>',body,re.S|re.I):
            try:
                parsed = json.loads(script)
                entries = parsed if isinstance(parsed,list) else parsed.get('@graph',[parsed])
                structured.extend(item for item in entries if isinstance(item,dict) and item.get('@type')=='JobPosting')
            except (ValueError,TypeError,AttributeError):pass
        from .alerts import job_key
        matching = [j for j in structured if j.get('url') and job_key(urljoin(url,j['url'])) == job_key(url)]
        job = matching[0] if len(matching)==1 else structured[0] if len(structured)==1 and not structured[0].get('url') else None
        if job and len(plain(job.get('description',''))) >= 100:
            organization = job.get('hiringOrganization') or {}
            location = job_location(job.get('jobLocation'))
            if job.get('jobLocationType') == 'TELECOMMUTE':
                location = 'Remote; ' + (job_location(job.get('applicantLocationRequirements')) or location)
            return {'url':url,'title':job.get('title',''),'company':organization.get('name',''),
                'location':location, 'description':plain(job['description']), 'body_scope':'jsonld_jobposting'}
        from .job_body import posting_body
        extracted = posting_body(body)
        title = re.search(r'<title[^>]*>(.*?)</title>',body,re.S|re.I)
        return {'url':url,'title':plain(title[1]) if title else extracted.pop('heading'), 'company':'', **extracted}

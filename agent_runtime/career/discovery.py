"""Read-only public job discovery. No candidate data or cookies are sent here."""
import html
import ipaddress
import json
import re
import socket
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlsplit

import httpx
from agent_runtime.auto_apply.contracts import public_https_url


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


class JobDiscovery:
    def __init__(self, *, transport=None, resolver=socket.getaddrinfo):
        self.transport,self.resolver = transport,resolver

    def read(self,url):
        # Validate each redirect before following it; refuse private DNS targets.
        with httpx.Client(transport=self.transport,timeout=20,follow_redirects=False,trust_env=False,
                headers={'User-Agent':'eregion/1.0 (public job research)'}) as client:
            for _ in range(5):
                url = public_https_url(url)
                addresses = self.resolver(urlsplit(url).hostname,443,type=socket.SOCK_STREAM)
                if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
                    raise ValueError('Job research can only read public internet pages.')
                with client.stream('GET',url) as response:
                    if response.is_redirect:
                        url = urljoin(url,response.headers.get('location',''))
                        continue
                    response.raise_for_status()
                    chunks,total = [],0
                    for chunk in response.iter_bytes():
                        total += len(chunk)
                        if total>2_000_000:raise ValueError('This page is too large. Read a specific job page instead.')
                        chunks.append(chunk)
                    return b''.join(chunks).decode(response.encoding or 'utf-8',errors='replace'),url
        raise ValueError('The job page redirected too many times.')

    def search(self,query,location='',boards=None,limit=10):
        if not isinstance(query,str) or not 0<len(query)<=400:raise ValueError('Use a short job-search query.')
        limit = min(20,max(1,int(limit)))
        results, failures = [],[]
        for board in (boards or [])[:5]:
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
                else:raise ValueError('Board platform must be greenhouse or lever.')
                words = re.findall(r'\w+',query.casefold())
                results += [item for item in items if any(w in item['title'].casefold() for w in words)
                    and (not location or location.casefold() in item['location'].casefold())]
            except Exception as exc:failures.append({'board':board,'error':type(exc).__name__})
        if not boards:
            query_url = 'https://html.duckduckgo.com/html/?'+urlencode({'q':f'{query} {location} jobs careers'})
            body,_ = self.read(query_url)
            parser = PageText();parser.feed(body)
            for link in parser.links:
                url = link['url']
                if url.startswith('//'):url = 'https:'+url
                query_args = parse_qs(urlsplit(url).query)
                url = query_args.get('uddg',[url])[0]
                if not link['title'] or not url.startswith('https://') or 'duckduckgo.com' in urlsplit(url).netloc:continue
                try:url = public_https_url(url)
                except ValueError:continue
                results.append({'url':url,'title':link['title'],'company':'','location':'','source':'public_search'})
        unique = {item['url']:item for item in results}
        return {'jobs':list(unique.values())[:limit], 'errors':failures,
            'note':'Read each result to verify a current job posting before saving or scoring it.' if unique else
                'No verified results. Try another query, specify Greenhouse/Lever company boards, or ask for a job link. Do not invent jobs.'}

    def job(self,url):
        url = public_https_url(url)
        parts = urlsplit(url);segments = parts.path.strip('/').split('/')
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
        for script in re.findall(r'<script[^>]+type=[\"\']application/ld\+json[\"\'][^>]*>(.*?)</script>',body,re.S|re.I):
            try:
                parsed = json.loads(script)
                entries = parsed if isinstance(parsed,list) else parsed.get('@graph',[parsed])
                job = next((item for item in entries if item.get('@type')=='JobPosting'),None)
                if job:
                    organization = job.get('hiringOrganization') or {}
                    return {'url':url,'title':job.get('title',''),'company':organization.get('name',''),
                        'location':job_location(job.get('jobLocation')), 'description':plain(job.get('description',''))[:45000]}
            except (ValueError,TypeError,AttributeError):pass
        parser = PageText();parser.feed(body)
        title = re.search(r'<title[^>]*>(.*?)</title>',body,re.S|re.I)
        if len(parser.text)<100:raise ValueError('The page did not expose a job description. Ask for the job text or another public link.')
        return {'url':url,'title':plain(title[1]) if title else '', 'company':'','location':'',
            'description':parser.text[:45000],'links':parser.links[:30]}

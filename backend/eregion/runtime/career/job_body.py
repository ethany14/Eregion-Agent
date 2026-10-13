"""Select a posting body before flattening HTML; never score an entire web page."""
from html.parser import HTMLParser
import re

VOID = {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}
BODY_CLASSES = {'job-description','job__description','posting-description','jobs-description__content','simple-job-description-html'}
CHROME_CLASSES = {'previous-next','related-jobs','recommended-jobs','similar-jobs','job-recommendations'}


class Node:
    def __init__(self, tag, attrs=(), parent=None):
        self.tag, self.attrs, self.parent, self.children = tag, dict(attrs), parent, []

    @property
    def classes(self):
        return set(self.attrs.get('class','').split())

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Node): yield from child.walk()

    def text(self):
        if self.tag in {'script','style','noscript','svg','nav','aside','footer','header'} or self.classes & CHROME_CLASSES:
            return ''
        content = ''.join(c.text() if isinstance(c, Node) else c for c in self.children)
        if self.tag in {'p','div','li','h1','h2','h3','br','article','section'}: content = '\n' + content + '\n'
        return content


class Tree(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.root = self.current = Node('document')
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.current)
        self.current.children.append(node)
        if tag not in VOID: self.current = node

    def handle_startendtag(self, tag, attrs):
        self.current.children.append(Node(tag, attrs, self.current))

    def handle_endtag(self, tag):
        node = self.current
        while node.parent:
            if node.tag == tag:
                self.current = node.parent
                return
            node = node.parent

    def handle_data(self, text):
        self.current.children.append(text)


def clean(node):
    return re.sub(r'\n[ \t]*\n+', '\n\n', re.sub(r'[ \t]+',' ',node.text())).strip()


def posting_body(source):
    root = Tree(source).root
    nodes = list(root.walk())
    bodies = [n for n in nodes if n.classes & BODY_CLASSES or
        n.attrs.get('data-automation-id') == 'jobPostingDescription' or n.attrs.get('itemprop') == 'description' or
        n.attrs.get('id')=='jobDescriptionText' or n.attrs.get('data-testid')=='jobsearch-JobComponent-description']
    # Nested equivalent wrappers describe one body, not two jobs.
    bodies = [n for n in bodies if not any(p is n for other in bodies if other is not n
        for p in ancestors(other))]
    if not bodies:
        bodies = [n for n in nodes if n.tag == 'article' and
            len([h for h in n.walk() if h.tag == 'h1']) == 1]
    if len(bodies) != 1 or len(clean(bodies[0])) < 100:
        raise ValueError('No single bounded job description found. Open the posting in the browser and select its actual description region; do not score whole-page text.')
    body = bodies[0]
    scope = next((n for n in ancestors(body) if n.tag == 'article'), body)
    locations = [n for n in scope.walk() if 'listing-location' in n.classes]
    heading = next((n for n in scope.walk() if n.tag == 'h1'), None)
    return {'description': clean(body), 'location': clean(locations[0]) if len(locations) == 1 else '',
        'heading': clean(heading) if heading else '', 'body_scope': 'bounded_html',
        'body_selector': '.' + next(iter(sorted(body.classes & BODY_CLASSES))) if body.classes & BODY_CLASSES else body.tag}


def ancestors(node):
    while node.parent:
        node = node.parent
        yield node

"""Necessary content overlap for partial credit, never proof of full support."""
import re

ALIASES = (
    ('kubernetes','k8s'), ('postgresql','postgres'), ('javascript','js'),
    ('sql','structured query language'), ('machine learning','ml'),
    ('natural language processing','nlp'), ('bachelor','bachelors','b.sc','b.s','bsc'),
    ('master','masters','m.sc','m.s','msc'),
)
STOP = frozenset('a an the and or of in on at to for with by from as is are was were be been '
    'have has had must should can will would may required require requirements preferred '
    'experience experienced years year months month one two three four five six seven eight nine ten '
    'skill skills knowledge ability able proficiency proficient strong excellent good advanced basic '
    'work worked working works team teams system systems software tool tools project projects '
    'use used using uses build built building develop developed developing development '
    'production professional hands scope support supporting tasks responsibilities data'.split())


def content_terms(text):
    # C and R are real skill names, not arbitrary single-letter content words.
    # Preserve explicitly written standalone uppercase tokens; operators are
    # part of identity (C, C++ and C# must not become each other's support).
    single_skills={m.group().casefold() for m in re.finditer(r'(?<![\w+#])(?:C|R)(?![\w+#])',text)}
    text=text.casefold()
    for aliases in ALIASES:
        for alias in sorted(aliases,key=len,reverse=True):
            text=re.sub(r'(?<![\w+#])'+re.escape(alias)+r'(?![\w+#])',aliases[0],text)
    terms=set()
    for word in re.findall(r'[\w]+(?:\+\+|#)?',text):
        if word in STOP or word.isdigit():continue
        if len(word)>5 and word.endswith('ing'): word=word[:-3]
        elif len(word)>3 and word.endswith('s') and not word.endswith(('ss','ics','aws')): word=word[:-1]
        if word not in STOP and (len(word)>1 or word in single_skills):terms.add(word)
    return terms


def partial_overlap(requirement, quote):
    return sorted(content_terms(requirement) & content_terms(quote))


PARTIAL_POLICY = ('Partial credit requires a content key term from the stated requirement in the exact evidence quote, '
    'or one of these listed aliases: ' + '; '.join(' = '.join(group) for group in ALIASES) + '. '
    'Generic words such as experience, work, tools, systems, data, development and years do not establish relevance. '
    'Identify the supported key term and actual missing component/scope; overlap alone never establishes full support.')

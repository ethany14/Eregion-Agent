"""Advisory editing notes, never factual verification or an aesthetic verdict."""
import re


def cover_invitation_occurrences(content):
    """Finite editorial pattern shared by revision notes and offline screens.

    These locations identify repeated phrasing, not factual errors or a human
    style verdict. A single future invitation is allowed.
    """
    return [
        {'block_id': f'paragraph-{index+1}', 'text': match[0]}
        for index, paragraph in enumerate(content.get('paragraphs') or [])
        for match in re.finditer(r'\bwould\s+welcome\s+the\s+(?:opportunity|chance)\b',
                                paragraph.get('text', ''), re.I)
    ]


def cover_revision_notes(content):
    paragraphs=content.get('paragraphs') or []
    notes=[]
    if paragraphs:
        opening=paragraphs[0].get('text','')
        first=re.split(r'(?<=[.!?])\s+',opening.strip())[0]
        if first and not re.match(r'I\b',first):
            notes.append({'kind':'opening_perspective','block_id':'paragraph-1','text':first,
                'instruction':'Open with one plain first-person application sentence naming only the verified role and company. Do not describe what the role, letter, or contribution focuses/centers on. Employer needs can appear separately; add no enthusiasm or candidate fact.'})
    invitations=cover_invitation_occurrences(content)
    if len(invitations)>1:
        notes.append({'kind':'repeated_invitation','occurrences':invitations,
            'instruction':'Consolidate the repeated invitation into one future contribution sentence. The opening states the application; the evidence paragraph states the supported past fact once; the closing adds only one distinct future task. Do not rotate synonyms to repeat the same intent.'})
    return notes

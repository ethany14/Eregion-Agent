"""Readable result labels and final-prose checks; source artifacts stay exact."""
import re

LABELS={'needs_review':'Needs review','needs_input':'Needs your input',
    'awaiting_review':'Ready for review','needs_confirmation':'Needs confirmation',
    'confirmed_condition':'Confirmed condition','submission_unknown':'Submission unconfirmed',
    'completed':'Completed','matched':'Matched','partial':'Partly supported','missing':'Missing evidence',
    'unknown':'Unresolved','saved':'Saved','cancelled':'Cancelled','running':'In progress'}
INTERNAL=re.compile(r'\b(?:[a-z][a-z0-9]*(?:_[a-z0-9]+){2,}|needs_review|needs_input|awaiting_review|needs_confirmation|confirmed_condition|submission_unknown)\b')


def display_label(value):
    text=str(value or '')
    if text in LABELS:return LABELS[text]
    if re.fullmatch(r'[a-z][a-z0-9]*(?:_[a-z0-9]+)+',text):return text.replace('_',' ').capitalize()
    return text


def validate_final_language(state,text):
    user=next((m.get('text','') for m in reversed(state.get('messages',[])) if m.get('role')=='user'),state.get('goal',''))
    # Explicit diagnostics requests may need the exact stored identifiers.
    request=re.search(r'\b(?:show|include|give|return|inspect|debug|list|explain)\b.{0,70}\b(?:ids?|identifiers?|internal codes?|enum(?:s| values)?|canonical names?)\b|(?:显示|列出|查看|给出|解释).{0,30}(?:ID|内部代码|枚举)',user,re.I)
    negated=re.search(r'\b(?:do not|don.t|never|without|hide|omit)\b.{0,35}\b(?:ids?|internal|enum)|(?:不要|不显示|隐藏).{0,20}(?:ID|内部|枚举)',user,re.I)
    if request and not negated:return
    prose=re.sub(r'```[\s\S]*?```|~~~[\s\S]*?~~~',' ',text)
    prose=re.sub(r'https?://[^\s<>]+|[A-Za-z]:[\\/][^\s<>]+|(?<!\w)/(?:[^\s/]+/)*[^\s<>]+',' ',prose)
    prose=re.sub(r'\b[\w.-]+\.(?:py|js|mjs|ts|md|json|xml|log|pdf|txt|csv|sqlite3?|db)\b',' ',prose,flags=re.I)
    # Inline expressions are code; a backticked internal enum by itself is still
    # a label in prose and should be explained in ordinary language.
    prose=re.sub(r'`[^`\n]*[()=\[\]{}:+*/][^`\n]*`',' ',prose)
    if re.search(r'\b(?:code|function|variable|program|script)\b|代码|函数|变量|脚本',user,re.I):
        prose=re.sub(r'`[^`\n]+`',' ',prose)
    leaked=[m.group() for m in INTERNAL.finditer(prose) if m.group() not in user]
    if leaked:raise ValueError('Explain internal result codes in ordinary language using display_name/status_label; keep exact identifiers only when requested. Unexplained codes: '+', '.join(dict.fromkeys(leaked)))

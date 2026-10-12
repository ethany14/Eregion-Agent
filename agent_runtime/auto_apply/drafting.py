"""Resume context and editable narrative drafts, separate from confirmed answers."""
from functools import lru_cache
import re

from .browser import BrowserBlocked
from .decisions import signature
from .matching import is_consent


@lru_cache(maxsize=4)
def resume_context(content):
    # Attempts already retain their original PDF. Reuse it for older attempts too,
    # without extracting it again for every model observation.
    from agent_runtime.resumes.pdf_text import extract_pdf_text
    try:
        text, pages = extract_pdf_text(content)
        return {"text": text, "page_count": pages, "warning": None}
    except ValueError:
        return {"text": "", "page_count": None,
                "warning": "Resume text could not be read. Ask for relevant project details if needed."}


def visible_drafts(state, fields):
    return {f["key"]: draft for f in fields
            if (draft := state.get("answer_drafts", {}).get(f["key"]))
            and draft["field"] == signature(f)
            and f["key"] not in state["answers"]
            and (not f["value"] or f.get("invalid"))}


def prepare_draft(field, state, *, text, evidence, missing_details):
    label = " ".join(str(field.get(k) or "") for k in ("label", "group", "help"))
    if (field["kind"] not in {"text", "textarea"} or field.get("options")
            or field.get("choice_control") or is_consent(field)
            or re.search(r"\b(sponsor\w*|visa|work authori\w*|citizenship|nationality|salary|compensation|"
                         r"consent|agree|ethnic\w*|gender|disabil\w*|veteran|criminal|password)\b|"
                         r"签证|担保|授权|同意|薪资|国籍", label, re.I)
            or not re.search(r"\b(describe|explain|share|example|why|what|how|motivat\w*|summari\w*)\b|"
                             r"tell us|tell me|cover letter|additional information|介绍|描述|经历|项目|简述|说明", label, re.I)):
        raise BrowserBlocked("Draft only an open-ended narrative question; use confirmed answers for other fields.")
    if field["key"] in state["answers"] or (field["value"] and not field.get("invalid")):
        raise BrowserBlocked("Keep the user's existing answer instead of replacing it with a draft.")
    if not isinstance(text, str) or not text.strip() or len(text) > 10000:
        raise BrowserBlocked("Provide a nonempty draft of at most 10,000 characters.")
    maximum = (field.get("constraints") or {}).get("max_length")
    if maximum is not None and str(maximum).isdigit() and len(text) > int(maximum):
        raise BrowserBlocked("Shorten the draft to fit this question's character limit.")
    if (not isinstance(missing_details, list) or len(missing_details) > 5
            or any(not isinstance(v, str) or not v.strip() or len(v) > 500 for v in missing_details)):
        raise BrowserBlocked("List only the specific missing details needed to finish the draft.")
    if not isinstance(evidence, list) or not 1 <= len(evidence) <= 8:
        raise BrowserBlocked("Cite resume or user-message evidence for the draft.")
    sources = {"resume": state.get("resume_context", {}).get("text", "")}
    sources.update({f"message:{m['id']}": m["text"] for m in state.get("messages", [])
                    if m["role"] == "user" and not m.get("control")})
    normalize = lambda value: re.sub(r"\s+", " ", value).strip().casefold()
    citations = []
    for item in evidence:
        if not isinstance(item, dict) or set(item) != {"source_ref", "quote"}:
            raise BrowserBlocked("Each citation needs a source_ref and a literal quote.")
        ref, quote = item["source_ref"], item["quote"]
        if (not isinstance(ref, str) or ref not in sources or not isinstance(quote, str)
                or not quote.strip() or len(quote) > 3000
                or normalize(quote) not in normalize(sources[ref])):
            raise BrowserBlocked("Cite text actually present in the resume or a user message, not the job page.")
        citations.append({"source_ref": ref, "quote": quote})
    return {"field": signature(field), "text": text.strip(), "evidence": citations,
            "missing_details": missing_details}

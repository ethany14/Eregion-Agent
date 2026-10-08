"""Bind compact replies to the questions actually shown, before invoking a model."""
import re

from .matching import boolean_answer, field_category, resolve_option, equivalent, clean


NUMBER = r"(?:^|[\s;；,，])([0-9]{1,2})\s*[.)、:：]\s*(?![0-9])"
TRIM = " \t\r\n;；,，、"


def asked_keys(message, fields):
    if message.get("role") != "assistant":
        return []
    if "question_keys" in message:
        return message["question_keys"]
    # Compatibility with saved conversations from before structured prompts.
    prefix, suffix = "I need your answer for: ", ". Reply here or use the fields below."
    text = message.get("text", "")
    if not (text.startswith(prefix) and text.endswith(suffix)):
        return []
    keys = []
    for label in text[len(prefix):-len(suffix)].split("; "):
        matches = [f["key"] for f in fields if f["label"] == label]
        if len(matches) != 1:
            return []
        keys.append(matches[0])
    return keys


def numbered_parts(text, count):
    """Map explicit question numbers; allow an unnumbered answer before `2.`."""
    markers = list(re.finditer(NUMBER, text))
    if not markers:
        return None
    prefix = text[:markers[0].start()].strip(" \t\r\n;；,，")
    parts = {}
    if prefix:
        if int(markers[0][1]) != 2:
            return {}
        parts[0] = prefix
    for index, marker in enumerate(markers):
        number = int(marker[1]) - 1
        if number < 0 or number >= count or number in parts:
            return {}
        end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        parts[number] = text[marker.end():end].strip(" \t\r\n;；,，")
    return parts


def ordered_answers(text, messages, fields):
    """Accept a simple leading sequence only; never shift answers over a gap."""
    keys = []
    for message in reversed(messages):
        if message["role"] == "user":
            return {}
        keys = asked_keys(message, fields)
        if keys:
            break
    current = {f["key"]: f for f in fields}
    if not keys or any(key not in current for key in keys):
        return {}
    # Resolve a geographic phrase before treating its commas as answer separators.
    # A city clarification can include a repeated referral answer after the list
    # has shrunk; field meaning must take priority over a stale question number.
    geographic = geographic_answers(text, keys, current)
    if geographic is not None:
        return geographic
    return answers_for_keys(text, keys, current)


def geographic_answers(text, keys, current):
    f = current[keys[0]]
    if field_category(f["label"]) != "city" or not f.get("options"):
        return None
    body = re.sub(r"^\s*1\s*[.)、:：]\s*", "", text).strip(TRIM)
    # Try longest literal spans first so `Ithaca, NY` cannot become two answers.
    ends = {len(body), *(m.start() for m in re.finditer(r"[,，;；、\n]", body)),
        *(m.start() for m in re.finditer(NUMBER, body))}
    for end in sorted(ends, reverse=True):
        value = body[:end].strip(TRIM)
        if len(value) > 160 or not resolve_option(f["label"], value, f["options"]):
            continue
        rest = body[end:].strip(TRIM)
        if not rest:
            return {f["key"]: value}
        # Short, explicit sourcing answers may refer to a previously asked field.
        # Never extend this out-of-order shortcut to authorization or consent.
        referral = re.sub(r"^2\s*[.)、:：]\s*", "", rest).strip(TRIM)
        channels = {"linkedin", "indeed", "glassdoor", "company website", "careers page", "referral"}
        sources = [item for item in current.values() if item["kind"] in {"text", "select", "combobox"}
            and re.search(r"(?i)how did you hear|how did you find|source of application", item["label"])]
        if clean(referral) in channels and len(sources) == 1 and (len(keys) == 1 or keys[1] == sources[0]["key"]):
            return {f["key"]: value, sources[0]["key"]: referral}
        if len(keys) > 1 and not re.search(NUMBER, rest):
            remaining = answers_for_keys(rest, keys[1:], current)
            if remaining:
                return {f["key"]: value, **remaining}
    return None


def answers_for_keys(text, keys, current):
    numbered = numbered_parts(text, len(keys))
    if numbered is not None:
        pairs = [(keys[index], part) for index, part in numbered.items()]
    else:
        # Semicolons/newlines preserve commas inside a city or school name.
        if len(keys) == 1 and field_category(current[keys[0]]["label"]) in {"city", "school"}:
            # One name can contain commas; do not silently discard its region.
            parts = [text.strip(TRIM)]
        else:
            delimiter = r"[;；\n]" if re.search(r"[;；\n]", text) else r"[,，]"
            parts = [part.strip() for part in re.split(delimiter, text.strip())]
        if len(parts) > len(keys) or (len(keys) > 1 and len(parts) < 2):
            return {}
        pairs = list(zip(keys, parts))
    answers = {}
    for key, part in pairs:
        f = current[key]
        if not part or len(part) > 160 or len(part.split()) > 8 or re.search(r"[:：=?]", part):
            return {}
        if re.match(r"(?i)^(i\b|please\b|for\b|use\b|change\b|actually\b|set\b)", part):
            return {}
        boolean = boolean_answer(part)
        binary = f["kind"] == "checkbox" or bool(re.search(r"(?i)fluent|sponsor|authorized|authorised|eligible", f["label"]))
        if binary and boolean is None:
            return {}
        if field_category(f["label"]) in {"city", "school", "degree", "country"} and boolean is not None:
            return {}
        if f["kind"] in {"select", "radio"} and f.get("options") and not resolve_option(f["label"], part, f["options"]):
            return {}
        if f["kind"] in {"file", "password"}:
            return {}
        answers[key] = boolean if f["kind"] == "checkbox" else part
    return answers


def input_prompt(unknown, failed, answers=None):
    clarifications, blocked = [], []
    for f in failed:
        options = [o for o in f.get("options", []) if not o.get("disabled") and
            equivalent(f["label"], (answers or {}).get(f["key"], ""), o)]
        labels = list(dict.fromkeys(o["label"] for o in options))
        if len(labels) > 1:
            clarifications.append((f, f["label"] + " — your answer matches multiple options. Which one? " + "; ".join(labels[:5])))
        else:
            blocked.append(f)
    text = ""
    if blocked:
        text = "I have your answers, but could not finish filling these controls: " + "; ".join(f["label"] for f in blocked) + ". Your answers are saved; retry or adjust the fields below.\n\n"
    shown = [*clarifications, *((f, f["label"]) for f in unknown)][:5]
    if shown:
        text += "I still need these answers:\n" + "\n".join(f"{i}. {label}" for i, (f, label) in enumerate(shown, 1))
        text += "\nReply in this order, separated by semicolons, or choose a question below."
    return text.strip(), [f["key"] for f, label in shown]

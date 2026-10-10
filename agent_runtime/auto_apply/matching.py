"""Field-aware option equivalence and conservative cross-form question identities."""
import re
import unicodedata
from difflib import SequenceMatcher


def clean(value):
    text = unicodedata.normalize("NFKD", str(value)).casefold()
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^\w]+", " ", text).strip()


COUNTRIES = {
    "united states": ("us", "usa", "u s", "u s a", "united states of america", "美国"),
    "united kingdom": ("uk", "gb", "gbr", "u k", "great britain", "英国"),
    "canada": ("ca", "can", "加拿大"), "china": ("cn", "chn", "prc", "中国"),
    "australia": ("au", "aus", "澳大利亚"), "germany": ("de", "deu", "deutschland", "德国"),
    "france": ("fr", "fra", "法国"), "india": ("in", "ind", "印度"),
    "japan": ("jp", "jpn", "日本"), "singapore": ("sg", "sgp", "新加坡"),
    "south korea": ("kr", "kor", "republic of korea", "韩国"),
    "ireland": ("ie", "irl"), "netherlands": ("nl", "nld"), "new zealand": ("nz", "nzl"),
    "switzerland": ("ch", "che"), "spain": ("es", "esp"), "italy": ("it", "ita"),
    "brazil": ("br", "bra"), "mexico": ("mx", "mex"), "taiwan": ("tw", "twn"),
}
SCHOOLS = {"mit": "massachusetts institute of technology", "cmu": "carnegie mellon university",
    "nyu": "new york university", "ucla": "university of california los angeles",
    "uc berkeley": "university of california berkeley", "ucb": "university of california berkeley",
    "uc san diego": "university of california san diego", "ucsd": "university of california san diego",
    "uiuc": "university of illinois urbana champaign", "upenn": "university of pennsylvania"}

US_STATES = dict(pair.split(":") for pair in (
    "al:alabama|ak:alaska|az:arizona|ar:arkansas|ca:california|co:colorado|ct:connecticut|"
    "de:delaware|dc:district of columbia|fl:florida|ga:georgia|hi:hawaii|id:idaho|il:illinois|"
    "in:indiana|ia:iowa|ks:kansas|ky:kentucky|la:louisiana|me:maine|md:maryland|ma:massachusetts|"
    "mi:michigan|mn:minnesota|ms:mississippi|mo:missouri|mt:montana|ne:nebraska|nv:nevada|"
    "nh:new hampshire|nj:new jersey|nm:new mexico|ny:new york|nc:north carolina|nd:north dakota|"
    "oh:ohio|ok:oklahoma|or:oregon|pa:pennsylvania|ri:rhode island|sc:south carolina|"
    "sd:south dakota|tn:tennessee|tx:texas|ut:utah|vt:vermont|va:virginia|wa:washington|"
    "wv:west virginia|wi:wisconsin|wy:wyoming"
).split("|"))


def city_equivalent(answer, value):
    """Match complete geographic components, expanding US states only in US options."""
    source = clean(answer).replace(" ", "")
    parts = [clean(part) for part in re.split(r"[,，]", str(value))]
    if not source or not all(parts):
        return False
    variants = [parts]
    if len(parts) >= 3 and country(parts[2]) == "united states":
        state = US_STATES.get(parts[1], parts[1])
        code = next((code for code, name in US_STATES.items() if name == state), None)
        if code:
            variants.extend([[parts[0], region, *parts[2:]] for region in (state, code)])
    if len(parts) >= 3 and country(parts[2]) in COUNTRIES:
        # The selected city may render USA while the source says United States.
        # Expand only aliases of this option's actual country; never drop a
        # conflicting country supplied by the user.
        name = country(parts[2])
        variants = [[*variant[:2], clean(alias), *variant[3:]]
            for variant in variants for alias in (name, *COUNTRIES[name])]
    return any(source == "".join(variant[:end]).replace(" ", "")
        for variant in variants for end in range(1, len(variant) + 1))


def country(value):
    text = clean(re.sub(r"\s*\+\d[\d ()-]*$", "", str(value)))
    return next((name for name, aliases in COUNTRIES.items() if text in (name, *aliases)), text)


def school(value):
    text = clean(value)
    text = SCHOOLS.get(text, text)
    text = re.sub(r"\b(univ|uni|u)\b", "university", text)
    return " ".join(w for w in text.split() if w not in {"the", "of", "at", "and"})


def field_category(label):
    text = clean(label)
    if re.search(r"\b(country|citizenship|nationality)\b|国家|国籍", text): return "country"
    # The question may mention university while asking which degree is pursued.
    if re.search(r"\b(?:what|which)\s+degree\b", text): return "degree"
    if re.search(r"\b(school|university|college|institution)\b|学校|大学", text): return "school"
    if re.search(r"\bdegree\b|学位", text): return "degree"
    if re.search(r"\bcity\b|城市", text): return "city"
    return "other"


def equivalent(label, answer, option):
    values = [option.get("label", ""), option.get("value", "")]
    if any(clean(answer) == clean(v) for v in values): return True
    polarity = boolean_answer(answer)
    if polarity is not None:
        return any(boolean_answer(v) is polarity for v in values)
    category = field_category(label)
    if category == "country": return any(country(answer) == country(v) for v in values)
    if category == "school":
        source = school(answer)
        for value in values:
            target = school(value)
            acronym = "".join(w[0] for w in target.split() if w)
            if source == target or (len(source) >= 2 and source.replace(" ", "") == acronym): return True
            if re.sub(r"\buniversity\b", "", source).strip() == re.sub(r"\buniversity\b", "", target).strip(): return True
            source_words = sorted(w for w in source.split() if w != "university")
            target_words = sorted(w for w in target.split() if w != "university")
            if source_words and len(source_words) == len(target_words) and all(
                a == b or (len(a) >= 4 and b.startswith(a)) for a, b in zip(source_words, target_words)):
                return True
            if len(source) > 8 and len(target) > 8 and SequenceMatcher(None, source, target).ratio() >= .96: return True
    if category == "degree":
        source = clean(answer)
        for value in values:
            target = clean(value)
            # Specific degrees can map to their general level, not another specialism.
            if target in {"bachelor s degree", "bachelors degree", "bachelor degree", "bachelors", "bachelor", "bachelor s"} and (
                source in {"bs", "b s", "bsc", "b sc", "ba", "b a", "beng", "本科", "学士"} or source.startswith(("bachelor ", "bachelors "))): return True
            if target in {"master s degree", "masters degree", "master degree", "masters", "master", "master s"} and (
                source in {"ms", "m s", "msc", "m sc", "ma", "m a", "meng", "m eng", "硕士"} or source.startswith(("master of science", "master of arts", "master of engineering", "master s", "masters "))): return True
            if "doctor of philosophy" in target and source in {"phd", "ph d", "doctor of philosophy", "博士"}: return True
    if category == "city":
        # Ignore spacing/punctuation, but require whole geographic components.
        # `ithaca newyork` matches city + state, never a different state or a
        # partial name such as `Ithaca Falls`. resolve_option checks uniqueness.
        return any(city_equivalent(answer, value) for value in values)
    return False


def boolean_answer(value):
    if isinstance(value, bool): return value
    text = clean(value)
    if text in {"yes", "true", "agree", "i agree", "是", "需要", "同意", "可以"}: return True
    if text in {"no", "false", "disagree", "i disagree", "否", "不需要", "不同意", "不可以"}: return False
    return None


def resolve_option(label, answer, options):
    # Dynamic suggestion menus can render the same public choice twice. Only
    # identical label/value pairs collapse; equal labels with different values
    # remain ambiguous (e.g. different schools or locations).
    unique = {}
    for option in options:
        if not option.get("disabled"):
            identity = tuple(str(option.get(key, "")).strip().casefold() for key in ("label", "value"))
            unique.setdefault(identity, option)
    options = list(unique.values())
    exact = [o for o in options if not o.get("disabled") and str(answer).strip().casefold() in
             {str(o.get("value", "")).strip().casefold(), str(o.get("label", "")).strip().casefold()}]
    if len(exact) == 1: return exact[0]
    if field_category(label) == "school" and len(clean(answer)) <= 5 and " " not in clean(answer):
        acronyms = [o for o in options if not o.get("disabled") and "".join(w[0] for w in school(o.get("label", "")).split()) == clean(answer)]
        if len(acronyms) > 1: return None
    matches = [o for o in options if not o.get("disabled") and equivalent(label, answer, o)]
    return matches[0] if len(matches) == 1 else None


def search_text(label, value):
    if field_category(label) == "country": return country(value)
    if field_category(label) == "school": return SCHOOLS.get(clean(value), str(value))
    return str(value)


def salary_units(value):
    """Keep explicit units; a bare dollar sign is not evidence of US dollars."""
    text = str(value).casefold()
    currencies = set(re.findall(r"\b(?:usd|eur|gbp|cad|aud|nzd|sgd|hkd|cny|rmb|jpy|inr|chf|sek|nok|dkk|pln|brl|mxn|zar|aed)\b", text))
    aliases = {"us dollars": "usd", "u.s. dollars": "usd", "united states dollars": "usd",
               "canadian dollars": "cad", "australian dollars": "aud", "euros": "eur", "euro": "eur",
               "pounds sterling": "gbp", "us$": "usd", "ca$": "cad", "a$": "aud", "€": "eur", "£": "gbp"}
    currencies.update(code for alias, code in aliases.items() if re.search(r"(?<!\w)" + re.escape(alias), text))
    if "rmb" in currencies:
        currencies.remove("rmb")
        currencies.add("cny")
    if "$" in text and not currencies:
        currencies.add("dollar_unspecified")
    periods = set()
    for period, pattern in {
        "year": r"\b(?:annual(?:ly)?|year(?:ly)?|annum|yr)\b|\bp\.a\.",
        "month": r"\b(?:month(?:ly)?|mo)\b", "week": r"\b(?:week(?:ly)?|wk)\b",
        "hour": r"\b(?:hour(?:ly)?|hr)\b", "day": r"\b(?:day|daily)\b",
    }.items():
        if re.search(pattern, text):
            periods.add(period)
    # Multiple/conflicting units must never turn into a single reusable amount.
    return {"currency": "+".join(sorted(currencies)), "period": "+".join(sorted(periods))}


def salary_compatible(question, value, target):
    from .standard import topic
    if topic(clean(question)) != "salary" and topic(clean(target)) != "salary":
        return True
    if topic(clean(question)) != "salary" or topic(clean(target)) != "salary":
        return False
    source, answer, destination = salary_units(question), salary_units(value), salary_units(target)
    for dimension in ("currency", "period"):
        stated, supplied, needed = source[dimension], answer[dimension], destination[dimension]
        if any("+" in unit for unit in (stated, supplied, needed)):
            return False
        if dimension == "currency" and supplied == "dollar_unspecified" and stated in {"usd", "cad", "aud", "nzd", "sgd", "hkd"}:
            supplied = stated
        if stated and supplied and stated != supplied:
            return False
        actual = supplied or stated
        if needed and actual != needed:
            return False
        # A generic destination can retain units explicitly written in the
        # answer, but cannot recover units omitted from a bare numeric answer.
        if actual and not needed and not supplied:
            return False
    return True


def question_identity(label):
    """Reuse only equivalent intent; preserve country, time scope and negation."""
    from .standard import topic
    text = clean(label)
    if re.search(r"\b(spouse|partner|dependent|family)\b", text):
        return "exact:" + text
    # Common questions share one identity across wordings (e.g. desired salary).
    standard = topic(text)
    if standard:
        if standard == "salary":
            units = salary_units(label)
            return "standard:salary" + "".join(f"|{key}={value}" for key, value in units.items() if value)
        return "standard:" + standard
    if re.search(r"\d|\b(hours|permanent|temporary|temporarily|internship|student)\b", text):
        return "exact:" + text
    for name, aliases in COUNTRIES.items():
        for alias in sorted((name, *aliases), key=len, reverse=True):
            if len(alias) <= 3 and alias not in {"us", "usa", "uk"}: continue
            if re.search(r"\b" + re.escape(alias) + r"\b", text):
                text = re.sub(r"\b" + re.escape(alias) + r"\b", name, text)
                break
    region = next((name for name in COUNTRIES if name in text), "unspecified")
    if re.search(r"\b(not|never|without|previously)\b", text): return "exact:" + text
    if re.search(r"\b(require|need)\b.*\bsponsor(ship)?\b", text):
        period = "future" if re.search(r"\b(future|later|ever)\b", text) else "current"
        return f"sponsorship:{region}:{period}"
    if re.search(r"\b(authorized|authorised|eligible)\b.*\bwork\b", text):
        return f"work_authorization:{region}"
    if re.search(r"\b(consent|agree|authorize)\b", text) and re.search(r"\b(process|processing)\b", text) and re.search(r"\b(data|information)\b", text):
        if re.search(r"\b(recruitment|recruiting|application|hiring)\b", text) and not any(w in text for w in ("future", "marketing", "third party", "background", "credit", "arbitration", "health", "medical")):
            return "consent:application_data_processing"
    simple = {"school": "school", "university": "school", "school name": "school", "college university": "school",
              "country": "country", "country of residence": "residence_country", "current country": "residence_country"}
    return simple.get(text, "exact:" + text)


def consent_answer(field, policy):
    if policy != "required_only": return None
    text = clean(field["label"])
    if any(w in text for w in ("marketing", "newsletter", "talent pool", "talent community", "future opportunities")):
        return None  # Leave optional subscriptions untouched.
    if field.get("required") and re.search(r"\b(consent|agree|authorize|acknowledge)\b", text) and (
        "privacy" in text or (re.search(r"\b(process|processing)\b", text) and re.search(r"\b(data|information)\b", text))):
        # Does not cover employment eligibility, contracts, background checks or attestations.
        if not any(w in text for w in ("background", "credit", "arbitration", "accurate", "certify", "third party")):
            return True if field["kind"] == "checkbox" else "Yes"
    return None


def is_consent(field):
    return field["kind"] in {"checkbox", "radio", "select", "combobox"} and bool(re.search(
        r"\b(consent|agree|authorize|acknowledge|subscribe|subscription|opt in)\b|同意|授权|订阅", clean(field["label"])))

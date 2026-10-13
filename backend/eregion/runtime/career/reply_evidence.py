"""Job-entry URL/score association shared by production and outcome acceptance."""
import re


def reply_job_evidence(final):
    """Associate scores with entries, never with a suffix of the entire reply.

    List items and table rows are hard boundaries. In unstructured multi-line
    entries, a score on a URL line belongs only to that URL; remaining score
    lines attach consistently before or after URLs according to the first pair.
    URL digits, salaries and arbitrary numbers are not scores. Point scores and
    bounded intervals share these entry boundaries but remain separate evidence.
    """
    url_pattern = re.compile(r'https?://[^\s<>|)]+')
    number = r'(\d+(?:\.\d+)?)'
    score_pattern = re.compile(
        r'(?<![\w.])' + number + r'\s*(?:/\s*100|%)' +
        r'|\b(?:match(?:\s+score)?|fit(?:\s+score)?|score(?:\s+(?:vs\.?|against|for)\s+(?:(?:saved|your|my)\s+)?(?:resume|profile))?)\s*[:=]?\s*' + number +
        r'|(?:评分|匹配度|匹配分数)\s*[:：]?\s*' + number, re.I)
    interval_number = r'(-?\d+(?:\.\d+)?)'
    # A spaced em dash separates clauses ('Score 46.12 — 45-60 min commute'), not bounds.
    interval_body = interval_number + r'\s*(?:[-–]|(?<!\s)—|—(?!\s)|\bto\b)\s*' + interval_number
    interval_pattern = re.compile(
        r'(?<![\w.])' + interval_body + r'\s*(?:/\s*100|%)'
        + r'|\b(?:match(?:\s+score)?|fit(?:\s+score)?|score)\s*(?:range|interval)?\s*[:=]?\s*' + interval_body
        + r'|(?:评分|匹配度|匹配分数)(?:区间)?\s*[:：]?\s*' + interval_body, re.I)
    lines = final.splitlines()
    markers = [len(m.group(1)) for line in lines
        if (m := re.match(r'^(\s*)(?:[-*+] |\d+[.)] )', line))]
    list_indent = min(markers) if markers else None
    blocks, current = [], []
    title_section = False
    for line in lines:
        marker = re.match(r'^(\s*)(?:[-*+] |\d+[.)] )', line)
        table = line.lstrip().startswith('|')
        # A job heading owns its peer metadata bullets (URL, Score, Caveats).
        # Ordinary independent list items remain hard boundaries. A heading
        # cannot itself contain a URL/score, which would be an ordinary entry.
        heading = bool(re.match(r'^\s*(?:#{1,6}\s+.+|\*\*[^*]+\*\*\s*:?|\d+[.)]\s+\S.*)\s*$', line)
            and not url_pattern.search(line) and not score_pattern.search(line) and not interval_pattern.search(line))
        boundary = heading or table or (not title_section and marker and len(marker.group(1)) == list_indent)
        if (boundary or (not line.strip() and not title_section)) and current:
            blocks.append(current)
            current = []
        if heading: title_section = True
        elif table: title_section = False
        if line.strip(): current.append((line, table))
        if table:
            blocks.append(current)
            current = []
    if current: blocks.append(current)
    result = {}
    score_columns = set()
    for block in blocks:
        urls, scores, inline = [], [], []
        for index, (line, table) in enumerate(block):
            matches = list(url_pattern.finditer(line))
            line_urls = [m.group().rstrip('.,;，。；') for m in matches]
            # Remove destinations before parsing numbers (including Markdown).
            text = url_pattern.sub('', line).replace('*', '').replace('`', '')
            # "Seniority fit: 0-2 years" is level metadata, not a skill score.
            score_text = re.sub(r'\b(?:seniority|location|culture)\s+fit\s*:[^\n]*', '', text, flags=re.I)
            # A descending pair is not an interval; it is a score followed by other numbers.
            bounds = lambda m: [float(g) for g in m.groups() if g is not None]
            intervals = [m for m in interval_pattern.finditer(score_text) if bounds(m)[0] <= bounds(m)[1]]
            values = [('range', tuple(bounds(m))) for m in intervals]
            # A bound is not a point score: mask the entire interval before
            # looking for points (including the upper bound before /100).
            point_text = score_text
            for m in reversed(intervals):
                point_text = point_text[:m.start()] + ' ' + point_text[m.end():]
            values += [('score', float(next(g for g in m.groups() if g is not None)))
                for m in score_pattern.finditer(point_text)]
            if table:
                cells = text.strip().strip('|').split('|')
                headings = {i for i, cell in enumerate(cells) if re.fullmatch(
                    r'\s*(?:score|fit(?:\s+score)?|match\s+score|评分|匹配度|匹配分数)(?:\s+(?:range|interval)|区间)?'
                    r'(?:\s*\([^)]*\))?\s*', cell, re.I)}
                separator = all(re.fullmatch(r'\s*:?-+:?\s*', cell) for cell in cells)
                if headings:
                    score_columns = headings
                elif not matches and not separator:
                    # A new Salary/Job ID/Age header must not inherit an earlier
                    # table's scoring columns.
                    score_columns = set()
                values += [('score', float(cell.strip())) for i, cell in enumerate(cells)
                    if i in score_columns and re.fullmatch(r'\s*\d+(?:\.\d+)?\s*', cell)]
                values += [('range', tuple(float(g) for g in m.groups()))
                    for i, cell in enumerate(cells) if i in score_columns
                    and (m := re.fullmatch(r'\s*' + interval_body + r'\s*', cell, re.I))]
            else:
                score_columns = set()
            urls.extend((index, url) for url in line_urls)
            if len(line_urls) == 1 and values:
                inline.append((line_urls[0], values))
            elif not line_urls:
                scores.extend((index, value) for value in values)
        for url, values in inline: result.setdefault(url, []).extend(values)
        if len(urls) == 1:
            result.setdefault(urls[0][1], []).extend(value for _, value in scores)
        elif urls and scores:
            before = scores[0][0] < urls[0][0]
            for index, value in scores:
                candidates = [(i, url) for i, url in urls if i > index] if before else [
                    (i, url) for i, url in urls if i < index]
                if candidates:
                    _, url = min(candidates) if before else max(candidates)
                    result.setdefault(url, []).append(value)
    return {url: {'scores': [value for kind, value in values if kind == 'score'],
                  'ranges': [list(value) for kind, value in values if kind == 'range']}
            for url, values in result.items()}


def reply_job_scores(final):
    """Point-score compatibility API; interval bounds never masquerade as points."""
    return {url: evidence['scores'] for url, evidence in reply_job_evidence(final).items()}

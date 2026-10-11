"""ATS-friendly PDF rendering for already-grounded tailored resumes."""

from __future__ import annotations

import re
from html import escape
from io import BytesIO

from job_agent.schemas import ResumeEntry, ResumeSection, TailoredResume


def _pdf_canvas(*args, **kwargs):
    """Stable bytes let approval/download/upload checks compare the same document."""
    from reportlab.pdfgen.canvas import Canvas
    kwargs['invariant'] = 1
    return Canvas(*args, **kwargs)


def render_letter_pdf(text: str) -> bytes:
    """Export already-approved letter text without rewriting its claims."""
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    stream = BytesIO()
    document = SimpleDocTemplate(stream,pagesize=letter,leftMargin=54,rightMargin=54,topMargin=54,bottomMargin=54,
        title='Cover letter')
    style = ParagraphStyle('Letter',fontName='Helvetica',fontSize=11,leading=16)
    content = []
    for paragraph in text.split('\n\n'):
        content += [Paragraph(escape(paragraph).replace('\n','<br/>'),style),Spacer(1,12)]
    document.build(content, canvasmaker=_pdf_canvas)
    return stream.getvalue()


def _safe(value: str | None) -> str:
    return escape((value or "").replace("\u2013", "-").replace("\u2014", "-").strip())


def render_tailored_resume_pdf(value: TailoredResume | dict, *, _compact_spacing: bool = False, _roomy: bool = False) -> bytes:
    """Render a structured resume without adding, merging, or rewriting claims."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        HRFlowable,
        KeepTogether,
        ListFlowable,
        ListItem,
        Paragraph,
        PageBreak,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    resume = TailoredResume.model_validate(value)
    stream = BytesIO()
    document = SimpleDocTemplate(
        stream,
        pagesize=letter,
        leftMargin=(0.4 if _compact_spacing else 0.5) * inch,
        rightMargin=(0.4 if _compact_spacing else 0.5) * inch,
        topMargin=0.38 * inch,
        bottomMargin=0.38 * inch,
        title=resume.header.name or "Tailored Resume",
        author=resume.header.name or "",
    )
    body = ParagraphStyle(
        "ResumeBody", fontName="Helvetica", fontSize=10.5 if _roomy else 9.2, leading=13.2 if _roomy else 11.2,
        textColor=colors.HexColor("#111111"), spaceAfter=0.5 if _compact_spacing else 1.5,
    )
    name_style = ParagraphStyle(
        "ResumeName", parent=body, fontName="Helvetica-Bold", fontSize=18,
        leading=20, alignment=TA_CENTER, spaceAfter=2,
    )
    contact_style = ParagraphStyle(
        "ResumeContact", parent=body, fontSize=9.3 if _roomy else 8.8, leading=11 if _roomy else 10,
        alignment=TA_CENTER, spaceAfter=4 if _compact_spacing else 6,
    )
    section_style = ParagraphStyle(
        "ResumeSection", parent=body, fontName="Helvetica-Bold", fontSize=11.5 if _roomy else 10.5,
        leading=12, spaceBefore=2 if _compact_spacing else 4, spaceAfter=0,
    )
    entry_style = ParagraphStyle(
        "ResumeEntry", parent=body, fontName="Helvetica-Bold", fontSize=10.5 if _roomy else 9.5,
        leading=11,
    )
    meta_style = ParagraphStyle(
        "ResumeMeta", parent=body, fontSize=9.5 if _roomy else 8.9, leading=11.5 if _roomy else 10.5,
    )
    date_style = ParagraphStyle(
        "ResumeDate", parent=meta_style, alignment=2,
    )
    bullet_style = ParagraphStyle(
        "ResumeBullet", parent=body, leftIndent=0, firstLineIndent=0,
        fontSize=10.3 if _roomy else 9.0, leading=12.6 if _roomy else 10.8,
    )

    story = []
    if resume.header.name:
        story.append(Paragraph(_safe(resume.header.name), name_style))
    if resume.header.contact_lines:
        story.append(Paragraph(" &nbsp; | &nbsp; ".join(_safe(item) for item in resume.header.contact_lines if item.strip()), contact_style))

    def section_heading(section: ResumeSection) -> list:
        return [
            Spacer(1, 1 if _compact_spacing else 2),
            Paragraph(_safe(section.title).upper(), section_style),
            HRFlowable(width="100%", thickness=0.55, color=colors.HexColor("#555555"), spaceBefore=0, spaceAfter=2 if _compact_spacing else 3),
        ]

    def entry_block(entry: ResumeEntry, section_type: str) -> list:
        heading_value = entry.heading
        if heading_value and heading_value.strip().casefold() in {
            section_type.casefold(),
            "experience" if section_type == "experience" else "",
            "projects" if section_type == "projects" else "",
            "education" if section_type == "education" else "",
        }:
            heading_value = None
        heading_parts = (
            (entry.subheading, heading_value)
            if section_type in {"experience", "education"}
            else (heading_value, entry.subheading)
        )
        heading = " | ".join(_safe(item) for item in heading_parts if item)
        date_values = [item for item in (entry.start_date, entry.end_date) if item]
        if len(date_values) == 2 and date_values[0].strip().casefold() == date_values[1].strip().casefold():
            date_values = date_values[:1]
        dates = " - ".join(_safe(item) for item in date_values)
        rows = []
        if heading or dates:
            rows.append(Table(
                [[Paragraph(heading, entry_style), Paragraph(dates, date_style)]],
                colWidths=[document.width * 0.74, document.width * 0.26],
                style=TableStyle([
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0.5 if _compact_spacing else 1),
                ]),
            ))
        if entry.location:
            rows.append(Paragraph(_safe(entry.location), meta_style))
        bullets = entry.bullets
        if section_type == "education":
            # The source line often repeats the rendered header verbatim. Drop only a
            # bullet with nothing beyond header fields; qualifiers such as
            # "In progress" or "expected" stay visible.
            def header_only(text: str) -> bool:
                rest = text
                for value in (entry.heading, entry.subheading, entry.location, entry.start_date, entry.end_date):
                    if value:
                        rest = re.sub(r"\s+".join(map(re.escape, value.split())), " ", rest, flags=re.I)
                return not re.search(r"[A-Za-z0-9]", rest)
            bullets = [claim for claim in bullets if not header_only(claim.text)]
        if bullets:
            rows.append(ListFlowable(
                [ListItem(Paragraph(_safe(claim.text), bullet_style), leftIndent=9) for claim in bullets],
                bulletType="bullet", bulletFontName="Helvetica", bulletFontSize=5,
                start="square", leftIndent=11, bulletOffsetY=1.5, spaceAfter=1 if _compact_spacing else 2,
            ))
        return rows

    # Keep headings with their first entry and balance whole entries across
    # the minimum number of pages. Content and font sizes are unchanged.
    groups = []
    for section in resume.sections:
        if not section.entries:
            continue
        heading = section_heading(section)
        if section.section_type == "summary":
            text = " ".join(_safe(claim.text) for entry in section.entries for claim in entry.bullets)
            if text:
                groups.append([*heading, Paragraph(text, body)])
        elif section.section_type == "skills":
            skills = [_safe(claim.text) for entry in section.entries for claim in entry.bullets]
            if skills:
                groups.append([*heading, Paragraph(" &nbsp; | &nbsp; ".join(skills), body)])
        else:
            first = True
            for entry in section.entries:
                block = entry_block(entry, section.section_type)
                if block:
                    groups.append([*(heading if first else []), *block, Spacer(1, 1 if _compact_spacing else 1.5)])
                    first = False
    if groups:
        groups[0] = [*story, *groups[0]]
    elif story:
        groups = [story]
    from reportlab.pdfgen.canvas import Canvas
    canvas = Canvas(BytesIO())
    width, capacity = document.width - 12, document.height - 24
    heights = []
    for group in groups:
        # Counting all spacing is conservative: ReportLab collapses adjacent
        # spacing. Leave additional room for the frame's padding.
        height = 0
        for flowable in group:
            _, h = flowable.wrapOn(canvas, width, document.height)
            height += h + flowable.getSpaceBefore() + flowable.getSpaceAfter()
        heights.append(height)
    # A small overflow often strands a skills block on a nearly empty page.
    # Try tighter whitespace once, keeping all content, font sizes and leading.
    # Longer documents retain normal spacing and balanced complete entries.
    if not _compact_spacing and not _roomy and capacity < sum(heights) <= capacity * 1.12:
        return render_tailored_resume_pdf(resume, _compact_spacing=True)
    if _compact_spacing and sum(heights) > capacity:
        # If all content cannot fit legibly on one page, use the necessary two
        # pages for larger readable type instead of two tiny half-empty pages.
        return render_tailored_resume_pdf(resume, _roomy=True)
    breaks = _balanced_page_breaks(heights, capacity)
    story = []
    for index, group in enumerate(groups):
        if index in breaks:
            story.append(PageBreak())
        story.append(KeepTogether(group))
    document.build(story, canvasmaker=_pdf_canvas)
    return stream.getvalue()


def _balanced_page_breaks(heights: list[float], capacity: float) -> set[int]:
    """Minimum ordered pages, then minimum squared unused space.

    Oversized individual entries fall back to ReportLab's normal splitting.
    This planner never drops content or shrinks text to force a page count.
    """
    if not heights or any(height > capacity for height in heights):
        return set()
    best = [(0, 0.0, [])]
    for end in range(1, len(heights) + 1):
        candidates, used = [], 0.0
        for begin in range(end - 1, -1, -1):
            used += heights[begin]
            if used > capacity:
                break
            pages, cost, breaks = best[begin]
            candidates.append((pages + 1, cost + (capacity - used) ** 2,
                               [*breaks, begin] if begin else breaks))
        best.append(min(candidates, key=lambda value: value[:2]))
    return set(best[-1][2])

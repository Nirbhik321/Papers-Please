"""
exporter.py — Generate exports: PDF cheat sheet and CSV question bank.

PDF: an A4 cheat sheet — the most repeated topics per module and the marks they cover.
CSV: ordered question bank for teachers to build internal assessments.
"""

import csv
import io
from datetime import date

from fpdf import FPDF, XPos, YPos

from modules.scorer import format_years, MAX_MODULE_MARKS


# ── ASCII sanitizer (Helvetica supports Latin-1 only) ─────────────────────────

_UNICODE_REPLACEMENTS = str.maketrans({
    "\u2018": "'",  "\u2019": "'",   # curly single quotes
    "\u201c": '"',  "\u201d": '"',   # curly double quotes  ← the current crash
    "\u2013": "-",  "\u2014": "-",   # en-dash, em-dash
    "\u2022": "*",  "\u00b7": "*",   # bullet points
    "\u00ae": "(R)", "\u00a9": "(C)", # registered, copyright
    "\u2026": "...",                  # ellipsis
    "\u00b0": "deg",                  # degree
    "\u2192": "->", "\u2190": "<-",  # arrows
    "\u2605": "*",  "\u2606": "*",   # filled/open stars
    "\u00e2": "a",  "\u00e9": "e",   # common accented chars from bad OCR
})


def _safe(text: str) -> str:
    """Strip non-Latin-1 characters so fpdf Helvetica never crashes."""
    text = text.translate(_UNICODE_REPLACEMENTS)
    # Replace any remaining non-Latin-1 chars with '?'
    return text.encode("latin-1", errors="replace").decode("latin-1")


# ── Palette (matches the website) ──────────────────────────────────────────────
INK        = (27,  34,  51)
INK_2      = (74,  81,  99)
LINE       = (221, 215, 201)
BAND       = (242, 239, 231)
STAMP      = (169, 50,  38)
AMBER      = (208, 138, 60)
OUTLINE    = (138, 142, 153)
OK_GREEN   = (30,  90,  57)
WHITE      = (255, 255, 255)

PAGE_W, MARGIN = 210, 15
CONTENT_W = PAGE_W - 2 * MARGIN
ROWS_PER_MODULE = 3


def generate_cheat_sheet(
    subject_name: str,
    subject_code: str,
    module_ladders: dict[int, list[dict]],   # {module_no: [step, ...]}
    total_papers: int,
    output_path: str,
    site_url: str = "",
) -> str:
    """
    Generate the one-page A4 cheat sheet: for each module, the topics that
    repeat most (up to the point where the module's marks are covered).

    Args:
        subject_name: e.g. "Computer Networks"
        subject_code: e.g. "BCS502"
        module_ladders: {module_no: result of scorer.build_marks_ladder()}
        total_papers: number of papers analysed
        output_path: file path to write the PDF
        site_url: optional website base, printed in the footer

    Returns:
        output_path (for convenience)
    """
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_margins(MARGIN, 14, MARGIN)
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.set_title(_safe(f"{subject_code} {subject_name} - cheat sheet"))
    pdf.add_page()

    _draw_header(pdf, subject_name, subject_code, total_papers)
    for module_no in sorted(module_ladders):
        steps = module_ladders[module_no]
        if steps:
            _draw_module(pdf, module_no, steps, total_papers)
    _draw_footer(pdf, subject_code, site_url)

    pdf.output(output_path)
    return output_path


def _tier(step: dict, total_papers: int) -> tuple[tuple, tuple]:
    """(fill, border) of the frequency square: 5-6 of 6 papers, 3-4, 1-2."""
    pct = step["frequency_pct"]
    if total_papers > 1 and pct >= 0.8:
        return STAMP, STAMP
    if total_papers > 1 and pct >= 0.5:
        return AMBER, AMBER
    return WHITE, OUTLINE


def _square(pdf: FPDF, x: float, y: float, fill: tuple, border: tuple, size: float = 2.6):
    pdf.set_fill_color(*fill)
    pdf.set_draw_color(*border)
    pdf.set_line_width(0.35)
    pdf.rect(x, y, size, size, style="DF")


def _draw_header(pdf: FPDF, subject_name: str, subject_code: str, total_papers: int):
    top = pdf.get_y()
    pdf.set_text_color(*STAMP)
    pdf.set_font("Helvetica", "B", 7)
    pdf.cell(0, 4, "PAPERS PLEASE  -  CHEAT SHEET", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(*INK)
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(125, 9, _safe(f"{subject_code}  {subject_name}"[:60]), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(*INK_2)
    pdf.set_font("Helvetica", "", 8)
    papers = f"{total_papers} paper{'s' if total_papers != 1 else ''}"
    pdf.cell(125, 5, f"From {papers}  -  generated {date.today().strftime('%d %b %Y')}",
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    bottom = pdf.get_y()

    # Legend, top right
    legend = [(STAMP, STAMP, "Very likely  -  most papers"), (AMBER, AMBER, "Likely  -  half or more"),
              (WHITE, OUTLINE, "Occasional")]
    pdf.set_font("Helvetica", "", 7.5)
    pdf.set_text_color(*INK_2)
    for i, (fill, border, label) in enumerate(legend):
        y = top + 3 + i * 5
        _square(pdf, 150, y, fill, border)
        pdf.set_xy(154, y - 0.9)
        pdf.cell(40, 4.4, label)

    pdf.set_y(max(bottom, top + 18) + 1.5)
    pdf.set_draw_color(*INK)
    pdf.set_line_width(0.6)
    pdf.line(MARGIN, pdf.get_y(), PAGE_W - MARGIN, pdf.get_y())
    pdf.ln(3.5)


def _draw_module(pdf: FPDF, module_no: int, steps: list[dict], total_papers: int):
    full_at = next((s["rank"] for s in steps if s["full_coverage"]), None)
    shown = steps[: min(full_at or ROWS_PER_MODULE, ROWS_PER_MODULE)]
    last = shown[-1]
    if full_at and full_at <= ROWS_PER_MODULE:
        ladder = f"Top {full_at} -> full {MAX_MODULE_MARKS}M"
    else:
        ladder = f"Top {len(shown)} -> ~{last['cumulative_expected']:.0f} of {MAX_MODULE_MARKS}M"

    if pdf.get_y() > 297 - 16 - 30:   # keep a module's band with its first rows
        pdf.add_page()

    y = pdf.get_y()
    pdf.set_fill_color(*BAND)
    pdf.rect(MARGIN, y, CONTENT_W, 6.5, style="F")
    pdf.set_xy(MARGIN + 2.5, y + 1)
    pdf.set_text_color(*INK)
    pdf.set_font("Helvetica", "B", 9.5)
    pdf.cell(100, 4.5, f"Module {module_no}")
    pdf.set_text_color(*OK_GREEN)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_xy(MARGIN, y + 1)
    pdf.cell(CONTENT_W - 2.5, 4.5, ladder, align="R")
    pdf.set_y(y + 8)

    for step in shown:
        _draw_row(pdf, step, total_papers)
    pdf.ln(3)


def _draw_row(pdf: FPDF, step: dict, total_papers: int):
    if pdf.get_y() > 297 - 16 - 14:   # never split a row across pages
        pdf.add_page()
    y = pdf.get_y()
    fill, border = _tier(step, total_papers)
    _square(pdf, MARGIN + 2.5, y + 1.1, fill, border)

    text_x, text_w = MARGIN + 8, CONTENT_W - 32
    pdf.set_xy(text_x, y)
    pdf.set_text_color(*INK)
    pdf.set_font("Helvetica", "B", 9.5)
    pdf.cell(text_w, 4.8, _safe(step["topic_label"] or step["representative_text"][:60])[:80])

    # Right-hand numbers: papers and usual marks
    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_text_color(*INK_2)
    pdf.set_xy(PAGE_W - MARGIN - 22, y)
    pdf.cell(11, 4.8, f"{step['frequency']}/{total_papers}", align="R")
    pdf.set_text_color(*INK)
    pdf.set_font("Helvetica", "B", 8.5)
    marks = int(round(step.get("avg_marks") or 0))
    pdf.cell(11, 4.8, f"{marks}M" if marks else "-", align="R")

    text = " ".join(step["representative_text"].split())
    text = text if len(text) <= 170 else text[:167].rsplit(" ", 1)[0] + "..."
    pdf.set_xy(text_x, y + 4.8)
    pdf.set_text_color(*INK_2)
    pdf.set_font("Helvetica", "", 7.8)
    pdf.multi_cell(text_w, 3.6, _safe(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_draw_color(*LINE)
    pdf.set_line_width(0.2)
    pdf.line(MARGIN, pdf.get_y() + 1.2, PAGE_W - MARGIN, pdf.get_y() + 1.2)
    pdf.ln(2.4)


def _draw_footer(pdf: FPDF, subject_code: str, site_url: str):
    pdf.set_auto_page_break(False)
    pdf.set_y(-13)
    pdf.set_draw_color(*LINE)
    pdf.set_line_width(0.2)
    pdf.line(MARGIN, pdf.get_y(), PAGE_W - MARGIN, pdf.get_y())
    pdf.ln(1.5)
    pdf.set_text_color(*INK_2)
    pdf.set_font("Helvetica", "", 7)
    left = f"Every topic and wording: {site_url.rstrip('/')}/s/{subject_code}" if site_url else "Papers Please"
    pdf.cell(CONTENT_W / 2, 4, _safe(left))
    pdf.cell(CONTENT_W / 2, 4, "Based on how often topics repeated - not a guarantee of what will appear.", align="R")


# ── CSV question bank ─────────────────────────────────────────────────────────

def generate_csv(
    subject_name: str,
    subject_code: str,
    module_ladders: dict[int, list[dict]],
    total_papers: int,
) -> str:
    """
    Generate a CSV question bank sorted by module then priority rank.

    Returns the CSV content as a string (ready for st.download_button).
    """
    buf = io.StringIO()
    writer = csv.writer(buf)

    writer.writerow([
        "Module", "Priority Rank", "Topic Label", "Question Text",
        "Avg Marks", "Times Repeated", "Total Papers", "Frequency %",
        "Years Seen", "Expected Marks", "Full Coverage",
    ])

    for module_no in sorted(module_ladders.keys()):
        for step in module_ladders[module_no]:
            writer.writerow([
                module_no,
                step["rank"],
                step.get("topic_label") or "",
                step["representative_text"],
                int(step.get("avg_marks") or 0),
                step["frequency"],
                total_papers,
                f"{step['frequency_pct'] * 100:.0f}%",
                format_years(step.get("years", [])),
                f"{step.get('expected_marks', 0):.1f}",
                "YES" if step["full_coverage"] else "",
            ])

    return buf.getvalue()

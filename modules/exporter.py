"""
exporter.py — Generate exports: PDF cheat sheet and CSV question bank.

PDF: one page per subject with ranked questions, frequency bars, marks ladder.
CSV: ordered question bank for teachers to build internal assessments.
"""

import csv
import io
from datetime import date

from fpdf import FPDF, XPos, YPos

from modules.scorer import format_years, format_appearances, MAX_MODULE_MARKS


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


# ── Colour palette ─────────────────────────────────────────────────────────────
BLACK       = (0,   0,   0)
WHITE       = (255, 255, 255)
DARK_GREY   = (40,  40,  40)
MID_GREY    = (120, 120, 120)
LIGHT_GREY  = (230, 230, 230)
ACCENT      = (30,  100, 200)   # blue for module headers
GREEN       = (20,  140, 60)    # for guaranteed marks
ORANGE      = (210, 100, 0)     # for medium-priority
RED_DARK    = (180, 30,  30)    # for top-priority stars


def generate_cheat_sheet(
    subject_name: str,
    subject_code: str,
    module_ladders: dict[int, list[dict]],   # {module_no: [step, ...]}
    total_papers: int,
    output_path: str,
) -> str:
    """
    Generate the cheat sheet PDF.

    Args:
        subject_name: e.g. "Computer Networks"
        subject_code: e.g. "BCS502"
        module_ladders: {module_no: result of scorer.build_marks_ladder()}
        total_papers: number of papers analysed
        output_path: file path to write the PDF

    Returns:
        output_path (for convenience)
    """
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_margins(15, 15, 15)

    _draw_header(pdf, subject_name, subject_code, total_papers)

    for module_no in sorted(module_ladders.keys()):
        steps = module_ladders[module_no]
        if not steps:
            continue
        _draw_module_section(pdf, module_no, steps, total_papers)

    _draw_footer(pdf)
    pdf.output(output_path)
    return output_path


# ── Header ─────────────────────────────────────────────────────────────────────

def _draw_header(pdf: FPDF, subject_name: str, subject_code: str, total_papers: int):
    # Title bar
    pdf.set_fill_color(*ACCENT)
    pdf.rect(x=15, y=pdf.get_y(), w=180, h=12, style="F")
    pdf.set_text_color(*WHITE)
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(180, 12, _safe(f"  PAPERS PLEASE  -  {subject_code} {subject_name}"),
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_text_color(*MID_GREY)
    pdf.set_font("Helvetica", "", 8)
    pdf.cell(180, 5,
             f"  Based on {total_papers} papers  ·  Generated {date.today().strftime('%d %b %Y')}",
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(3)


# ── Module section ─────────────────────────────────────────────────────────────

def _draw_module_section(pdf: FPDF, module_no: int, steps: list[dict], total_papers: int):
    # Module header
    pdf.set_fill_color(*LIGHT_GREY)
    pdf.set_text_color(*DARK_GREY)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(180, 7, f"  Module {module_no}", fill=True,
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1)

    for step in steps:
        _draw_question_row(pdf, step, total_papers)

    # Marks ladder summary
    _draw_marks_ladder(pdf, steps)
    pdf.ln(4)


def _draw_question_row(pdf: FPDF, step: dict, total_papers: int):
    rank = step["rank"]
    label = _safe(step["topic_label"] or step["representative_text"][:60])
    freq = step["frequency"]
    freq_pct = step["frequency_pct"]
    avg_marks = step["avg_marks"]
    years = step.get("years", [])
    appearances = step.get("appearances", [])
    text_preview = _safe(step["representative_text"][:100])

    # Star rating
    stars = "***" if freq_pct >= 0.8 else ("** " if freq_pct >= 0.5 else "*  ")
    star_color = RED_DARK if freq_pct >= 0.8 else (ORANGE if freq_pct >= 0.5 else MID_GREY)

    pdf.set_text_color(*star_color)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(10, 6, stars)

    pdf.set_text_color(*DARK_GREY)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(100, 6, label[:55])

    # Frequency bar
    bar_w = int(freq_pct * 40)
    x = pdf.get_x()
    y = pdf.get_y() + 1
    pdf.set_fill_color(*ACCENT)
    pdf.rect(x=x, y=y, w=bar_w, h=4, style="F")
    pdf.set_fill_color(*LIGHT_GREY)
    pdf.rect(x=x + bar_w, y=y, w=40 - bar_w, h=4, style="F")
    pdf.set_x(x + 42)

    pdf.set_text_color(*MID_GREY)
    pdf.set_font("Helvetica", "", 8)
    pdf.cell(18, 6, f"{freq}/{total_papers}")
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(*DARK_GREY)
    pdf.cell(10, 6, f"{int(avg_marks)}M", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # Year + position metadata
    years_str = _safe(format_years(years))
    seen_str = _safe(format_appearances(appearances))
    pdf.set_text_color(*MID_GREY)
    pdf.set_font("Helvetica", "", 7)
    pdf.set_x(20)
    pdf.cell(160, 4, f"Years: {years_str}  |  Seen in: {seen_str}",
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # Question text preview
    suffix = "..." if len(step["representative_text"]) > 100 else ""
    pdf.set_x(20)
    pdf.set_font("Helvetica", "I", 7)
    pdf.set_text_color(*MID_GREY)
    pdf.multi_cell(160, 4, f'"{text_preview}{suffix}"',
                   new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1)


def _draw_marks_ladder(pdf: FPDF, steps: list[dict]):
    """Draw the cumulative marks guarantee box."""
    pdf.set_fill_color(240, 248, 255)
    pdf.set_draw_color(*ACCENT)
    start_y = pdf.get_y()

    # Draw box content
    pdf.set_text_color(*ACCENT)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_x(15)
    pdf.cell(180, 5, "  MARKS YOU LOCK IN", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    for step in steps:
        rank = step["rank"]
        label = step["topic_label"] or "..."
        cum = step["cumulative_expected"]
        full = step["full_coverage"]

        color = GREEN if full else (ORANGE if cum >= MAX_MODULE_MARKS * 0.5 else MID_GREY)
        pdf.set_text_color(*color)
        pdf.set_font("Helvetica", "", 8)
        pdf.set_x(18)
        checkmark = "[OK]" if full else "    "
        pdf.cell(
            180, 4,
            _safe(
                f"  {checkmark} Study top {rank} topic{'s' if rank > 1 else ''}"
                f" ({label[:30]}) -> Expected ~{cum:.0f}M"
                f"{'  << FULL COVERAGE' if full else ''}"
            ),
            new_x=XPos.LMARGIN, new_y=YPos.NEXT,
        )
        if full:
            break

    pdf.ln(1)


# ── Footer ─────────────────────────────────────────────────────────────────────

def _draw_footer(pdf: FPDF):
    pdf.set_y(-12)
    pdf.set_text_color(*MID_GREY)
    pdf.set_font("Helvetica", "I", 7)
    pdf.cell(
        0, 5,
        "Papers Please  -  Frequency analysis only - not a guarantee of exam content.",
        align="C",
    )


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

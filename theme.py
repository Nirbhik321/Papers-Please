"""
theme.py — shared visual theme for the public-facing pages.

Call inject_theme() once near the top of each public page. The Admin page
deliberately does NOT use this — staying plain is a visual cue that you've
left the student-facing app and you're in an operational area.
"""

from pathlib import Path

import streamlit as st

_CSS_PATH = Path(__file__).parent / "assets" / "style.css"


def inject_theme():
    css = _CSS_PATH.read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def exam_header(
    title: str,
    subtitle: str = "",
    time: str = "However long you need",
    max_marks: str = "No limit",
    note: str = "",
    show_usn: bool = True,
):
    """The signature hero block, styled like a VTU exam-paper header."""
    usn_html = ""
    if show_usn:
        boxes = "".join("<span class='usn-box'></span>" for _ in range(10))
        usn_html = f"""
        <div class="usn-strip">
            <span class="usn-label">USN</span>
            <div class="usn-boxes">{boxes}</div>
        </div>
        """

    subtitle_html = f'<p class="exam-subtitle">{subtitle}</p>' if subtitle else ""
    note_html = f'<p class="exam-note">Note: {note}</p>' if note else ""

    st.markdown(
        f"""
        <div class="exam-header">
          {usn_html}
          <h1 class="exam-title">{title}</h1>
          {subtitle_html}
          <div class="exam-header-row">
            <span>Time: {time}</span>
            <span>Max Marks: {max_marks}</span>
          </div>
          {note_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def stamp(text: str, kind: str = "violet") -> str:
    """
    Inline HTML for an 'official stamp' badge. Returns a string —
    embed it inside an st.markdown(..., unsafe_allow_html=True) call.
    kind: 'violet' (default) or 'red'
    """
    css_class = "stamp stamp-red" if kind == "red" else "stamp"
    return f'<span class="{css_class}">{text}</span>'


def mark_circle(text: str, level: str = "high") -> str:
    """
    Inline HTML for a red-pen-circled mark, replacing emoji priority dots.
    level: 'high' (red), 'mid' (violet), 'low' (muted)
    """
    css_class = "mark-circle" if level == "high" else f"mark-circle {level}"
    return f'<span class="{css_class}">{text}</span>'
"""
data_cache.py — caching wrappers around the read-heavy backend calls.

Streamlit reruns the *entire* page script on every interaction (every
button click, tab switch, selectbox change, checkbox toggle — not just on
page load). Without caching, that means re-hitting SQLite and rebuilding
every module's marks ladder from scratch on every single click, even when
nothing in the database has changed. That's almost always the real cause
of "Streamlit feels slow."

These wrappers use @st.cache_data, keyed on the database file's mtime, so:
  - repeated reruns with no new data hit the cache (fast)
  - the moment a paper is uploaded/deleted (DB file changes), the cache
    for that db_path invalidates automatically

No backend code changes — this only wraps functions that already exist
in modules/db.py and pipeline.py.
"""

import os

import streamlit as st

import pipeline
from modules.db import get_all_papers as _get_all_papers
from modules.db import get_distinct_subjects as _get_distinct_subjects


def db_version(db_path: str) -> float:
    """mtime of the DB file — changes whenever the DB is written to."""
    try:
        return os.path.getmtime(db_path)
    except OSError:
        return 0.0


@st.cache_data(show_spinner=False)
def get_all_papers_cached(db_path: str, _version: float):
    return _get_all_papers(db_path)


@st.cache_data(show_spinner=False)
def get_distinct_subjects_cached(db_path: str, _version: float):
    return _get_distinct_subjects(db_path)


@st.cache_data(show_spinner=False)
def get_module_analysis_cached(db_path: str, subject_code: str, _version: float):
    return pipeline.get_module_analysis(db_path, subject_code)
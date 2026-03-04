import html
import hashlib
import json
from typing import Any

import streamlit as st

from utils import record_identifier


def _safe_text(value: Any) -> str:
    """Escape a value for safe HTML rendering."""
    return html.escape(str(value or "").strip())


def _record_hash(rec_id: str) -> str:
    """Generate a short hash for a record identifier."""
    return hashlib.md5(rec_id.encode("utf-8")).hexdigest()[:10]


def _add_skipped_publication(rec_id: str) -> None:
    """Add a publication to the skipped list in session state."""
    skipped = st.session_state.get("html_skipped_publications", [])
    if rec_id not in skipped:
        st.session_state["html_skipped_publications"] = skipped + [rec_id]


def render_html_preview(payload: dict | None, container: Any = None, top_n: int | None = None) -> None:
    """Render top-N records as a compact HTML-style preview.

    Per record layout (6/7 rows):
    1) Title, Type
    2) Year, Citation, Doi
    3) Relevance Score (if available)
    4) Authors
    5) Topic
    6) Keywords
    7) Abstract
    """
    display = container if container is not None else None
    if display is None:
        return

    if not payload:
        display.warning("No results available.")
        return

    raw = payload.get("json")
    if raw is None:
        display.warning("No results available.")
        return

    try:
        records = json.loads(raw)
    except Exception:
        display.warning("Could not parse results JSON.")
        return

    if not isinstance(records, list) or not records:
        display.warning("No results available.")
        return

    if top_n is None:
        preview = records
    else:
        preview = records[: max(int(top_n), 1)]

    display.markdown(
        """
        <style>
        .html-preview-card {
            border: 1px solid #d9e4ee;
            border-radius: 8px;
            padding: 10px 12px;
            margin-bottom: 10px;
            background: #ffffff;
        }
        .html-preview-row {
            margin: 2px 0;
            line-height: 1.45;
            color: #1f2937;
        }
        .html-preview-label {
            color: #1f77b4;
            font-weight: 600;
        }
        .html-preview-view-btn {
            display: inline-block;
            margin-left: 8px;
            padding: 2px 8px;
            font-size: 12px;
            line-height: 1.4;
            color: #ffffff !important;
            background: #1f77b4;
            border: 1px solid #1f77b4;
            border-radius: 6px;
            text-decoration: none;
            vertical-align: middle;
        }
        .html-preview-view-btn:hover {
            background: #166aa3;
            border-color: #166aa3;
            text-decoration: none;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    for rec in preview:
        rec_id = record_identifier(rec)
        rec_hash = _record_hash(rec_id)

        title = _safe_text(rec.get("Title"))
        work_type = _safe_text(rec.get("Type"))
        year = _safe_text(rec.get("Publication Year"))
        citation = _safe_text(rec.get("Citations"))
        doi = _safe_text(rec.get("DOI"))
        relevance = _safe_text(rec.get("Relevance Score"))
        openalex_url = _safe_text(rec.get("OpenAlex URL"))
        authors = _safe_text(rec.get("Authors"))
        topics = _safe_text(rec.get("Topics"))
        keywords = _safe_text(rec.get("Keywords"))
        abstract = _safe_text(rec.get("Abstract"))

        relevance_row = ""
        view_btn = ""
        if openalex_url:
            view_btn = (
                f'<a class="html-preview-view-btn" href="{openalex_url}" target="_blank" rel="noopener noreferrer">View</a>'
            )

        if relevance or openalex_url:
            url_part = f", <span class=\"html-preview-label\">OpenAlex URL</span>: {openalex_url}" if openalex_url else ""
            relevance_row = (
                f'<div class="html-preview-row"><span class="html-preview-label">Relevance Score</span>: {relevance}{url_part}{view_btn}</div>'
            )

        card_html = f"""
        <div class="html-preview-card">
            <div class="html-preview-row"><span class="html-preview-label">Title</span>: {title}, <span class="html-preview-label">Type</span>: {work_type}</div>
            <div class="html-preview-row"><span class="html-preview-label">Year</span>: {year}, <span class="html-preview-label">Citation</span>: {citation}, <span class="html-preview-label">Doi</span>: {doi}</div>
            {relevance_row}
            <div class="html-preview-row"><span class="html-preview-label">Authors</span>: {authors}</div>
            <div class="html-preview-row"><span class="html-preview-label">Topic</span>: {topics}</div>
            <div class="html-preview-row"><span class="html-preview-label">Keywords</span>: {keywords}</div>
            <div class="html-preview-row"><span class="html-preview-label">Abstract</span>: {abstract}</div>
        </div>
        """

        display.markdown(card_html, unsafe_allow_html=True)

        btn_col1, btn_col2, btn_col3, btn_col4 = display.columns(4)
        with btn_col1:
            st.button(
                "Skip",
                key=f"skip_pub_{rec_hash}",
                type="primary",
                on_click=_add_skipped_publication,
                args=(rec_id,),
                use_container_width=True,
            )
        with btn_col2:
            similar_clicked = st.button(
                "Similar works",
                key=f"similar_pub_{rec_hash}",
                type="primary",
                use_container_width=True,
            )
        with btn_col3:
            citing_clicked = st.button(
                "Citing works",
                key=f"citing_pub_{rec_hash}",
                type="primary",
                use_container_width=True,
            )
        with btn_col4:
            cited_clicked = st.button(
                "Cited works",
                key=f"cited_pub_{rec_hash}",
                type="primary",
                use_container_width=True,
            )

        if similar_clicked:
            display.info("Similar works is under construction.")
        if citing_clicked:
            display.info("Citing works is under construction.")
        if cited_clicked:
            display.info("Cited works is under construction.")

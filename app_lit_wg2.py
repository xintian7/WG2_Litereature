import streamlit as st
from pathlib import Path
import json
import pandas as pd

from button_search import perform_search
from button_analyze import perform_analyze
from button_neo4j import build_neo4j_cypher
from button_html import render_html_preview
from utils import (
    record_identifier,
    DISPLAY_CONTAINER_HEIGHT,
    MAX_WORK_TYPES,
    UN_MEMBER_STATES,
    UN_MEMBER_STATE_TO_COUNTRY_CODE,
)


st.markdown("""
<style>

/* Hide top toolbar (Fork + GitHub) */
[data-testid="stToolbar"]{
    display:none;
}

/* Hide Streamlit footer ("Hosted with Streamlit") */
footer {
    visibility: hidden;
    display: none !important;
}

/* Hide GitHub + Streamlit footer container */
[data-testid="stStatusWidget"] {
    display: none;
}

/* Hide bottom decoration (GitHub avatar / repo badge) */
[data-testid="stDecoration"] {
    display: none;
}
            
</style>
""", unsafe_allow_html=True)


def _payload_after_skips(payload: dict | None) -> dict | None:
    """Return a payload filtered by skipped publications for downloads."""
    if not payload:
        return payload

    skipped_ids = set(st.session_state.get("html_skipped_publications", []))
    if not skipped_ids:
        return payload

    try:
        records = json.loads(payload.get("json") or "[]")
    except Exception:
        return payload

    if not isinstance(records, list):
        return payload

    filtered_records = [
        rec for rec in records
        if record_identifier(rec) not in skipped_ids
    ]

    filtered_payload = dict(payload)
    filtered_payload["json"] = json.dumps(
        filtered_records,
        indent=2,
        ensure_ascii=False,
    ).encode("utf-8")
    filtered_payload["csv"] = pd.DataFrame(filtered_records).to_csv(index=False).encode("utf-8")
    filtered_payload["total"] = len(filtered_records)
    return filtered_payload


# ---- IPCC STYLE ----
st.markdown("""
<style>
.main-title {
    /* no background to keep default page background */
    color: #00a9cf;
    padding: 20px;
    border-radius: 10px;
    text-align: center;
    font-size: 42px;
    font-weight: 700;
    letter-spacing: 1px;
}

/* Primary button styling */
div.stButton > button[kind="primary"] {
    background-color: #1f77b4;
    color: #ffffff;
    border: 1px solid #1f77b4;
    min-height: 48px;
    padding: 0.5rem 1.25rem;
    white-space: nowrap;
}
div.stButton > button[kind="primary"]:hover {
    background-color: #166aa3;
    border-color: #166aa3;
}
/* Download button styling to match primary */
div.stDownloadButton > button {
    background-color: #1f77b4;
    color: #ffffff;
    border: 1px solid #1f77b4;
    min-height: 48px;
    padding: 0.5rem 1.25rem;
    white-space: nowrap;
}
div.stDownloadButton > button:hover {
    background-color: #166aa3;
    border-color: #166aa3;
}
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-title">Climate Knowledge Finder</div>', unsafe_allow_html=True)
st.markdown("<h3 style='text-align:center'>Settings</h3>", unsafe_allow_html=True)

# OpenAlex API control below title
label_col, input_col = st.columns([1, 4])
with label_col:
    st.markdown("**OpenAlex API**")
with input_col:
    openalex_api = st.text_input(
        "",
        value="",
        placeholder="Enter OpenAlex API key",
        label_visibility="collapsed",
        key="openalex_api_input",
    )

# OpenAI API control below OpenAlex API
label_col, input_col = st.columns([1, 4])
with label_col:
    st.markdown("**OpenAI API**")
with input_col:
    openai_api = st.text_input(
        "",
        value="",
        placeholder="Enter OpenAI API key",
        label_visibility="collapsed",
        key="openai_api_input",
    )

# Sidebar


with st.sidebar:
    st.header("About")
    st.markdown(
        "<span style='color: #00a9cf; font-weight: bold;'>Climate Knowledge Finder</span> (ver 0.1) "
        "is a web app developed by the IPCC [WGII](https://www.ipcc.ch/working-group/wg2/) TSU to help IPCC authors find climate-related grey literature from [OpenAlex](https://openalex.org)'s database. "
        "Please contact xxx@ipccwg2.org if you have any questions or suggestions.",
        unsafe_allow_html=True
    )
    # Sidebar keeps About and Disclaimer only; search controls moved to main page

    st.sidebar.markdown("### Disclaimer")
    st.sidebar.markdown(
        "The information provided by "
        "<span style='color: #00a9cf; font-weight: bold;'>Climate Knowledge Finder</span> "
        " is sourced from [OpenAlex](https://openalex.org). "
        "While we strive to ensure accuracy, we cannot guarantee the completeness or reliability of the data. "
        "Users are encouraged to verify the information independently before making decisions based on it.",
        unsafe_allow_html=True
    )

    st.sidebar.markdown("### To-do")
    st.sidebar.checkbox("Authentications for GS users.", value=False, key="todo_auth_gs")
    st.sidebar.checkbox("Knowledge graphs and network analysis.", value=False, key="todo_kg")
    st.sidebar.checkbox("More flexible search controls (e.g., more types, more filters).", value=False, key="todo_search_controls")
    st.sidebar.checkbox("More result metadata (e.g., abstracts) and better display (e.g., HTML preview, highlights).", value=False, key="todo_metadata")
    st.sidebar.checkbox("Performance improvements for larger result sets.", value=False, key="todo_perf")
    st.sidebar.checkbox("More export formats (e.g., Excel, Zotero, EndNote).", value=False, key="todo_exports")
    st.sidebar.checkbox("User accounts and saved searches.", value=False, key="todo_accounts")
    # logo_path = Path(__file__).parent / "assets" / "ipcc.png"
    # if logo_path.exists():
    #     st.sidebar.image(str(logo_path), width=200)
    # else:
    #     st.sidebar.caption("IPCC logo not found at assets/ipcc.png")

# Main search section (centered title and controls in one row)
st.divider()
st.markdown("<h3 style='text-align:center'>Grey literature searching</h3>", unsafe_allow_html=True)

# Keyword: label+help line, then control line
label_col, help_col = st.columns([1, 4])
with label_col:
    st.markdown("**Keyword**")
with help_col:
    st.caption("You can add multiple keywords below, using ; to separate. The sign ; indicates an AND operator.")
kw_col1, kw_col2 = st.columns([1, 4])
with kw_col1:
    st.write("")
with kw_col2:
    keyword = st.text_input("", value="climate change; water", label_visibility="collapsed", key="kw")

# Publication year: label+help line, then slider line
label_col, help_col = st.columns([1, 4])
with label_col:
    st.markdown("**Publication year**")
with help_col:
    st.caption("Select a start and end year for the publication date range.")
yr_col1, yr_col2 = st.columns([1, 4])
with yr_col1:
    st.write("")
with yr_col2:
    year_range = st.slider("", 1900, 2027, (2000, 2026), label_visibility="collapsed", key="yr")

# Type: label+help line, then multiselect line
label_col, help_col = st.columns([1, 4])
with label_col:
    st.markdown("**Type**")
with help_col:
    st.caption("Due to processing time, you can select up to 3 categories at one time. "
    "It will be improved in a future version to allow more categories.")
type_col1, type_col2 = st.columns([1, 4])
with type_col1:
    st.write("")
with type_col2:
    work_types = st.multiselect(
        "",
        options=[
            "article",
            "book",
            "book-chapter",
            "book-section",
            "database",
            "dataset",
            "dissertation",
            "editorial",
            "erratum",
            "grant",
            "letter",
            "libguides",
            "other",
            "paratext",
            "peer-review",
            "preprint",
            "reference-entry",
            "report",
            "report-component",
            "review",
            "software",
            "standard",
            "supplementary-materials",
        ],
        default=["report", "preprint"],
        label_visibility="collapsed",
        key="wt",
    )
    if work_types and len(work_types) > MAX_WORK_TYPES:
        st.warning(f"You selected more than {MAX_WORK_TYPES} types — only the first {MAX_WORK_TYPES} will be used.")
        work_types = work_types[:MAX_WORK_TYPES]

# Language: label+help line, then control line
label_col, help_col = st.columns([1, 4])
with label_col:
    st.markdown("**Language**")
with help_col:
    st.caption("Filter results by language. Default is English.")
lang_col1, lang_col2 = st.columns([1, 4])
with lang_col1:
    st.write("")
with lang_col2:
    language_option = st.selectbox(
        "",
        options=[
            "English",
            "Arabic",
            "Chinese",
            "French",
            "Russian",
            "Spanish",
            "Dutch",
            "German",
            "Hindi",
            "Indonesian",
            "Italian",
            "Japanese",
            "Korean",
            "Persian",
            "Polish",
            "Portuguese",
            "Turkish",
            "Ukrainian",
            "Vietnamese",
        ],
        index=0,
        label_visibility="collapsed",
        key="lang",
    )
    language_code_map = {
        "English": "en",
        "Arabic": "ar",
        "Chinese": "zh",
        "French": "fr",
        "Russian": "ru",
        "Spanish": "es",
        "Dutch": "nl",
        "German": "de",
        "Hindi": "hi",
        "Indonesian": "id",
        "Italian": "it",
        "Japanese": "ja",
        "Korean": "ko",
        "Persian": "fa",
        "Polish": "pl",
        "Portuguese": "pt",
        "Turkish": "tr",
        "Ukrainian": "uk",
        "Vietnamese": "vi",
    }
    selected_language = language_code_map.get(language_option)

# Global South: label+help line, then checkbox line
label_col, help_col = st.columns([1, 4])
with label_col:
    st.markdown("**Global South**")
with help_col:
    st.caption("If checked, only works with institutions from the Global South are included.")
gs_col1, gs_col2 = st.columns([1, 4])
with gs_col1:
    st.write("")
with gs_col2:
    filter_global_south = st.checkbox(
        "Global South",
        value=False,
        key="global_south_filter",
    )

# UN member states: label+help line, then control line
label_col, help_col = st.columns([1, 4])
with label_col:
    st.markdown("**UN member states**")
with help_col:
    st.caption("Filter results to works where at least one institution is from the selected UN member state (https://www.un.org/en/about-us/member-states). When this filter is not applied, results will include works from any country or institution worldwide.")
state_col1, state_col2 = st.columns([1, 4])
with state_col1:
    st.write("")
with state_col2:
    selected_member_state = st.selectbox(
        "",
        options=UN_MEMBER_STATES,
        index=None,
        placeholder="Select a UN member state",
        label_visibility="collapsed",
        key="un_member_state",
    )
    selected_member_state_code = UN_MEMBER_STATE_TO_COUNTRY_CODE.get(selected_member_state or "")

# Number of results: label line then control line
label_col, help_col = st.columns([1, 4])
with label_col:
    st.markdown("**Max Number / Type**")
with help_col:
    st.caption("Select how many results per publication type (max 5000 for the time being). More results take longer to load.")
nr_col1, nr_col2 = st.columns([1, 4])
with nr_col1:
    st.write("")
with nr_col2:
    num_results = st.slider("", 1, 5000, 500, label_visibility="collapsed", key="nr")

# Sort by: label+help line, then control line
label_col, help_col = st.columns([1, 4])
with label_col:
    st.markdown("**Sort by**")
with help_col:
    st.caption("Choose how to order the results: by relevance score, citation count, or publication date.")
sort_col1, sort_col2 = st.columns([1, 4])
with sort_col1:
    st.write("")
with sort_col2:
    sort_by = st.selectbox(
        "",
        options=["Relevance", "Citation count", "Date"],
        index=0,
        label_visibility="collapsed",
        key="sb",
    )

# Container for results (keeps results snug under the search area)
results_container = st.container()
# Container for analysis output (heatmap etc.)
analyze_container = st.container()

# Center the buttons under the controls
_, btn_col, _ = st.columns([1, 4, 1])
with btn_col:
    did_search = False
    did_analyze = False

    # Row 1: Search (1-1), Analyze (1-2), empty (1-3)
    r1c1, r1c2, r1c3 = st.columns([2, 2, 2])
    with r1c1:
        if st.button(
            "Search OpenAlex",
            key="main_search_button",
            type="primary",
            use_container_width=True,
        ):
            did_search = True
            result_payload = perform_search(
                keyword,
                year_range,
                num_results,
                work_types=work_types,
                language=selected_language,
                is_global_south=filter_global_south,
                institution_country_code=selected_member_state_code,
                container=results_container,
                display_limit=5,
                sort_by=sort_by,
            )
            st.session_state["last_payload"] = result_payload
            # Clear any cached analysis when a new search is run
            st.session_state.pop("last_analyze_triggered", None)
            st.session_state.pop("html_skipped_publications", None)
    with r1c2:
        if st.button(
            "Analyze Results",
            key="analyze_results_button",
            type="primary",
            use_container_width=True,
        ):
            payload = st.session_state.get("last_payload")
            if not payload:
                st.warning("Run a search first to analyze results.")
            else:
                did_analyze = True
                st.session_state["last_analyze_triggered"] = True
                perform_analyze(payload, year_range, container=analyze_container)
    with r1c3:
        if st.button(
            "Clear Results",
            key="clear_results_button",
            type="primary",
            use_container_width=True,
        ):
            st.session_state.pop("last_analyze_triggered", None)
            analyze_container.empty()
            st.rerun()

    payload = st.session_state.get("last_payload")
    payload_for_download = _payload_after_skips(payload)

    # Row 2: CSV (2-1), JSON (2-2), Neo4j placeholder (2-3)
    r2c1, r2c2, r2c3 = st.columns([2, 2, 2])
    with r2c1:
        if payload_for_download:
            st.download_button(
                "Download CSV",
                payload_for_download["csv"],
                "openalex_results.csv",
                "text/csv",
                key="download_csv_button",
                use_container_width=True,
            )
        else:
            st.download_button(
                "Download CSV",
                data=b"",
                file_name="openalex_results.csv",
                mime="text/csv",
                key="download_csv_button_disabled",
                disabled=True,
                use_container_width=True,
            )
    with r2c2:
        if payload_for_download:
            st.download_button(
                "Download JSON",
                payload_for_download["json"],
                "openalex_results.json",
                "application/json",
                key="download_json_button",
                use_container_width=True,
            )
        else:
            st.download_button(
                "Download JSON",
                data=b"",
                file_name="openalex_results.json",
                mime="application/json",
                key="download_json_button_disabled",
                disabled=True,
                use_container_width=True,
            )
    with r2c3:
        if payload_for_download:
            neo4j_cypher = build_neo4j_cypher(payload_for_download)
            st.download_button(
                "Download Neo4j",
                data=neo4j_cypher,
                file_name="openalex_results.cypher",
                mime="text/plain",
                key="download_neo4j_button",
                use_container_width=True,
            )
        else:
            st.download_button(
                "Download Neo4j",
                data=b"",
                file_name="openalex_results.cypher",
                mime="text/plain",
                key="download_neo4j_button_disabled",
                disabled=True,
                use_container_width=True,
            )

st.divider()
st.markdown("<h3 style='text-align:center'>Grey Literature Review & Export</h3>", unsafe_allow_html=True)

cached_payload = st.session_state.get("last_payload")
_, html_btn_wrap, _ = st.columns([1, 4, 1])
with html_btn_wrap:
    html_btn_col1, html_btn_col2, html_btn_col3 = st.columns([2, 2, 2])
    with html_btn_col1:
        if st.button("View HTML", key="view_html_button", type="primary", use_container_width=True):
            if cached_payload:
                st.session_state["show_html_preview"] = True
            else:
                st.warning("Run a search first to view HTML results.")
    with html_btn_col2:
        if st.button("Load CSV", key="load_csv_button", type="primary", use_container_width=True):
            st.warning("Load CSV is still under construction.")
    with html_btn_col3:
        st.write("")

# Topic filter control for HTML preview
html_records_all = []
html_topic_options = []
if cached_payload:
    try:
        html_records_all = json.loads(cached_payload.get("json") or "[]")
    except Exception:
        html_records_all = []

if isinstance(html_records_all, list) and html_records_all:
    skipped_ids = set(st.session_state.get("html_skipped_publications", []))

    if skipped_ids:
        html_records_all = [
            rec for rec in html_records_all
            if record_identifier(rec) not in skipped_ids
        ]

if isinstance(html_records_all, list) and html_records_all:
    topic_set = set()
    for rec in html_records_all:
        if not isinstance(rec, dict):
            continue
        topics_str = (rec.get("Topics") or "").strip()
        if not topics_str:
            continue
        for t in [x.strip() for x in topics_str.split(";") if x.strip()]:
            topic_set.add(t)
    html_topic_options = sorted(topic_set, key=str.lower)

label_col, help_col = st.columns([1, 4])
with label_col:
    st.markdown("**Filter Topic**")
with help_col:
    st.caption("Select one or more topics to filter the HTML preview results.")

flt_col1, flt_col2 = st.columns([1, 4])
with flt_col1:
    st.write("")
with flt_col2:
    def _on_select_all_topics_change():
        if st.session_state.get("html_topic_select_all"):
            st.session_state["html_topic_filter"] = html_topic_options.copy()
            st.session_state["html_topic_deselect_all"] = False

    def _on_deselect_all_topics_change():
        if st.session_state.get("html_topic_deselect_all"):
            st.session_state["html_topic_filter"] = []
            st.session_state["html_topic_select_all"] = False
            # Use as an action-like control; reset after applying
            st.session_state["html_topic_deselect_all"] = False

    def _on_topic_filter_change():
        selected_now = st.session_state.get("html_topic_filter", [])
        if st.session_state.get("html_topic_select_all") and len(selected_now) < len(html_topic_options):
            st.session_state["html_topic_select_all"] = False
        if selected_now:
            st.session_state["html_topic_deselect_all"] = False

    toggle_col1, toggle_col2 = st.columns(2)
    with toggle_col1:
        select_all_topics = st.checkbox(
            "Select all topics",
            value=False,
            key="html_topic_select_all",
            on_change=_on_select_all_topics_change,
        )
    with toggle_col2:
        st.checkbox(
            "Deselect all topics",
            value=False,
            key="html_topic_deselect_all",
            on_change=_on_deselect_all_topics_change,
        )

    selected_html_topics = st.multiselect(
        "",
        options=html_topic_options,
        key="html_topic_filter",
        label_visibility="collapsed",
        on_change=_on_topic_filter_change,
    )

html_container = st.container()
if st.session_state.get("show_html_preview") and cached_payload:
    payload_for_html = cached_payload
    if isinstance(html_records_all, list):
        if not selected_html_topics:
            payload_for_html = dict(cached_payload)
            payload_for_html["json"] = json.dumps([], ensure_ascii=False)
            html_container.caption("Filtered results: 0")
        else:
            selected_lc = {t.lower() for t in selected_html_topics}
            filtered_records = []
            for rec in html_records_all:
                if not isinstance(rec, dict):
                    continue
                topics_str = (rec.get("Topics") or "").strip()
                rec_topics = {x.strip().lower() for x in topics_str.split(";") if x.strip()}
                if rec_topics.intersection(selected_lc):
                    filtered_records.append(rec)

            payload_for_html = dict(cached_payload)
            payload_for_html["json"] = json.dumps(filtered_records, ensure_ascii=False)
            html_container.caption(f"Filtered results: {len(filtered_records)}")

    render_html_preview(payload_for_html, container=html_container, top_n=None)

# Re-render cached results on rerun (e.g., download click)
if cached_payload and not did_search:
    results_container.success(cached_payload.get("summary", "Results"))
    caption_text = cached_payload.get("caption")
    if caption_text:
        results_container.caption(caption_text)
    display_json = cached_payload.get("display_json")
    if display_json:
        json_container = results_container.container(height=420, border=True)
        json_container.code(display_json, language="json")

# Re-render cached analysis on rerun (e.g., download click)
if st.session_state.get("last_analyze_triggered") and cached_payload and not did_analyze:
    perform_analyze(cached_payload, year_range, container=analyze_container)

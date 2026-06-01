import streamlit as st
from pathlib import Path
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
import requests
from dotenv import load_dotenv
from typing import Any

from button_search import normalize_keyword_query, perform_search
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


load_dotenv()


st.markdown("""
<style>

/* Hide Streamlit footer ("Hosted with Streamlit") */
footer {
    visibility: hidden;
    display: none !important;
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


def render_text_document_page(doc_key: str) -> None:
    """Render a markdown document from assets based on the selected key."""
    docs = {
        "privacy": ("Privacy Policy", "Privacy Policy.txt"),
        "terms": ("Terms of Use", "Terms of Use.txt"),
    }

    doc_meta = docs.get(doc_key)
    if not doc_meta:
        st.error("Requested document was not found.")
        return

    doc_title, doc_filename = doc_meta
    doc_path = Path(__file__).parent / "assets" / doc_filename

    st.divider()
    st.markdown("## Climate Literature Navigator")

    if not doc_path.exists():
        st.error(f"Document file not found: assets/{doc_filename}")
        return

    doc_text = doc_path.read_text(encoding="utf-8").strip()
    if not doc_text:
        st.warning(f"Document is empty: assets/{doc_filename}")
    else:
        lines = doc_text.splitlines()
        if lines:
            first_line = lines[0].lstrip("# ").strip().strip("*")
            if first_line.lower() == doc_title.lower():
                doc_text = "\n".join(lines[1:]).lstrip()
        st.markdown(doc_text)

    st.markdown("[Back to Climate Literature Navigator](?doc=)")


def _get_query_param(param_name: str) -> str | None:
    """Return the requested query param, if any."""
    try:
        query_params = st.query_params
        value = query_params.get(param_name)
    except Exception:
        query_params = st.experimental_get_query_params()
        values = query_params.get(param_name)
        value = values[0] if isinstance(values, list) and values else values

    if isinstance(value, list):
        value = value[0] if value else None

    if value is None:
        return None

    value = str(value).strip()
    return value or None


def _run_keyword_search(
    keyword_value: str,
    year_range: tuple[int, int],
    num_results: int,
    work_types: list[str],
    language: str | None,
    language_label: str,
    is_global_south: bool,
    institution_country_code: str | None,
    member_state: str | None,
    container: Any,
    display_limit: int,
    sort_by: str,
    use_semantic_search: bool,
) -> dict | None:
    """Run a search, cache the payload, and log it when successful."""
    result_payload = perform_search(
        keyword_value,
        year_range,
        num_results,
        work_types=work_types,
        language=language,
        is_global_south=is_global_south,
        institution_country_code=institution_country_code,
        container=container,
        display_limit=display_limit,
        sort_by=sort_by,
        use_semantic_search=use_semantic_search,
    )
    st.session_state["last_payload"] = result_payload
    st.session_state.pop("last_analyze_triggered", None)
    st.session_state.pop("html_skipped_publications", None)

    if result_payload:
        try:
            log_ok, log_msg = _write_search_log_to_notion(
                keyword=keyword_value,
                year_range=year_range,
                work_types=work_types,
                language=language_label,
                member_state=member_state,
                max_number=num_results,
                returned_results=int(result_payload.get("total") or 0),
            )
        except Exception as exc:
            log_ok, log_msg = False, f"Failed to write search log to Notion: {exc}"
        if not log_ok:
            st.warning(log_msg)

    return result_payload


def _accept_keyword_correction(corrected_keyword: str) -> None:
    """Persist the corrected keyword into the textbox state."""
    st.session_state["kw"] = corrected_keyword
    st.session_state["keyword_search_decision"] = "apply"


def _keep_keyword_correction() -> None:
    """Keep the original keyword in the textbox state."""
    st.session_state["keyword_search_decision"] = "keep"


@st.dialog("Suggested keyword(s)")
def _keyword_correction_dialog(review: dict[str, str]) -> None:
    """Ask the user to confirm the auto-corrected keyword query."""
    st.write("Your keyword search was adjusted to follow Boolean search syntax.")
    st.markdown(f"**Original:** {review['original']}")
    st.markdown(f"**Suggested:** {review['corrected']}")
    if review.get("explanation"):
        st.info(review["explanation"])

    left_col, right_col = st.columns(2)
    with left_col:
        if st.button(
            "Use corrected query",
            key="keyword_correction_accept",
            type="primary",
            use_container_width=True,
        ):
            _accept_keyword_correction(review["corrected"])
            st.rerun()
    with right_col:
        if st.button(
            "Keep original query",
            key="keyword_correction_keep",
            use_container_width=True,
        ):
            _keep_keyword_correction()
            st.rerun()


def _write_feedback_to_notion(
    name: str,
    chapter: str,
    email: str,
    message: str,
    contact_ok: bool,
) -> tuple[bool, str]:
    token = os.getenv("NOTION_TOKEN")
    database_id = os.getenv("DATABASE_ID")
    if not token or not database_id:
        return False, "Notion credentials are missing in the environment."

    title_value = name.strip() or "Feedback"
    email_value = email.strip() if email.strip() else None
    cet_now = datetime.now(ZoneInfo("Europe/Paris")).isoformat()
    properties = {
        "Title": {"title": [{"text": {"content": title_value}}]},
        "App name": {"rich_text": [{"text": {"content": "Literature"}}]},
        "Name": {"rich_text": [{"text": {"content": name}}]},
        "Chapter": {"rich_text": [{"text": {"content": chapter}}]},
        "Email": {"email": email_value},
        "Question or Suggestion": {"rich_text": [{"text": {"content": message}}]},
        "Further Contact": {"rich_text": [{"text": {"content": "Yes" if contact_ok else "No"}}]},
        "Datetime": {"date": {"start": cet_now}},
    }

    ok, detail = _create_notion_page(
        token=token,
        database_id=database_id,
        properties=properties,
    )
    if not ok:
        return False, f"Failed to submit feedback to Notion. Response detail: {detail}"

    return True, "Thank you! Your feedback has been submitted."


def _create_notion_page(
    token: str,
    database_id: str,
    properties: dict,
) -> tuple[bool, object]:
    """Create a Notion page in the target database and return raw response detail on failure."""
    try:
        response = requests.post(
            "https://api.notion.com/v1/pages",
            headers={
                "Authorization": f"Bearer {token}",
                "Notion-Version": "2022-06-28",
                "Content-Type": "application/json",
            },
            json={
                "parent": {"database_id": database_id.strip()},
                "properties": properties,
            },
            timeout=20,
        )
    except requests.RequestException as exc:
        return False, f"Request error: {exc}"
    except Exception as exc:
        return False, f"Unexpected error: {exc}"

    if response.status_code >= 300:
        try:
            return False, response.json()
        except ValueError:
            return False, response.text

    return True, "ok"


def _write_search_log_to_notion(
    keyword: str,
    year_range: tuple[int, int],
    work_types: list[str],
    language: str,
    member_state: str | None,
    max_number: int,
    returned_results: int,
) -> tuple[bool, str]:
    """Write one search event to the literature Notion database."""
    token = os.getenv("NOTION_TOKEN")
    database_id = os.getenv("literature_database_id")
    if not token or not database_id:
        return False, "Notion search-log credentials are missing in the environment."

    keyword_clean = (keyword or "").strip()
    title_keyword = keyword_clean or "No keyword"
    title_keyword = title_keyword[:120]
    title_value = f"Search: {title_keyword}"

    publication_year_text = f"{year_range[0]}-{year_range[1]}"
    type_text = ", ".join(work_types) if work_types else "Any"
    language_text = language or "Any"
    member_state_text = member_state or "All"
    cet_now = datetime.now(ZoneInfo("Europe/Paris")).isoformat()

    properties = {
        "Name": {"title": [{"text": {"content": title_value}}]},
        "Keyword": {"rich_text": [{"text": {"content": keyword_clean}}]},
        "Publication year": {"rich_text": [{"text": {"content": publication_year_text}}]},
        "Type": {"rich_text": [{"text": {"content": type_text}}]},
        "Language": {"rich_text": [{"text": {"content": language_text}}]},
        "UN member states": {"rich_text": [{"text": {"content": member_state_text}}]},
        "Max Number": {"number": int(max_number)},
        "Returned results": {"number": int(returned_results)},
        "Datetime": {"date": {"start": cet_now}},
    }

    ok, detail = _create_notion_page(
        token=token,
        database_id=database_id,
        properties=properties,
    )
    if not ok:
        return False, f"Failed to write search log to Notion. Response detail: {detail}"

    return True, "Search log saved to Notion."


def render_feedback_page() -> None:
    st.divider()
    st.markdown("## Climate Literature Navigator")
    st.markdown("Any feedback is welcome! Please share your questions or suggestions below to help us improve the app. We will review all feedback carefully and get back to you if you indicate that we can contact you.")
    st.markdown("Please fill out the form below. Fields marked with * are required.")

    with st.form("feedback_form"):
        name = st.text_input("Name (optional)", value="")
        chapter = st.text_input("Chapter (optional)", value="")
        email = st.text_input("Email address (required if you want to be contacted)", value="")
        message = st.text_area("Question or suggestion *", value="", height=160)
        contact_ok = st.checkbox("I would like to be contacted about this inquiry", value=False)
        submitted = st.form_submit_button("Submit")

    if submitted:
        missing = [
            label
            for label, value in (
                ("Question or suggestion", message.strip()),
            )
            if not value
        ]
        if contact_ok and not email.strip():
            missing.append("Email address")
        email_value = email.strip()
        if email_value and "@" not in email_value:
            st.error("Please enter a valid email address.")
        elif missing:
            st.error(f"Please complete the required fields: {', '.join(missing)}.")
        else:
            ok, msg = _write_feedback_to_notion(
                name=name.strip(),
                chapter=chapter.strip(),
                email=email.strip(),
                message=message.strip(),
                contact_ok=contact_ok,
            )
            if ok:
                st.success(msg)
            else:
                st.error(msg)

    st.markdown("[Back to Climate Literature Navigator](?page=)")


page_key = _get_query_param("page")
if page_key == "feedback":
    render_feedback_page()
    st.stop()

# Render doc pages before the main UI.
doc_key = _get_query_param("doc")
if doc_key:
    render_text_document_page(doc_key)
    st.stop()

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

/* Center main content with 20% gutters and 60% content width */
section.main > div.block-container {
    padding-left: 20%;
    padding-right: 20%;
}

/* Primary button styling */
div.stButton > button[kind="primary"] {
    background-color: #1f77b4;
    color: #ffffff;
    border: 1px solid #1f77b4;
    min-height: 48px;
    padding: 0.5rem 1.25rem;
    white-space: nowrap;
    text-align: center;
    display: flex;
    justify-content: center;
    align-items: center;
}
div.stButton > button[kind="primary"]:hover {
    background-color: #166aa3;
    border-color: #166aa3;
}

div.stButton > button[kind="secondary"] {
    background-color: #a3a3a3;
    color: #ffffff;
    border: 1px solid #a3a3a3;
    min-height: 48px;
    padding: 0.5rem 1.25rem;
    white-space: nowrap;
    text-align: center;
    display: flex;
    justify-content: center;
    align-items: center;
}
div.stButton > button[kind="secondary"]:hover {
    background-color: #8a8a8a;
    border-color: #8a8a8a;
}

div.stButton > button[kind="primary"]:disabled {
    background-color: #a3a3a3;
    color: #ffffff;
    border-color: #a3a3a3;
    cursor: not-allowed;
}
/* Download button styling to match primary */
div.stDownloadButton > button {
    background-color: #1f77b4;
    color: #ffffff;
    border: 1px solid #1f77b4;
    min-height: 48px;
    padding: 0.5rem 1.25rem;
    white-space: nowrap;
    text-align: center;
    display: flex;
    justify-content: center;
    align-items: center;
}
div.stDownloadButton > button:hover {
    background-color: #166aa3;
    border-color: #166aa3;
}

div.stFormSubmitButton > button {
    text-align: center;
    display: flex;
    justify-content: center;
    align-items: center;
}

/* Show selected topics one per line without text overlap (topic filter only) */
div[data-testid="stMultiSelect"]:has(input[id*="html_topic_filter"]) [data-baseweb="tag"] {
    display: flex;
    align-items: center;
    width: 100%;
    max-width: 100% !important;
    min-height: 2rem;
    margin-right: 0;
}
div[data-testid="stMultiSelect"]:has(input[id*="html_topic_filter"]) [data-baseweb="tag"] > span {
    display: block;
    flex: 1 1 auto;
    min-width: 0;
    max-width: none !important;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    line-height: 1.2;
}

/* Keep emphasized terms in captions blue */
div[data-testid="stCaptionContainer"] strong {
    color: #00a9cf !important;
    font-weight: 700 !important;
    opacity: 1 !important;
}

/* Keep caption links in the same app cyan */
div[data-testid="stCaptionContainer"] a,
div[data-testid="stCaptionContainer"] a:link,
div[data-testid="stCaptionContainer"] a:visited,
div[data-testid="stCaptionContainer"] a:hover,
div[data-testid="stCaptionContainer"] a:active {
    color: #00a9cf !important;
    font-weight: 700 !important;
    text-decoration-thickness: 2px;
    opacity: 1 !important;
}
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-title"> Climate Literature Navigator </div>', unsafe_allow_html=True)
st.markdown(
    """
    <div style="
        background-color:#EAF4FF;
        border:1px solid #BBDFFF;
        border-radius:8px;
        padding:12px 14px;
        margin:8px 0 14px 0;
        text-align:center;
        font-weight:600;
        font-size:17px;
        color:#1F2D3D;
    ">
        ℹ️ Please first carefully read the information from the left sidebar before using the app.
    </div>
    """,
    unsafe_allow_html=True,
)
st.markdown("<h3 style='text-align:center'>Settings 🛠️</h3>", unsafe_allow_html=True)

# OpenAlex API control below title
label_col, input_col = st.columns([1, 4])
with label_col:
    st.markdown("**OpenAlex API**")
with input_col:
    openalex_api = st.text_input(
        "",
        value="",
        placeholder="Placeholder for a future version (currently not required for version 0.1a)",
        label_visibility="collapsed",
        key="openalex_api_input",
    )

# # OpenAI API control below OpenAlex API
# label_col, input_col = st.columns([1, 4])
# with label_col:
#     st.markdown("**OpenAI API**")
# with input_col:
#     openai_api = st.text_input(
#         "",
#         value="",
#         placeholder="Enter OpenAI API key",
#         label_visibility="collapsed",
#         key="openai_api_input",
#     )

# Sidebar


with st.sidebar:
    st.header("About")
    st.markdown(
        "<span style='color: #00a9cf; font-weight: bold;'>Climate Literature Navigator</span> (ver 0.1) "
        "is a web app developed by the <a href='https://www.ipcc.ch/working-group/wg2/'>IPCC WGII</a> TSU to help IPCC authors find climate-related literature from <a href='https://openalex.org'>OpenAlex</a>'s database. "
        "Please contact tsu@ipccwg2.org if you have any questions or suggestions.",
        unsafe_allow_html=True
    )
    # Sidebar keeps About and Disclaimer only; search controls moved to main page

    st.sidebar.markdown("### Disclaimer")
    st.sidebar.markdown(
        "Please carefully review the [Terms of Use](?doc=terms) and [Privacy Policy](?doc=privacy) before using this app. "
        "By using the app, you agree to the terms outlined in these documents."
    )

    st.sidebar.markdown(
        "<p>Please also note that the information provided by "
        "<span style='color: #00a9cf; font-weight: bold;'>Climate Literature Navigator</span> "
        " is fully sourced from <a href='https://openalex.org'>OpenAlex</a>. "
        "While we strive to ensure accuracy, we cannot guarantee the completeness or reliability of the data. "
        "Users should verify the information independently before making decisions based on it.</p>",
        unsafe_allow_html=True
    )

    st.sidebar.markdown("### User Guide")
    st.sidebar.markdown(
        "Please carefully read the [User Guide](https://xintian.notion.site/Climate-Literature-Navigator-User-guide-35a34913e84c805299cffccb92293cba)."
    )

    st.sidebar.markdown("### Give feedback")
    st.sidebar.markdown(
        "Please share your questions or suggestions using the "
        "[feedback form](?page=feedback)."
    )

    st.sidebar.markdown("### Other WGII TSU Apps")
    st.sidebar.markdown(
        "[WGII LLM App](https://wg2llm.streamlit.app/)"
    )

    st.sidebar.markdown("### To-do")
    st.sidebar.checkbox("General maintenance after LAM2 (v0.1b)", value=False, key="todo_auth_gs")
    st.sidebar.checkbox("Add multi-page tabs (v0.2)", value=False, key="todo_multi_page")
    st.sidebar.checkbox("Add more databases, e.g. Scopus, Overton, CORE, ReliefWeb (v0.3)", value=False, key="todo_search_sources")
    st.sidebar.checkbox("Add cloud-based features (v0.4)", value=False, key="todo_cloud")
    st.sidebar.checkbox("Performance improvements for larger result sets (v0.4)", value=False, key="todo_performance")
    st.sidebar.checkbox("General maintenance (v0.4)", value=False, key="todo_maintenance")
    st.sidebar.checkbox("User accounts and saved searches (v0.5)", value=False, key="todo_accounts")
    st.sidebar.checkbox("Add Load CSV functionality (v0.5)", value=False, key="todo_load_csv")
    st.sidebar.checkbox("Add semantic analysis (v0.6)", value=False, key="todo_analysis")
    st.sidebar.checkbox("Add knowledge graphs (v0.7)", value=False, key="todo_knowledge_graph")
    st.sidebar.checkbox("UI enhancements (v0.8)", value=False, key="todo_ui_enhancements")

    # logo_path = Path(__file__).parent / "assets" / "ipcc.png"
    # if logo_path.exists():
    #     st.sidebar.image(str(logo_path), width=200)
    # else:
    #     st.sidebar.caption("IPCC logo not found at assets/ipcc.png")

# Main search section (centered title and controls in one row)
st.divider()
st.markdown("<h3 style='text-align:center'>Literature searching 🔎</h3>", unsafe_allow_html=True)

# Keyword: label+help line, then control line
label_col, help_col = st.columns([1, 4])
with label_col:
    st.markdown("**Keyword**")
with help_col:
    st.caption(
        "Use Boolean operators to combine terms:  \n"
        "**AND**: requires all terms,  \n"
        "**OR**: allows either term,  \n"
        "**Parentheses**: group logic,  \n"
        "**Double quotes**: exact phrases,  \n"
        "**Notes**: Other operators are not supported at this moment. Please submit feedback using the feedback form if you need additional operators.  \n"
        "**Example**: \"climate change\" AND (water OR \"land use\") AND Bahamas.  \n"
        "**Reference**: [OpenAlex searching guide](https://developers.openalex.org/guides/searching)"
    )
kw_col1, kw_col2 = st.columns([1, 4])
with kw_col1:
    st.write("")
with kw_col2:
    keyword = st.text_input("", value="climate change", label_visibility="collapsed", key="kw")
    use_semantic_search = st.checkbox(
        "Semantic search",
        value=False,
        key="semantic_search",
        help="If checked, use semantic search (broader matching). If unchecked, use regular Boolean search (more precise matching). Reference: https://developers.openalex.org/guides/semantic-search",
    )

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
    year_range = st.slider("", 1900, 2027, (2000, 2025), label_visibility="collapsed", key="yr")

# Type: label+help line, then multiselect line
label_col, help_col = st.columns([1, 4])
with label_col:
    st.markdown("**Type**")
with help_col:
    st.caption(
        f"Due to processing time, you can select up to {MAX_WORK_TYPES} categories at one time. "
        "It will be improved in a future version to allow more categories."
    )
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
            "dataset",
            "dissertation",
            "editorial",
            "erratum",
            "letter",
            "libguides",
            "other",
            "paratext",
            "peer-review",
            "preprint",
            "reference-entry",
            "report",
            "retraction",
            "review",
            "standard",
            "supplementary-materials",
        ],
        default=["report"],
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
    st.caption("Filter results by language. Default is English. When selecting other languages, the keywords can be in the selected language or in English, which will give different results. We are working on a future version to allow more flexible combinations of languages and keywords.")
lang_col1, lang_col2 = st.columns([1, 4])
with lang_col1:
    st.write("")
with lang_col2:
    language_option = st.selectbox(
        "",
        options=[
            "Any",
            "English",
            "Arabic",
            "Chinese",
            "French",
            "Russian",
            "Spanish",
            # "Dutch",
            # "German",
            # "Hindi",
            # "Indonesian",
            # "Italian",
            # "Japanese",
            # "Korean",
            # "Persian",
            # "Polish",
            # "Portuguese",
            # "Turkish",
            # "Ukrainian",
            # "Vietnamese",
        ],
        index=1,
        label_visibility="collapsed",
        key="lang",
    )
    language_code_map = {
        "Any": None,
        "English": "en",
        "Arabic": "ar",
        "Chinese": "zh",
        "French": "fr",
        "Russian": "ru",
        "Spanish": "es",
        # "Dutch": "nl",
        # "German": "de",
        # "Hindi": "hi",
        # "Indonesian": "id",
        # "Italian": "it",
        # "Japanese": "ja",
        # "Korean": "ko",
        # "Persian": "fa",
        # "Polish": "pl",
        # "Portuguese": "pt",
        # "Turkish": "tr",
        # "Ukrainian": "uk",
        # "Vietnamese": "vi",
    }
    selected_language = language_code_map.get(language_option)

# Global South filter is not used for now.
# label_col, help_col = st.columns([1, 4])
# with label_col:
#     st.markdown("**Global South**")
# with help_col:
#     st.caption("If checked, only works with institutions from the Global South are included.")
# gs_col1, gs_col2 = st.columns([1, 4])
# with gs_col1:
#     st.write("")
# with gs_col2:
#     filter_global_south = st.checkbox(
#         "Global South",
#         value=False,
#         key="global_south_filter",
#     )
filter_global_south = False

# UN member states: label+help line, then control line
label_col, help_col = st.columns([1, 4])
with label_col:
    st.markdown("**UN member states**")
with help_col:
    st.caption(
        "Filter results to works where **at least one institution/affiliation of this publication is from the selected UN member state** "
        "([UN member states](https://www.un.org/en/about-us/member-states)). "
        "When this filter is not applied, results will include works from any state worldwide."
    )
state_col1, state_col2 = st.columns([1, 4])
with state_col1:
    st.write("")
with state_col2:
    selected_member_state = st.selectbox(
        "",
        options=UN_MEMBER_STATES,
        index=None,
        placeholder="You can leave this field empty to include works from all states.",
        label_visibility="collapsed",
        key="un_member_state",
    )
    selected_member_state_code = UN_MEMBER_STATE_TO_COUNTRY_CODE.get(selected_member_state or "")

# Number of results: label line then control line
label_col, help_col = st.columns([1, 4])
with label_col:
    st.markdown("**Max Number**")
with help_col:
    st.caption("Select the maximum number of results to return (max 5000 for the time being). More results take longer to load.")
nr_col1, nr_col2 = st.columns([1, 4])
with nr_col1:
    st.write("")
with nr_col2:
    num_results = st.slider("", 1, 5000, 500, label_visibility="collapsed", key="nr")

sort_by = st.session_state.get("sb", "Relevance")

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
            normalized_keyword, needs_review, explanation = normalize_keyword_query(keyword)
            if needs_review and not use_semantic_search:
                st.session_state["keyword_search_request"] = {
                    "keyword": keyword,
                    "year_range": year_range,
                    "num_results": num_results,
                    "work_types": work_types,
                    "language": selected_language,
                    "language_label": language_option,
                    "is_global_south": filter_global_south,
                    "institution_country_code": selected_member_state_code,
                    "member_state": selected_member_state,
                    "display_limit": 5,
                    "sort_by": sort_by,
                    "use_semantic_search": use_semantic_search,
                }
                st.session_state["keyword_search_review"] = {
                    "original": keyword,
                    "corrected": normalized_keyword,
                    "explanation": explanation,
                }
                st.session_state.pop("keyword_search_decision", None)
            else:
                did_search = True
                st.session_state.pop("keyword_search_request", None)
                st.session_state.pop("keyword_search_review", None)
                st.session_state.pop("keyword_search_decision", None)
                _run_keyword_search(
                    normalized_keyword,
                    year_range,
                    num_results,
                    work_types,
                    selected_language,
                    language_option,
                    filter_global_south,
                    selected_member_state_code,
                    selected_member_state,
                    results_container,
                    5,
                    sort_by,
                    use_semantic_search,
                )
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

    pending_review = st.session_state.get("keyword_search_review")
    pending_request = st.session_state.get("keyword_search_request")
    pending_decision = st.session_state.get("keyword_search_decision")

    if pending_review and not pending_decision:
        _keyword_correction_dialog(pending_review)

    if pending_request and pending_decision:
        request_keyword = pending_request.get("keyword", "")
        if pending_decision == "apply":
            # Use the same value shown in the keyword textbox after approval.
            request_keyword = st.session_state.get("kw", request_keyword)

        did_search = True
        _run_keyword_search(
            request_keyword,
            pending_request.get("year_range", year_range),
            pending_request.get("num_results", num_results),
            pending_request.get("work_types", work_types),
            pending_request.get("language", selected_language),
            pending_request.get("language_label", language_option),
            pending_request.get("is_global_south", filter_global_south),
            pending_request.get("institution_country_code", selected_member_state_code),
            pending_request.get("member_state", selected_member_state),
            results_container,
            pending_request.get("display_limit", 5),
            pending_request.get("sort_by", sort_by),
            pending_request.get("use_semantic_search", use_semantic_search),
        )
        st.session_state.pop("keyword_search_request", None)
        st.session_state.pop("keyword_search_review", None)
        st.session_state.pop("keyword_search_decision", None)

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
st.markdown("<h3 style='text-align:center'>Literature Review & Export 📑</h3>", unsafe_allow_html=True)

label_col, help_col = st.columns([1, 4])
with label_col:
    st.markdown("**Filter Topic**")
with help_col:
    st.caption("Select one or more topics to display relevant publications.")

cached_payload = st.session_state.get("last_payload")
NO_GENERATED_TOPICS_LABEL = "No Generated Topics"

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
    has_no_generated_topics = False
    for rec in html_records_all:
        if not isinstance(rec, dict):
            continue
        topics_str = (rec.get("Topics") or "").strip()
        if not topics_str:
            has_no_generated_topics = True
            continue
        for t in [x.strip() for x in topics_str.split(";") if x.strip()]:
            topic_set.add(t)
    html_topic_options = sorted(topic_set, key=str.lower)
    if has_no_generated_topics:
        html_topic_options.append(NO_GENERATED_TOPICS_LABEL)

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

label_col, help_col = st.columns([1, 4])
with label_col:
    st.markdown("**Sort by**")
with help_col:
    st.caption("Choose how to order the results: by relevance score, citation count, or publication date.")
sort_col1, sort_col2 = st.columns([1, 4])
with sort_col1:
    st.write("")
with sort_col2:
    current_sort = st.session_state.get("sb", "Relevance")
    sort_options = ["Relevance", "Citation count", "Date"]
    sort_index = sort_options.index(current_sort) if current_sort in sort_options else 0
    st.selectbox(
        "",
        options=sort_options,
        index=sort_index,
        label_visibility="collapsed",
        key="sb",
    )

_, html_btn_wrap, _ = st.columns([1, 4, 1])
with html_btn_wrap:
    html_btn_col1, html_btn_col2, html_btn_col3 = st.columns([2, 2, 2])
    with html_btn_col1:
        if st.button("Read Publications", key="view_html_button", type="primary", use_container_width=True):
            if cached_payload:
                st.session_state["show_html_preview"] = True
            else:
                st.warning("Run a search first to view HTML results.")
    with html_btn_col2:
        if st.button("Load CSV", key="load_csv_button", type="secondary", use_container_width=True):
            st.warning("Load CSV is still under construction.")
    with html_btn_col3:
        st.write("")

html_container = st.container()
if st.session_state.get("show_html_preview") and cached_payload:
    payload_for_html = cached_payload
    if isinstance(html_records_all, list):
        if not selected_html_topics:
            payload_for_html = dict(cached_payload)
            payload_for_html["json"] = json.dumps([], ensure_ascii=False)
            html_container.caption("Filtered results: 0")
        else:
            include_no_generated_topics = NO_GENERATED_TOPICS_LABEL in selected_html_topics
            selected_lc = {
                t.lower() for t in selected_html_topics
                if t != NO_GENERATED_TOPICS_LABEL
            }
            filtered_records = []
            for rec in html_records_all:
                if not isinstance(rec, dict):
                    continue
                topics_str = (rec.get("Topics") or "").strip()
                rec_topics = {x.strip().lower() for x in topics_str.split(";") if x.strip()}
                if rec_topics.intersection(selected_lc) or (include_no_generated_topics and not rec_topics):
                    filtered_records.append(rec)

            payload_for_html = dict(cached_payload)
            payload_for_html["json"] = json.dumps(filtered_records, ensure_ascii=False)
            html_container.caption(f"Filtered results: {len(filtered_records)}")

    render_html_preview(payload_for_html, container=html_container, top_n=None)

# Re-render cached results on rerun (e.g., download click)
if cached_payload and not did_search:
    results_container.success(cached_payload.get("summary", "Results"))
    # No caption or JSON preview for results.

# Re-render cached analysis on rerun (e.g., download click)
if st.session_state.get("last_analyze_triggered") and cached_payload and not did_analyze:
    perform_analyze(cached_payload, year_range, container=analyze_container)

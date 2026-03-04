import json
from typing import Any

import pandas as pd
import streamlit as st
from pyalex import Works
from pyalex.api import QueryError

from utils import OPENALEX_PAGE_SIZE, DISPLAY_CONTAINER_HEIGHT


def get_work_topics(work: dict[str, Any]) -> str:
    """Extract topic display names from an OpenAlex work.

    Uses both `primary_topic` and `topics` (if present), de-duplicated in order.
    """
    names = []

    primary_topic = work.get("primary_topic") or {}
    if isinstance(primary_topic, dict):
        primary_name = primary_topic.get("display_name")
        if primary_name:
            names.append(primary_name)

    topics = work.get("topics") or []
    if isinstance(topics, list):
        for t in topics:
            if not isinstance(t, dict):
                continue
            t_name = t.get("display_name")
            if t_name:
                names.append(t_name)

    # de-duplicate while preserving order
    deduped = []
    seen = set()
    for n in names:
        if n in seen:
            continue
        seen.add(n)
        deduped.append(n)

    return "; ".join(deduped)


def perform_search(
    keyword: str,
    year_range: tuple[int, int],
    num_results: int,
    work_types: list[str] | None = None,
    language: str | None = None,
    is_global_south: bool = False,
    institution_country_code: str | None = None,
    container: Any = None,
    display_limit: int = 5,
    sort_by: str = "Relevance",
) -> dict[str, Any] | None:
    """Perform a search against OpenAlex and render results.

    This function assumes a Search button in `app.py` calls it; it does not create its own button.
    """
    # Basic validation
    if not keyword or not keyword.strip():
        st.warning("Please enter a keyword for the search.")
        return

    if not year_range or len(year_range) != 2:
        st.warning("Please select a valid publication year range.")
        return

    start_year, end_year = year_range

    try:
        # Use provided container for rendering results to avoid extra spacing
        display = container if container is not None else st

        # clear previous results in the container if possible
        if container is not None:
            container.empty()

        # Prepare keywords list (split on ';')
        keywords_list = [k.strip() for k in keyword.split(";") if k.strip()]
        if not keywords_list:
            st.warning("Please enter at least one keyword.")
            return

        with st.spinner("Searching..."):
            # Build filter kwargs (avoid passing multi-value `type` to API)
            filter_kwargs = {
                "from_publication_date": f"{start_year}-01-01",
                "to_publication_date": f"{end_year}-12-31",
            }
            if language:
                filter_kwargs["language"] = language
            if institution_country_code:
                filter_kwargs["institutions.country_code"] = institution_country_code

            def _build_base_query() -> Any:
                query = Works().search(combined_query).filter(**filter_kwargs)
                if is_global_south:
                    query = query.filter(institutions={"is_global_south": True})
                return query

            all_results = []

            def _format_keyword(kw):
                return f'"{kw}"' if " " in kw else kw

            combined_query = " AND ".join(_format_keyword(kw) for kw in keywords_list)
            requested_n = max(int(num_results), 1)
            openalex_total = 0

            def _fetch_paginated(query: Any, limit: int) -> list[dict[str, Any]]:
                """Fetch up to `limit` records across multiple OpenAlex pages."""
                page_size = OPENALEX_PAGE_SIZE
                page = 1
                collected = []
                while len(collected) < limit:
                    batch = query.get(per_page=page_size, page=page)
                    if not batch:
                        break
                    collected.extend(batch)
                    if len(batch) < page_size:
                        break
                    page += 1
                return collected[:limit]

            # Map UI sort option to OpenAlex sort kwargs
            _sort_map = {
                "Relevance": {"relevance_score": "desc"},
                "Citation count": {"cited_by_count": "desc"},
                "Date": {"publication_date": "desc"},
            }
            sort_kwargs = _sort_map.get(sort_by, {"relevance_score": "desc"})

            if work_types:
                # Collect results per type and enforce num_results per type
                types_to_query = work_types[:3]
                for t in types_to_query:
                    per_type_results = []
                    try:
                        type_query = _build_base_query().filter(type=t)
                        try:
                            openalex_total += int(type_query.count() or 0)
                        except Exception:
                            pass
                        per_type_results = _fetch_paginated(
                            type_query.sort(**sort_kwargs),
                            requested_n,
                        )
                    except Exception:
                        per_type_results = []

                    # Deduplicate within type and trim to num_results
                    seen = set()
                    deduped_type = []
                    for r in per_type_results:
                        rid = r.get("id") if isinstance(r, dict) else None
                        if not rid:
                            rid = (r.get("ids") or {}).get("openalex") if isinstance(r, dict) else None
                        if not rid or rid in seen:
                            continue
                        seen.add(rid)
                        deduped_type.append(r)
                        if len(deduped_type) >= int(num_results):
                            break

                    all_results.extend(deduped_type)

            else:
                # No type filter: aggregate across keywords and trim to total
                try:
                    base_query = _build_base_query()
                    try:
                        openalex_total = int(base_query.count() or 0)
                    except Exception:
                        openalex_total = 0
                    all_results = _fetch_paginated(
                        base_query.sort(**sort_kwargs),
                        requested_n,
                    )
                except Exception:
                    all_results = []

                # Deduplicate overall and trim to requested total
                seen = set()
                unique_results = []
                for r in all_results:
                    rid = r.get("id") if isinstance(r, dict) else None
                    if not rid:
                        rid = (r.get("ids") or {}).get("openalex") if isinstance(r, dict) else None
                    if not rid or rid in seen:
                        continue
                    seen.add(rid)
                    unique_results.append(r)
                    if len(unique_results) >= int(num_results):
                        break

                all_results = unique_results

            results = all_results

    except QueryError as e:
        st.error(f"Search failed: {e}")
        return
    except Exception as e:
        st.error(f"Unexpected error during search: {e}")
        return

    if not results:
        display.warning("No results found")
        return None

    records = []
    for work in results:
        openalex_id = work.get("id")
        title = work.get("title")
        pub_date = work.get("publication_date")
        pub_year = work.get("publication_year")
        cited = work.get("cited_by_count")
        doi = work.get("doi")
        work_type = work.get("type")
        relevance_score = work.get("relevance_score")
        if relevance_score is None:
            relevance_score = work.get("_score")

        # Safely extract nested fields; some entries may have None instead of dict
        primary_loc = work.get("primary_location") or {}
        if not isinstance(primary_loc, dict):
            primary_loc = {}
        source_obj = primary_loc.get("source") or {}
        if not isinstance(source_obj, dict):
            source_obj = {}
        source = source_obj.get("display_name") or ""

        openalex_link = f'<a href="{openalex_id}" target="_blank">View</a>' if openalex_id else ""

        landing_url = primary_loc.get("landing_page_url") or ""
        oa_info = work.get("open_access") or {}
        if not isinstance(oa_info, dict):
            oa_info = {}
        oa_status = oa_info.get("oa_status") or ""
        is_oa = oa_info.get("is_oa")
        oa_flag = "Yes" if is_oa is True else "No" if is_oa is False else ""

        # Authors (limit to first 5 for readability)
        authorships = work.get("authorships") or []
        author_names = []
        if isinstance(authorships, list):
            for auth in authorships[:5]:
                name = (
                    (auth or {}).get("author", {}) or {}
                ).get("display_name")
                if name:
                    author_names.append(name)
        authors_display = ", ".join(author_names)

        # Abstract (OpenAlex uses inverted index; reconstruct if present)
        abstract_text = ""
        inverted = work.get("abstract_inverted_index")
        if isinstance(inverted, dict) and inverted:
            positions = []
            for word, idxs in inverted.items():
                for i in idxs:
                    positions.append((i, word))
            if positions:
                abstract_text = " ".join(word for _, word in sorted(positions))

        publisher = source_obj.get("publisher") or ""

        # Keywords
        kw_list = work.get("keywords") or []
        keywords_display = "; ".join(
            kw.get("display_name", "") for kw in kw_list if isinstance(kw, dict) and kw.get("display_name")
        )
        topics_display = get_work_topics(work)

        records.append({
            "OpenAlex": openalex_link,
            "OpenAlex URL": openalex_id,
            "Title": title,
            "Publication Date": pub_date,
            "Publication Year": pub_year,
            "Journal": source,
            "Type": work_type,
            "Authors": authors_display,
            "Open Access": oa_flag,
            "OA Status": oa_status,
            "Citations": cited,
            "DOI": doi,
            "Relevance Score": relevance_score,
            "Keywords": keywords_display,
            "Topics": topics_display,
            # CSV-only fields
            "Abstract": abstract_text,
            "Publisher": publisher,
            "URL": landing_url,
        })

    df = pd.DataFrame(records)

    # Display table (omit Language/URL and CSV-only columns)
    display_columns = [
        "OpenAlex",
        "Title",
        "Publication Date",
        "Publication Year",
        "Journal",
        "Type",
        "Authors",
        "Open Access",
        "OA Status",
        "Citations",
        "DOI",
        "Relevance Score",
        "Keywords",
        "Topics",
    ]
    df_display = df[[c for c in display_columns if c in df.columns]].copy()
    df_display = df_display.head(int(display_limit))

    # remove duplicates using raw ID
    try:
        df["raw_id"] = [r.get("id") for r in results]
        df = df.drop_duplicates(subset="raw_id").drop(columns="raw_id")
    except Exception:
        # If results structure differs, skip dedupe step
        pass

    openalex_total_text = str(openalex_total) if openalex_total else "an unknown number of"
    summary_text = (
        f"OpenAlex reports about {openalex_total_text} matches. "
        f"Returned {len(df)} unique results."
    )
    caption_text = (
        f"Showing the first {len(df_display)} results on screen. "
        "Download the CSV or JSON to view all returned results."
    )
    display_json = json.dumps(
        df_display.to_dict(orient="records"),
        indent=2,
        ensure_ascii=False,
    )

    display.success(summary_text)
    display.caption(caption_text)

    # Present results in the provided container as JSON-like output with scroll
    json_container = display.container(height=DISPLAY_CONTAINER_HEIGHT, border=True)
    json_container.code(display_json, language="json")

    csv = df.to_csv(index=False).encode("utf-8")
    json_full = json.dumps(
        df.to_dict(orient="records"),
        indent=2,
        ensure_ascii=False,
    ).encode("utf-8")
    return {
        "csv": csv,
        "json": json_full,
        "total": len(df),
        "openalex_total": openalex_total,
        "shown": len(df_display),
        "summary": summary_text,
        "caption": caption_text,
        "display_json": display_json,
    }

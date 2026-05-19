import json
import re
from typing import Any

import pandas as pd
import requests
import streamlit as st

from utils import OPENALEX_PAGE_SIZE, DISPLAY_CONTAINER_HEIGHT, MAX_WORK_TYPES


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


def _build_work_text_blob(work: dict[str, Any]) -> str:
    """Build a lowercase text blob from key searchable fields."""
    title = str(work.get("title") or "")

    # Reconstruct abstract text from OpenAlex inverted index.
    abstract_text = ""
    inverted = work.get("abstract_inverted_index")
    if isinstance(inverted, dict) and inverted:
        try:
            max_pos = max((max(pos) for pos in inverted.values() if pos), default=-1)
            if max_pos >= 0:
                tokens = [""] * (max_pos + 1)
                for word, positions in inverted.items():
                    if not isinstance(positions, list):
                        continue
                    for p in positions:
                        if isinstance(p, int) and 0 <= p < len(tokens):
                            tokens[p] = str(word)
                abstract_text = " ".join(tok for tok in tokens if tok)
        except Exception:
            abstract_text = ""

    keywords_text = " ".join(
        str(k.get("display_name") or "")
        for k in (work.get("keywords") or [])
        if isinstance(k, dict)
    )

    topics_text = " ".join(
        str(t.get("display_name") or "")
        for t in (work.get("topics") or [])
        if isinstance(t, dict)
    )

    return " ".join([title, abstract_text, keywords_text, topics_text]).lower()


def _matches_all_keywords(work: dict[str, Any], keywords_list: list[str]) -> bool:
    """Return True only if all keyword phrases are present (AND semantics)."""
    blob = _build_work_text_blob(work)
    return all(kw.lower() in blob for kw in keywords_list)


def _tokenize_boolean_query(query: str) -> list[str]:
    """Tokenize a boolean expression supporting quotes, AND/OR, and parentheses."""
    pattern = r'"[^"\\]*(?:\\.[^"\\]*)*"|\(|\)|\bAND\b|\bOR\b|[^\s()]+'
    return [t for t in re.findall(pattern, query, flags=re.IGNORECASE) if t.strip()]


def _normalize_term(token: str) -> str:
    token = token.strip()
    if len(token) >= 2 and token[0] == '"' and token[-1] == '"':
        return token[1:-1].strip().lower()
    return token.lower()


def _insert_implicit_and(tokens: list[str]) -> list[str]:
    """Insert implicit AND between adjacent operands/parentheses."""
    if not tokens:
        return tokens

    out: list[str] = []

    def _is_operand(tok: str) -> bool:
        upper = tok.upper()
        return tok not in ("(", ")") and upper not in ("AND", "OR")

    for i, tok in enumerate(tokens):
        if i > 0:
            prev = tokens[i - 1]
            if (
                (_is_operand(prev) or prev == ")")
                and (_is_operand(tok) or tok == "(")
            ):
                out.append("AND")
        out.append(tok)

    return out


def _to_rpn(tokens: list[str]) -> list[str]:
    """Convert infix boolean tokens to RPN using shunting-yard."""
    precedence = {"OR": 1, "AND": 2}
    output: list[str] = []
    operators: list[str] = []

    for tok in tokens:
        upper = tok.upper()
        if tok == "(":
            operators.append(tok)
        elif tok == ")":
            while operators and operators[-1] != "(":
                output.append(operators.pop())
            if not operators or operators[-1] != "(":
                raise ValueError("Mismatched parentheses in keyword expression.")
            operators.pop()
        elif upper in ("AND", "OR"):
            while (
                operators
                and operators[-1] in precedence
                and precedence[operators[-1]] >= precedence[upper]
            ):
                output.append(operators.pop())
            operators.append(upper)
        else:
            output.append(_normalize_term(tok))

    while operators:
        op = operators.pop()
        if op in ("(", ")"):
            raise ValueError("Mismatched parentheses in keyword expression.")
        output.append(op)

    return output


def _extract_literals(tokens: list[str]) -> list[str]:
    literals: list[str] = []
    seen: set[str] = set()
    for tok in tokens:
        upper = tok.upper()
        if tok in ("(", ")") or upper in ("AND", "OR"):
            continue
        lit = _normalize_term(tok)
        if not lit or lit in seen:
            continue
        seen.add(lit)
        literals.append(lit)
    return literals


def _evaluate_rpn_expression(work: dict[str, Any], rpn: list[str]) -> bool:
    """Evaluate parsed boolean expression against a work text blob."""
    blob = _build_work_text_blob(work)
    stack: list[bool] = []

    for tok in rpn:
        if tok in ("AND", "OR"):
            if len(stack) < 2:
                raise ValueError("Invalid keyword expression.")
            right = stack.pop()
            left = stack.pop()
            stack.append(left and right if tok == "AND" else left or right)
        else:
            stack.append(tok in blob)

    if len(stack) != 1:
        raise ValueError("Invalid keyword expression.")
    return stack[0]


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
    use_semantic_search: bool = False,
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

        keyword_expr = keyword.strip()
        if not keyword_expr:
            st.warning("Please enter at least one keyword.")
            return

        with st.spinner("Searching..."):
            # Align with OpenAlex UI behavior by querying title+abstract directly.
            search_field = "semantic.search" if use_semantic_search else "title_and_abstract.search"
            filter_parts = [
                f"{search_field}:{keyword_expr}",
                f"from_publication_date:{start_year}-01-01",
                f"to_publication_date:{end_year}-12-31",
            ]
            if language:
                filter_parts.append(f"language:{language}")
            if institution_country_code:
                filter_parts.append(f"institutions.country_code:{institution_country_code}")
            if is_global_south:
                filter_parts.append("institutions.is_global_south:true")
            if work_types:
                types_to_query = work_types[:MAX_WORK_TYPES]
                filter_parts.append(f"type:{'|'.join(types_to_query)}")

            base_params: dict[str, Any] = {
                "filter": ",".join(filter_parts),
            }

            requested_n = max(int(num_results), 1)
            openalex_total = 0

            def _fetch_paginated(params: dict[str, Any], limit: int) -> list[dict[str, Any]]:
                """Fetch up to `limit` records across multiple OpenAlex pages."""
                page_size = min(OPENALEX_PAGE_SIZE, 100)
                page = 1
                collected: list[dict[str, Any]] = []
                while len(collected) < limit:
                    response = requests.get(
                        "https://api.openalex.org/works",
                        params={**params, "per_page": page_size, "page": page},
                        timeout=30,
                    )
                    response.raise_for_status()
                    batch = (response.json() or {}).get("results") or []
                    if not batch:
                        break
                    collected.extend(batch)
                    if len(batch) < page_size:
                        break
                    page += 1
                return collected[:limit]

            # Map UI sort option to OpenAlex sort kwargs
            _sort_map = {
                "Relevance": None,
                "Citation count": {"cited_by_count": "desc"},
                "Date": {"publication_date": "desc"},
            }
            sort_kwargs = _sort_map.get(sort_by, None)

            def _apply_sort(params: dict[str, Any]) -> dict[str, Any]:
                new_params = dict(params)
                if not sort_kwargs:
                    return new_params
                sort_field, sort_dir = next(iter(sort_kwargs.items()))
                new_params["sort"] = f"{sort_field}:{sort_dir}"
                return new_params

            query_params = _apply_sort(base_params)

            try:
                try:
                    count_response = requests.get(
                        "https://api.openalex.org/works",
                        params={**query_params, "per_page": 1},
                        timeout=30,
                    )
                    count_response.raise_for_status()
                    openalex_total = int((count_response.json() or {}).get("meta", {}).get("count") or 0)
                except Exception:
                    openalex_total = 0
                all_results = _fetch_paginated(
                    query_params,
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
        f"OpenAlex reports {openalex_total_text} matches. "
        f"Returned {len(df)} unique results. Json & CSV are available for download."
    )
    display.success(summary_text)

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
    }

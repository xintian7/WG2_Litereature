import json
import math
from collections import Counter
from itertools import combinations
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

nx = None

try:
    from wordcloud import WordCloud
except Exception:
    WordCloud = None


def perform_analyze(
    payload: dict[str, Any] | None,
    year_range: tuple[int, int],
    container: Any = None,
) -> None:
    """Render publication/year analytics and a top-keyword frequency heatmap.

    Parameters
    ----------
    payload : dict
        The result payload returned by ``perform_search``.
    year_range : tuple[int, int]
        The (start_year, end_year) selected in the year slider.
    container : streamlit container, optional
        Where to render the chart.  Falls back to ``st`` if not provided.
    """
    display = container if container is not None else st

    if not payload:
        display.warning("No search results to analyze. Please run a search first.")
        return

    # ---- Load records -------------------------------------------------------
    try:
        records = json.loads(payload["json"])
    except Exception as e:
        display.error(f"Failed to parse search results: {e}")
        return

    if not records:
        display.warning("No records found in the search results.")
        return

    start_year, end_year = year_range
    all_years = list(range(start_year, end_year + 1))
    year_labels = [str(y) for y in all_years]

    # ---- Figure 1: stacked counts per year by type + cumulative curve -------
    pub_rows = []
    for rec in records:
        year = rec.get("Publication Year")
        work_type = (rec.get("Type") or "Unknown").strip() or "Unknown"
        try:
            year = int(year)
        except (ValueError, TypeError):
            continue
        if start_year <= year <= end_year:
            pub_rows.append({"year": year, "type": work_type})

    if pub_rows:
        df_pub = pd.DataFrame(pub_rows)

        # Sort types by total frequency (descending) for a stable legend order
        type_order = (
            df_pub["type"].value_counts().index.tolist()
            if not df_pub.empty else []
        )

        fig_pub = go.Figure()
        for t in type_order:
            y_counts = (
                df_pub[df_pub["type"] == t]
                .groupby("year")
                .size()
                .reindex(all_years, fill_value=0)
            )
            fig_pub.add_trace(
                go.Bar(
                    x=year_labels,
                    y=y_counts.values,
                    name=t,
                    hovertemplate=(
                        "Type: <b>%{fullData.name}</b><br>"
                        "Year: %{x}<br>"
                        "Count: %{y}<extra></extra>"
                    ),
                )
            )

        yearly_totals = (
            df_pub.groupby("year")
            .size()
            .reindex(all_years, fill_value=0)
        )
        cumulative_totals = yearly_totals.cumsum()
        tickvals = [str(y) for i, y in enumerate(all_years) if i % 2 == 0]

        fig_pub.add_trace(
            go.Scatter(
                x=year_labels,
                y=cumulative_totals.values,
                mode="lines+markers",
                name="Cumulative",
                line=dict(color="#d67c27", width=2.5),
                marker=dict(size=5),
                yaxis="y2",
                hovertemplate=(
                    "Year: %{x}<br>"
                    "Cumulative: %{y}<extra></extra>"
                ),
            )
        )

        fig_pub.update_layout(
            title=dict(
                text="Publications by Year (Stacked by Type) + Cumulative Trend",
                x=0.5,
                xanchor="center",
                font=dict(size=16),
            ),
            barmode="stack",
            xaxis=dict(
                title="Publication Year",
                type="category",
                tickmode="array",
                tickvals=tickvals,
                tickangle=-45,
                tickfont=dict(size=11),
            ),
            yaxis=dict(
                title="Publications per Year",
                tickfont=dict(size=11),
            ),
            yaxis2=dict(
                title="Cumulative Publications",
                overlaying="y",
                side="right",
                showgrid=False,
            ),
            legend=dict(
                orientation="v",
                yanchor="top",
                y=1,
                xanchor="left",
                x=1.01,
                font=dict(size=10),
            ),
            height=600,
            margin=dict(l=80, r=190, t=80, b=90),
            paper_bgcolor="white",
            plot_bgcolor="white",
        )

        display.plotly_chart(fig_pub, use_container_width=True)
    else:
        display.warning("No valid publication year/type data found to build the yearly chart.")

    def _render_term_heatmap(term_field, term_label, panel_title):
        """Render a keyword/topic heatmap with marginal yearly publication totals."""
        rows = []
        for rec in records:
            year = rec.get("Publication Year")
            term_str = (rec.get(term_field) or "").strip()
            if not term_str or year is None:
                continue
            try:
                year = int(year)
            except (ValueError, TypeError):
                continue
            if not (start_year <= year <= end_year):
                continue
            for term in [k.strip() for k in term_str.split(";") if k.strip()]:
                rows.append({"year": year, "term": term})

        if not rows:
            display.warning(f"No {term_label.lower()} found in the results.")
            return

        df = pd.DataFrame(rows)
        top10 = df["term"].value_counts().head(10).index.tolist()
        if not top10:
            display.warning(f"Not enough {term_label.lower()} data to build a heatmap.")
            return

        df_top = df[df["term"].isin(top10)]
        pivot = (
            df_top.groupby(["term", "year"])
            .size()
            .unstack(fill_value=0)
            .reindex(index=top10, columns=all_years, fill_value=0)
        )

        active_years = [y for y in all_years if pivot[y].sum() > 0]
        if active_years:
            pivot = pivot[active_years]
        else:
            active_years = all_years

        local_year_labels = [str(y) for y in active_years]

        pub_year_rows = []
        for rec in records:
            y = rec.get("Publication Year")
            try:
                y = int(y)
            except (ValueError, TypeError):
                continue
            if start_year <= y <= end_year:
                pub_year_rows.append(y)

        pub_year_counts = (
            pd.Series(pub_year_rows)
            .value_counts()
            .reindex(active_years, fill_value=0)
            .sort_index()
        ) if pub_year_rows else pd.Series(index=active_years, dtype=int)

        fig = make_subplots(
            rows=2,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.03,
            row_heights=[0.18, 0.82],
        )

        fig.add_trace(
            go.Bar(
                x=local_year_labels,
                y=pub_year_counts.values.tolist(),
                name="Total publications",
                marker_color="#6baed6",
                hovertemplate="Year: %{x}<br>Total publications: %{y}<extra></extra>",
            ),
            row=1,
            col=1,
        )

        fig.add_trace(
            go.Heatmap(
                z=pivot.values.tolist(),
                x=local_year_labels,
                y=top10,
                colorscale="Blues",
                colorbar=dict(
                    title=dict(text="Frequency", side="right"),
                    thickness=16,
                    len=0.72,
                    outlinewidth=1,
                    outlinecolor="#cccccc",
                ),
                hoverongaps=False,
                hovertemplate=(
                    "<b>%{y}</b><br>"
                    "Year: %{x}<br>"
                    "Count: %{z}<extra></extra>"
                ),
            ),
            row=2,
            col=1,
        )

        fig.update_layout(
            title=dict(
                text=panel_title,
                x=0.5,
                xanchor="center",
                font=dict(size=16),
            ),
            xaxis2=dict(
                title="Publication Year",
                type="category",
                tickangle=-45,
                tickfont=dict(size=11),
            ),
            yaxis=dict(
                title="Total / Year",
                tickfont=dict(size=10),
            ),
            yaxis2=dict(
                title=term_label,
                autorange="reversed",
                tickfont=dict(size=11),
            ),
            height=540,
            margin=dict(l=220, r=90, t=80, b=90),
            paper_bgcolor="white",
            plot_bgcolor="white",
            showlegend=False,
        )

        display.plotly_chart(fig, use_container_width=True)

    # ---- Figure 2: keyword heatmap -----------------------------------------
    _render_term_heatmap(
        term_field="Keywords",
        term_label="Keyword",
        panel_title="Top 10 Keywords — Frequency by Year (with Marginal Yearly Totals)",
    )

    # ---- Figure 3: keyword co-occurrence network ---------------------------
    network_keyword_count = display.number_input(
        "Number of keywords",
        min_value=1,
        max_value=30,
        value=10,
        step=1,
        key="network_keyword_count",
    )

    publication_keywords = []
    keyword_freq = Counter()
    for rec in records:
        year = rec.get("Publication Year")
        kw_str = (rec.get("Keywords") or "").strip()
        if not kw_str or year is None:
            continue
        try:
            year = int(year)
        except (ValueError, TypeError):
            continue
        if not (start_year <= year <= end_year):
            continue

        kws = [k.strip() for k in kw_str.split(";") if k.strip()]
        if not kws:
            continue
        kws_unique = sorted(set(kws))
        publication_keywords.append(kws_unique)
        keyword_freq.update(kws_unique)

    if keyword_freq:
        top50_keywords = [k for k, _ in keyword_freq.most_common(int(network_keyword_count))]
        top50_set = set(top50_keywords)

        edge_weights = Counter()
        for kws in publication_keywords:
            kws_top = [k for k in kws if k in top50_set]
            if len(kws_top) < 2:
                continue
            for a, b in combinations(sorted(kws_top), 2):
                edge_weights[(a, b)] += 1

        # Keep stronger edges to reduce clutter
        top_edges = sorted(edge_weights.items(), key=lambda x: x[1], reverse=True)[:400]

        # Build graph and layout (spring layout if networkx is available)
        graph = None
        node_pos = {}
        local_nx = nx
        if local_nx is None:
            try:
                import importlib
                local_nx = importlib.import_module("networkx")
            except Exception:
                local_nx = None

        if local_nx is not None:
            graph = local_nx.Graph()
            graph.add_nodes_from(top50_keywords)
            for (a, b), w in top_edges:
                graph.add_edge(a, b, weight=w)

            n = max(len(top50_keywords), 1)
            node_pos = local_nx.spring_layout(
                graph,
                k=0.7 / math.sqrt(n),
                iterations=250,
                seed=42,
                weight="weight",
            )
        else:
            # Fallback layout (deterministic plane-distributed spiral)
            fallback_degree = Counter()
            for (a, b), _w in top_edges:
                fallback_degree[a] += 1
                fallback_degree[b] += 1

            ordered_nodes = sorted(
                top50_keywords,
                key=lambda k: (fallback_degree.get(k, 0), keyword_freq.get(k, 0)),
                reverse=True,
            )
            n = max(len(ordered_nodes), 1)
            golden_angle = math.pi * (3 - math.sqrt(5))
            for i, kw in enumerate(ordered_nodes):
                # Radius in [0, 1]: denser near center, spread over full disk
                r = math.sqrt((i + 0.5) / n)
                theta = i * golden_angle
                node_pos[kw] = (r * math.cos(theta), r * math.sin(theta))

        node_sizes_raw = [keyword_freq[k] for k in top50_keywords]
        min_f = min(node_sizes_raw) if node_sizes_raw else 1
        max_f = max(node_sizes_raw) if node_sizes_raw else 1

        def _scale_size(v):
            if max_f == min_f:
                return 18
            return 10 + (v - min_f) * 26 / (max_f - min_f)

        # Build degree stats from retained edges
        if graph is not None:
            degree = Counter(dict(graph.degree()))
        else:
            degree = Counter()
            for (a, b), _w in top_edges:
                degree[a] += 1
                degree[b] += 1

        edge_weights_only = [w for (_pair, w) in top_edges]
        min_w = min(edge_weights_only) if edge_weights_only else 1
        max_w = max(edge_weights_only) if edge_weights_only else 1

        def _scale_edge_width(w):
            if max_w == min_w:
                return 2.0
            norm = (w - min_w) / (max_w - min_w)
            return 0.3 + (norm ** 1.8) * 7.2

        node_x = [node_pos[k][0] for k in top50_keywords]
        node_y = [node_pos[k][1] for k in top50_keywords]
        node_size = [_scale_size(keyword_freq[k]) for k in top50_keywords]
        node_degree = [degree.get(k, 0) for k in top50_keywords]
        node_text = [
            f"<b>{k}</b><br>Frequency: {keyword_freq[k]}<br>Connections: {degree.get(k, 0)}"
            for k in top50_keywords
        ]

        fig_net = go.Figure()
        for (a, b), w in top_edges:
            x0, y0 = node_pos[a]
            x1, y1 = node_pos[b]
            fig_net.add_trace(
                go.Scatter(
                    x=[x0, x1],
                    y=[y0, y1],
                    mode="lines",
                    line=dict(width=_scale_edge_width(w), color="rgba(31,119,180,0.22)"),
                    hovertemplate=f"Co-occurrence: {w}<extra></extra>",
                    showlegend=False,
                )
            )

        fig_net.add_trace(
            go.Scatter(
                x=node_x,
                y=node_y,
                mode="markers",
                marker=dict(
                    size=node_size,
                    color=node_degree,
                    colorscale="Blues",
                    showscale=True,
                    colorbar=dict(title="# of connections"),
                    line=dict(width=1, color="#2f3e46"),
                    opacity=0.9,
                ),
                hovertext=node_text,
                hoverinfo="text",
                showlegend=False,
            )
        )

        fig_net.update_layout(
            title=dict(
                text=f"Keyword Co-occurrence Network (Top {int(network_keyword_count)} Keywords)",
                x=0.5,
                xanchor="center",
                font=dict(size=16),
            ),
            height=560,
            margin=dict(l=40, r=40, t=70, b=30),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        )

        display.plotly_chart(fig_net, use_container_width=True)
    else:
        display.warning("Not enough keyword data to build the keyword co-occurrence network.")

    # ---- Figure 4: topic heatmap -------------------------------------------
    _render_term_heatmap(
        term_field="Topics",
        term_label="Topic",
        panel_title="Top 10 Topics — Frequency by Year (with Marginal Yearly Totals)",
    )

    # ---- Figure 5: top-20 topics word cloud -------------------------------
    topic_rows = []
    for rec in records:
        year = rec.get("Publication Year")
        topic_str = (rec.get("Topics") or "").strip()
        if not topic_str or year is None:
            continue
        try:
            year = int(year)
        except (ValueError, TypeError):
            continue
        if not (start_year <= year <= end_year):
            continue
        topic_rows.extend([t.strip() for t in topic_str.split(";") if t.strip()])

    if not topic_rows:
        display.warning("No topics found for the word cloud.")
        return

    top20_topics = pd.Series(topic_rows).value_counts().head(20)
    if top20_topics.empty:
        display.warning("Not enough topic data to build the word cloud.")
        return

    if WordCloud is None:
        display.warning("Word cloud package is unavailable. Install `wordcloud` to render this figure.")
        return

    wc = WordCloud(
        width=1400,
        height=500,
        background_color="white",
        colormap="Blues",
        prefer_horizontal=0.9,
        random_state=42,
    ).generate_from_frequencies(top20_topics.to_dict())

    fig_wc, ax = plt.subplots(figsize=(12, 4))
    ax.imshow(wc, interpolation="bilinear")
    ax.axis("off")
    ax.set_title("Top 20 Topics — Word Cloud", fontsize=16)
    display.pyplot(fig_wc, use_container_width=True)
    plt.close(fig_wc)

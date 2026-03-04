# Guidance

This document helps IPCC AR7 WGII authors use **Climate Knowledge Finder (version 0.1)** to look for grey literature about climate-related topics.

## 1) What this app does 

**Climate Knowledge Finder** is a Web App designed for:

-   searching climate-related grey literature from [OpenAlex](https://openalex.org/),
-   reviewing and analyzing returned records,
-   filtering and refining records,
-   exporting results as CSV, JSON, and Neo4j Cypher.

## 2) Quick start

### Prerequisites

-   Web browser (Google Chrome is recommended)
-   Internet access (required for OpenAlex)

### Web App Url 
https://wg2literature.streamlit.app/ 

## 3) Core controls in Grey literature searching

-   **Keyword**: separate terms with `;` (AND logic).
-   **Publication year**: inclusive year range.
-   **Type**: up to 3 selected types are used.
-   **Language**: language filter (default English).
-   **Global South**: include only works with Global South institutions when checked.
-   **UN member states**: include only works with at least one institution from selected member state.
-   **Max Number / Type**: fetch size per type.
-   **Sort by**: Relevance, Citation count, Date.

## 4) Buttons and outputs

In **Grey literature searching**:
-   **Search OpenAlex**: runs query and updates current payload.
-   **Analyze Results**: runs analysis on latest payload (cached data).
-   **Clear Results**: clears current visible output state.
-   **Download CSV / JSON / Neo4j**: export the current payload.

In **Grey Literature Review & Export**:

-   **View HTML** shows card-style records.
-   **Filter Topic** narrows displayed cards.
-   **Skip** removes a record from export payload.
-   **Similar works / Citing works / Cited works** are currently under construction.

## 5) User scenario (recommended workflow)

### Scenario

You are preparing references on climate-water in East Africa and look for policy-relevant grey literature.

### Steps

1.  Set **Keyword** to `climate change`; `water`.
2.  Set **Publication year** to `(2020, 2026)`.
3.  Set **Type** to `report` and `preprint`.
4.  Keep **Language** as `English` (default).
5.  Tick **Global South**.
6.  Set **UN member states** to `Kenya` (or another focus country).
7.  Set **Max Number / Type** to `325` and **Sort by** to `Relevance`.
8.  Click **Search OpenAlex**. 
9.  Click **Analyze Results**, which shows 
    - The number of publications per year
    ![alt text](assets/md_totalpublication.png)
    - The occurrence of top 10 key words 
    ![alt text](assets/md_top10_keywords_occurrence.png)
    - The co-occurrence of keywords
    ![alt text](assets/md_keywords_cooccurrence.png)
    - The most related topics per year (via a topic model)
    ![alt text](assets/md_related_topics_per_year.png)
    - Word cloud of keywords (under construction)
    ![alt text](assets/md_keywords_wordcloud.png)

10. Now you have the options to save (all) the results as CSV, JSON, or Neo4j files. 
11. Click **View html** and select topics. 
12. You can read the metadata and abstracts of the publications.  
![alt text](assets/md_publication_metadata_abstracts.png)
13. For less relevant publications, you can click on the **skip** button can optionally download the remaining results again.  
14. Other buttons are still under construction at this moment. 
15. If you'd like to search other topics, you can refresh the page and search again. 

## 7) Troubleshooting

-   **No results**: broaden years, remove country filter, or untick Global South.
-   **Too many results**: tighten keywords, narrow years, reduce types.
-   **Slow response**: lower Max Number / Type.
-   **Analyze disabled**: run Search first.
-   **Export smaller than expected**: check skipped records in HTML review.

## 8) Notes

-   Data is sourced from OpenAlex and may vary by metadata quality.
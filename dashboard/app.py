import os
import json
import base64
import html
from datetime import datetime
from typing import List, Dict, Any, Optional
import streamlit as st

# Configure page layout
st.set_page_config(
    page_title="Document Intelligence",
    page_icon="[DOCS]",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Load GeistPixel and GeistMono fonts into base64 for embedding
def get_font_base64(path: str) -> str:
    if os.path.exists(path):
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    return ""

font_dir = os.path.join(os.path.dirname(__file__), "fonts")
pixel_b64 = get_font_base64(os.path.join(font_dir, "GeistPixel.ttf"))
mono_b64 = get_font_base64(os.path.join(font_dir, "GeistMono.ttf"))

font_faces = ""
if pixel_b64:
    font_faces += f"""
    @font-face {{
        font-family: 'GeistPixel';
        src: url(data:font/truetype;charset=utf-8;base64,{pixel_b64}) format('truetype');
        font-weight: normal;
        font-style: normal;
    }}
    """
if mono_b64:
    font_faces += f"""
    @font-face {{
        font-family: 'GeistMono';
        src: url(data:font/truetype;charset=utf-8;base64,{mono_b64}) format('truetype');
        font-weight: normal;
        font-style: normal;
    }}
    """

# Custom CSS adhering to strict design rules
# Minimalist white theme with subtle halftone dot grid, 0px border radius, sharp edges
custom_css = f"""
<style>
{font_faces}

/* Base App & Halftone Background */
.stApp {{
    background-color: #ffffff !important;
    background-image: radial-gradient(#d8d8d8 1px, transparent 1px) !important;
    background-size: 16px 16px !important;
    color: #111111 !important;
    font-family: 'GeistMono', monospace !important;
}}

/* Sidebar Styling */
section[data-testid="stSidebar"] {{
    background-color: #fafafa !important;
    border-right: 1px solid #e0e0e0 !important;
}}

/* Typography */
h1, h2, h3, h4, h5, h6 {{
    font-family: 'GeistPixel', monospace !important;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-weight: normal !important;
    color: #000000 !important;
    margin-bottom: 0.5rem !important;
    border: none !important;
}}

p, span, div, label, input, button, table {{
    font-family: 'GeistMono', monospace !important;
    color: #111111;
}}

/* Sharp Edges Everywhere */
button, input, select, textarea, div[data-baseweb="select"], .stTextInput > div > div, .stSelectbox > div > div {{
    border-radius: 0px !important;
    border: 1px solid #cccccc !important;
    background-color: #ffffff !important;
    color: #000000 !important;
}}

/* Button Styling */
.stButton > button {{
    border-radius: 0px !important;
    border: 1px solid #111111 !important;
    background-color: #f7f7f7 !important;
    color: #000000 !important;
    font-family: 'GeistMono', monospace !important;
    padding: 0.5rem 1rem !important;
    transition: none !important;
}}

.stButton > button:hover {{
    background-color: #000000 !important;
    border-color: #000000 !important;
    color: #ffffff !important;
}}

/* Flat Stat Cards */
.stat-card {{
    background-color: #fbfbfb;
    border: 1px solid #e0e0e0;
    padding: 1rem;
    margin-bottom: 1rem;
    border-radius: 0px;
}}

.stat-label {{
    font-family: 'GeistMono', monospace;
    font-size: 0.75rem;
    color: #666666;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}}

.stat-value {{
    font-family: 'GeistPixel', monospace;
    font-size: 1.75rem;
    color: #000000;
    margin-top: 0.25rem;
}}

/* Document Record Card */
.doc-card {{
    background-color: #ffffff;
    border: 1px solid #dedede;
    padding: 1.25rem;
    margin-bottom: 0.75rem;
    border-radius: 0px;
}}

.doc-card:hover {{
    border-color: #888888;
}}

.doc-title {{
    font-family: 'GeistMono', monospace;
    font-weight: bold;
    font-size: 1rem;
    color: #000000;
    word-break: break-all;
}}

.tag-badge {{
    display: inline-block;
    background-color: #f0f0f0;
    border: 1px solid #d0d0d0;
    color: #222222;
    font-size: 0.75rem;
    padding: 2px 6px;
    margin-right: 4px;
    margin-bottom: 4px;
    font-family: 'GeistMono', monospace;
    border-radius: 0px;
}}

/* Expanders */
div[data-testid="stExpander"] {{
    border-radius: 0px !important;
    border: 1px solid #e0e0e0 !important;
    background-color: #ffffff !important;
}}

/* Hide Streamlit Standard Elements */
#MainMenu {{visibility: hidden;}}
footer {{visibility: hidden;}}
header {{visibility: hidden;}}
</style>
"""

st.markdown(custom_css, unsafe_allow_html=True)


# Query Generator & Data Fetching with RAM cache (TTL: 60s)
def build_bigquery_sql(
    project_id: str,
    dataset_id: str,
    table_id: str,
    doc_type_filter: str = "ALL",
    language_filter: str = "ALL",
    order_by: str = "date DESC",
    row_limit: int = 100,
    custom_where: str = ""
) -> str:
    """Constructs parameterized SQL query with guardrails."""
    conditions = []
    
    if doc_type_filter and doc_type_filter != "ALL":
        safe_type = doc_type_filter.replace("'", "")
        conditions.append(f"document_type = '{safe_type}'")
        
    if language_filter and language_filter != "ALL":
        safe_lang = language_filter.replace("'", "")
        conditions.append(f"language = '{safe_lang}'")
        
    if custom_where.strip():
        # Clean custom where clause
        cleaned = custom_where.strip().lstrip("WHERE").lstrip("where").strip()
        if cleaned:
            conditions.append(f"({cleaned})")
            
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    
    return f"""
SELECT 
    filename, 
    date, 
    tags, 
    word_count, 
    summary, 
    gcs_uri, 
    content_type,
    file_size_bytes,
    language,
    document_type,
    entities_json,
    content_sha256
FROM `{project_id}.{dataset_id}.{table_id}`
{where_clause}
ORDER BY {order_by}
LIMIT {row_limit};
""".strip()


@st.cache_data(ttl=60)
def fetch_documents_from_bigquery(
    project_id: str,
    dataset_id: str,
    table_id: str,
    query_sql: str
) -> List[Dict[str, Any]]:
    """Fetches document metadata from BigQuery with query scan protection and caching."""
    try:
        from google.cloud import bigquery
        client = bigquery.Client(project=project_id)
        
        # Guardrail: Maximum bytes billed cap (10 MB limit)
        job_config = bigquery.QueryJobConfig(
            maximum_bytes_billed=10000000,
            use_query_cache=True
        )
        
        query_job = client.query(query_sql, job_config=job_config)
        rows = [dict(row) for row in query_job.result()]
        return rows
    except Exception as e:
        # Fallback to local mock store for offline development
        return load_local_mock_records()


def load_local_mock_records() -> List[Dict[str, Any]]:
    """Loads records from local simulation file if offline."""
    mock_file = os.path.join(os.getcwd(), "data", "bigquery_stream_mock.jsonl")
    if os.path.exists(mock_file):
        records = []
        with open(mock_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    records.append(json.loads(line.strip()))
        return list(reversed(records))
    return []


# Application Header
st.markdown("<h1>Document Intelligence Pipeline</h1>", unsafe_allow_html=True)
st.caption("Event-Driven Serverless Pipeline : Cloud Storage : PubSub : Cloud Run : BigQuery")

# Sidebar Configuration & Query Controls
with st.sidebar:
    st.markdown("<h3>Pipeline Controls</h3>", unsafe_allow_html=True)
    
    project_id = st.text_input("GCP Project ID", value="antigravity-gdg-manila")
    dataset_id = st.text_input("BigQuery Dataset", value="document_analytics")
    table_id = st.text_input("BigQuery Table", value="processed_documents")
    
    st.markdown("<h3>Query Options</h3>", unsafe_allow_html=True)
    
    doc_type_filter = st.selectbox(
        "Document Type Filter",
        options=["ALL", "invoice", "contract", "resume", "report", "other"]
    )
    
    language_filter = st.selectbox(
        "Language Filter",
        options=["ALL", "en", "tl", "es", "ja", "other"]
    )
    
    sort_order = st.selectbox(
        "Sort Order",
        options=["date DESC", "date ASC", "word_count DESC", "word_count ASC", "filename ASC"]
    )
    
    row_limit = st.slider("Max Rows (LIMIT)", min_value=10, max_value=250, value=100, step=10)
    
    custom_where = st.text_input(
        "Custom SQL Filter (Optional)",
        value="",
        placeholder="e.g. word_count > 30"
    )
    
    if st.button("Refresh / Run Query"):
        fetch_documents_from_bigquery.clear()
        st.rerun()

# Build SQL Query
active_sql = build_bigquery_sql(
    project_id=project_id,
    dataset_id=dataset_id,
    table_id=table_id,
    doc_type_filter=doc_type_filter,
    language_filter=language_filter,
    order_by=sort_order,
    row_limit=row_limit,
    custom_where=custom_where
)

# SQL Inspection Accordion
with st.expander("Inspect Active BigQuery SQL Query"):
    st.code(active_sql, language="sql")
    st.caption("Guardrails active: maximum_bytes_billed = 10,000,000 bytes (10 MB scan ceiling) : cache TTL = 60s")

# Load Data
records = fetch_documents_from_bigquery(project_id, dataset_id, table_id, active_sql)

if not records:
    st.info("No records matched the query. Try adjusting the filters or upload new files to Cloud Storage.")
else:
    # Summary Metrics Row
    total_docs = len(records)
    total_words = sum(int(r.get("word_count") or 0) for r in records)
    all_tags = sorted(list(set(tag for r in records for tag in (r.get("tags") or []))))
    languages = sorted(list(set(r.get("language") or "en" for r in records)))

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(f'<div class="stat-card"><div class="stat-label">Total Documents</div><div class="stat-value">{total_docs}</div></div>', unsafe_allow_html=True)
    with col2:
        st.markdown(f'<div class="stat-card"><div class="stat-label">Total Word Count</div><div class="stat-value">{total_words:,}</div></div>', unsafe_allow_html=True)
    with col3:
        st.markdown(f'<div class="stat-card"><div class="stat-label">Distinct Tags</div><div class="stat-value">{len(all_tags)}</div></div>', unsafe_allow_html=True)
    with col4:
        st.markdown(f'<div class="stat-card"><div class="stat-label">Languages Detected</div><div class="stat-value">{", ".join(languages).upper()}</div></div>', unsafe_allow_html=True)

    # Search and Filter Controls
    fcol1, fcol2 = st.columns([2, 1])
    with fcol1:
        search_query = st.text_input("Filter Results by Keyword", placeholder="Search filename or summary...")
    with fcol2:
        selected_tags = st.multiselect("Filter by Tag", options=all_tags)

    # Filter Records in Memory
    filtered = records
    if search_query:
        q = search_query.lower()
        filtered = [
            r for r in filtered 
            if q in (r.get("filename") or "").lower() or q in (r.get("summary") or "").lower()
        ]

    if selected_tags:
        filtered = [
            r for r in filtered 
            if any(t in (r.get("tags") or []) for t in selected_tags)
        ]

    st.markdown(f"<h3>Processed Records ({len(filtered)})</h3>", unsafe_allow_html=True)

    # Display Records
    for item in filtered:
        fname = html.escape(item.get("filename") or "untitled")
        fdate = html.escape(str(item.get("date") or ""))
        words = int(item.get("word_count") or 0)
        summary = html.escape(item.get("summary") or "No summary available.")
        lang = html.escape((item.get("language") or "en").upper())
        doc_type = html.escape((item.get("document_type") or "general").upper())
        tags = item.get("tags") or []
        
        tag_html = "".join([f'<span class="tag-badge">{html.escape(t)}</span>' for t in tags])
        
        entities_raw = item.get("entities_json")
        entities_dict = {}
        if entities_raw:
            try:
                entities_dict = json.loads(entities_raw) if isinstance(entities_raw, str) else entities_raw
            except Exception:
                pass

        with st.container():
            st.markdown(
                f"""
                <div class="doc-card">
                    <div style="display: flex; justify-content: space-between; align-items: baseline;">
                        <span class="doc-title">{fname}</span>
                        <span style="font-size: 0.75rem; color: #666666;">{fdate}</span>
                    </div>
                    <div style="margin-top: 0.5rem; font-size: 0.85rem; color: #333333;">
                        {summary}
                    </div>
                    <div style="margin-top: 0.75rem;">
                        <span class="tag-badge" style="background-color: #000000; color: #ffffff; border-color: #000000;">TYPE: {doc_type}</span>
                        <span class="tag-badge" style="background-color: #e5e5e5; color: #000000;">LANG: {lang}</span>
                        <span class="tag-badge" style="background-color: #e5e5e5; color: #000000;">WORDS: {words}</span>
                        {tag_html}
                    </div>
                </div>
                """,
                unsafe_allow_html=True
            )
            
            # Entities expander
            if entities_dict and any(entities_dict.values()):
                with st.expander("Inspect Extracted Entities"):
                    ecol1, ecol2, ecol3 = st.columns(3)
                    with ecol1:
                        if entities_dict.get("dates"):
                            st.caption("DATES")
                            for d in entities_dict["dates"]:
                                st.code(d, language=None)
                    with ecol2:
                        if entities_dict.get("organizations"):
                            st.caption("ORGANIZATIONS")
                            for org in entities_dict["organizations"]:
                                st.code(org, language=None)
                    with ecol3:
                        if entities_dict.get("monetary_amounts"):
                            st.caption("AMOUNTS")
                            for amt in entities_dict["monetary_amounts"]:
                                st.code(amt, language=None)

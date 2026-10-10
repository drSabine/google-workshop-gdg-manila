import os
import json
import base64
import html
from datetime import datetime
from typing import List, Dict, Any
import streamlit as st

# Configure page layout and dark theme
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
# Halftone dot background, 0px border radius, no gradients, no accent bars
custom_css = f"""
<style>
{font_faces}

/* Base App & Halftone Background */
.stApp {{
    background-color: #080808;
    background-image: radial-gradient(#1c1c1c 1px, transparent 1px);
    background-size: 16px 16px;
    color: #e6e6e6;
    font-family: 'GeistMono', monospace !important;
}}

/* Typography */
h1, h2, h3, h4, h5, h6 {{
    font-family: 'GeistPixel', monospace !important;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-weight: normal !important;
    color: #ffffff !important;
    margin-bottom: 0.5rem !important;
    border: none !important;
}}

p, span, div, label, input, button, table {{
    font-family: 'GeistMono', monospace !important;
}}

/* Sharp Edges Everywhere */
button, input, select, textarea, div[data-baseweb="select"], .stTextInput > div > div {{
    border-radius: 0px !important;
    border: 1px solid #282828 !important;
    background-color: #121212 !important;
    color: #f0f0f0 !important;
}}

/* Button Styling */
.stButton > button {{
    border-radius: 0px !important;
    border: 1px solid #333333 !important;
    background-color: #141414 !important;
    color: #ffffff !important;
    font-family: 'GeistMono', monospace !important;
    padding: 0.5rem 1rem !important;
    transition: none !important;
}}

.stButton > button:hover {{
    background-color: #222222 !important;
    border-color: #555555 !important;
    color: #ffffff !important;
}}

/* Flat Stat Cards */
.stat-card {{
    background-color: #101010;
    border: 1px solid #222222;
    padding: 1rem;
    margin-bottom: 1rem;
    border-radius: 0px;
}}

.stat-label {{
    font-family: 'GeistMono', monospace;
    font-size: 0.75rem;
    color: #888888;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}}

.stat-value {{
    font-family: 'GeistPixel', monospace;
    font-size: 1.75rem;
    color: #ffffff;
    margin-top: 0.25rem;
}}

/* Document Record Card */
.doc-card {{
    background-color: #0e0e0e;
    border: 1px solid #202020;
    padding: 1.25rem;
    margin-bottom: 0.75rem;
    border-radius: 0px;
}}

.doc-title {{
    font-family: 'GeistMono', monospace;
    font-weight: bold;
    font-size: 1rem;
    color: #ffffff;
    word-break: break-all;
}}

.tag-badge {{
    display: inline-block;
    background-color: #1a1a1a;
    border: 1px solid #303030;
    color: #b0b0b0;
    font-size: 0.75rem;
    padding: 2px 6px;
    margin-right: 4px;
    margin-bottom: 4px;
    font-family: 'GeistMono', monospace;
    border-radius: 0px;
}}

/* Hide Streamlit Standard Elements */
#MainMenu {{visibility: hidden;}}
footer {{visibility: hidden;}}
header {{visibility: hidden;}}
</style>
"""

st.markdown(custom_css, unsafe_allow_html=True)


# Data Fetching from BigQuery with RAM cache (TTL: 60s)
@st.cache_data(ttl=60)
def fetch_documents_from_bigquery(project_id: str, dataset_id: str, table_id: str) -> List[Dict[str, Any]]:
    """Fetches document metadata from BigQuery with query scan protection and caching."""
    try:
        from google.cloud import bigquery
        client = bigquery.Client(project=project_id)
        
        # Guardrail: Maximum bytes billed cap (10 MB limit)
        job_config = bigquery.QueryJobConfig(
            maximum_bytes_billed=10000000,
            use_query_cache=True
        )
        
        query = f"""
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
            ORDER BY date DESC
            LIMIT 100;
        """
        query_job = client.query(query, job_config=job_config)
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

# Sidebar Configuration & Access Control
with st.sidebar:
    st.markdown("<h3>Pipeline Controls</h3>", unsafe_allow_html=True)
    
    project_id = st.text_input("GCP Project ID", value="antigravity-gdg-manila")
    dataset_id = st.text_input("BigQuery Dataset", value="document_analytics")
    table_id = st.text_input("BigQuery Table", value="processed_documents")
    
    if st.button("Refresh Pipeline Data"):
        fetch_documents_from_bigquery.clear()
        st.rerun()

# Load Data
records = fetch_documents_from_bigquery(project_id, dataset_id, table_id)

if not records:
    st.info("No records found in BigQuery table yet. Upload files to Cloud Storage to trigger ingestion.")
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
        search_query = st.text_input("Search Filename or Summary", placeholder="Enter keyword...")
    with fcol2:
        selected_tags = st.multiselect("Filter by Tag", options=all_tags)

    # Filter Records
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
                        <span style="font-size: 0.75rem; color: #888888;">{fdate}</span>
                    </div>
                    <div style="margin-top: 0.5rem; font-size: 0.85rem; color: #cccccc;">
                        {summary}
                    </div>
                    <div style="margin-top: 0.75rem;">
                        <span class="tag-badge" style="background-color: #222222; color: #ffffff;">TYPE: {doc_type}</span>
                        <span class="tag-badge" style="background-color: #222222; color: #ffffff;">LANG: {lang}</span>
                        <span class="tag-badge" style="background-color: #222222; color: #ffffff;">WORDS: {words}</span>
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

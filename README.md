# Serverless Event-Driven Document Processing Pipeline on Google Cloud

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)
[![Cloud Run](https://img.shields.io/badge/Google%20Cloud-Cloud%20Run-4285F4.svg)](https://cloud.google.com/run)
[![Cloud Pub/Sub](https://img.shields.io/badge/Google%20Cloud-Pub%2FSub%20Push-4285F4.svg)](https://cloud.google.com/pubsub)
[![BigQuery](https://img.shields.io/badge/BigQuery-Storage%20Write%20API-4285F4.svg)](https://cloud.google.com/bigquery/docs/write-api)

A production-grade, serverless, event-driven document processing pipeline built on Google Cloud. Built for high throughput, low latency, and enterprise reliability with automated dead-letter queues and OIDC security.

---

## 🏛️ Architecture Overview

```
                                  +---------------------------------------------+
                                  | Cloud Pub/Sub Service Agent                 |
                                  | (service-PROJECT_NUM@gcp-sa-pubsub...)       |
                                  +---------------------------------------------+
                                                         |
                                                         v (Publishes poison-pills)
+-------------+  Upload   +-------------+  Notification  +-------------+  Push (OIDC)   +---------------+  Storage Write API  +--------------+
|    User     | --------> | Cloud       | -------------> | Pub/Sub     | -------------> | Cloud Run     | ------------------> | BigQuery     |
| Client / UI |           | Storage     | OBJECT_        | Main Topic  | Exponential    | (FastAPI OCR  | (Protobuf Streaming)| Dataset      |
+-------------+           | Bucket      | FINALIZE       +-------------+ Backoff / Auth |  Processor)   |                     +--------------+
                          +-------------+                       |                       +---------------+
                                                                | (After 5 failed retries)
                                                                v
                                                         +-------------+
                                                         | Dead-Letter |
                                                         | Topic (DLQ) |
                                                         +-------------+
                                                                |
                                                                v
                                                         +-------------+
                                                         | DLQ Pull    |
                                                         | Subscription|
                                                         +-------------+
```

### Key Architectural Decisions (Aligned with Grill-Me Specifications)
1. **Event Ingestion**: Cloud Storage native Pub/Sub notification (`OBJECT_FINALIZE`, JSON payload format).
2. **Streaming Target**: BigQuery **Storage Write API** (default stream) using **Protocol Buffers v2 (`proto2`)** serialization for ultra-low latency and streaming quotas.
3. **Delivery Mechanism**: Pub/Sub **Push Subscription** protected with **OIDC Service Account authentication** (`roles/run.invoker`).
4. **Resilience & Fault Tolerance**: Pub/Sub **Dead-Letter Queue (DLQ)** with exponential backoff (min: 10s, max: 600s, max delivery attempts: 5).
5. **Compute**: Fully managed, auto-scaling **Cloud Run** service containerized with FastAPI and Python 3.11.
6. **Infrastructure Automation**: Complete deployment scripts provided in both **Bash** (`scripts/deploy.sh`) and **PowerShell** (`scripts/deploy.ps1`).

---

## 📁 Repository Structure

```
.
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI service receiving Pub/Sub push events
│   ├── ocr_processor.py           # Simulated OCR text, tag, and metadata extractor
│   ├── bq_writer.py               # BigQuery Storage Write API writer (Protobuf)
│   ├── config.py                  # Environment and settings configuration
│   ├── schema.json                # BigQuery table schema JSON definition
│   └── proto/
│       ├── document_metadata.proto    # Proto2 schema for BigQuery Storage Write API
│       └── document_metadata_pb2.py # Compiled Python protobuf bindings
├── scripts/
│   ├── deploy.sh                  # Complete automated bash deployment for GCP
│   ├── deploy.ps1                 # Complete automated PowerShell deployment for Windows
│   ├── test_pipeline.py           # Comprehensive local & live integration test runner
│   └── teardown.sh                # Resource cleanup script
├── Dockerfile                     # Cloud Run container definition
├── requirements.txt               # Python package dependencies
└── README.md                      # Documentation and operational runbook
```

---

## ⚡ Quickstart: Local Development & Testing

You can develop and test the entire pipeline locally without requiring active Google Cloud billing by enabling simulation mode (`MOCK_GCP=true`).

### 1. Set Up Virtual Environment

```powershell
# Windows PowerShell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

```bash
# Linux / macOS / Cloud Shell
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Run Standalone Component Tests

Test OCR extraction and Protobuf serialization directly:

```powershell
python scripts/test_pipeline.py --standalone
```

### 3. Start Local Server

```powershell
$env:MOCK_GCP = "true"
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

In another terminal, trigger a simulated document ingestion test:

```powershell
python scripts/test_pipeline.py --url http://localhost:8080
```

Inspect local mock records:
- Open your browser or curl: `http://localhost:8080/api/v1/mock-records`
- Mock files are saved to: `data/bigquery_stream_mock.jsonl`

---

## 🚀 Google Cloud Deployment

### Prerequisites
- [Google Cloud SDK (`gcloud`)](https://cloud.google.com/sdk/docs/install) installed and initialized.
- A GCP project with billing enabled.

### Option A: Deploy via Bash (Linux / macOS / Cloud Shell)

```bash
# 1. Login and select your project
gcloud auth login
gcloud config set project YOUR_PROJECT_ID

# 2. Run automated deployment script
chmod +x scripts/deploy.sh
./scripts/deploy.sh
```

### Option B: Deploy via PowerShell (Windows)

```powershell
# 1. Login and select your project
gcloud auth login
gcloud config set project YOUR_PROJECT_ID

# 2. Run automated PowerShell deployment script
.\scripts\deploy.ps1 -ProjectId YOUR_PROJECT_ID -Region asia-southeast1
```

The script will automatically:
1. Enable all 7 required APIs.
2. Create the Cloud Storage bucket with uniform access.
3. Create the BigQuery dataset and table using `app/schema.json`.
4. Create dedicated service accounts (`doc-runner-sa` and `pubsub-invoker-sa`) with least-privilege IAM roles.
5. Build and deploy the Cloud Run container.
6. Create the Dead-Letter Queue (DLQ) topic and DLQ pull subscription.
7. Create the main Pub/Sub push subscription configured with OIDC authentication and exponential retry backoff.
8. Register the Cloud Storage notification trigger on `OBJECT_FINALIZE`.

---

## 🧪 Testing the Live Pipeline

### 1. Upload a Document to Cloud Storage

```bash
# Create a dummy test invoice
echo "INVOICE #9941 - GDG Manila Workshop Demo. Total: $4,500.00" > demo_invoice.txt

# Upload to the GCS bucket
gcloud storage cp demo_invoice.txt gs://YOUR_PROJECT_ID-docs-ingest/
```

### 2. Verify Cloud Run Execution Logs

```bash
gcloud run services logs read doc-processor-service --region asia-southeast1 --limit 20
```

### 3. Query Extracted Metadata in BigQuery

```bash
bq query --use_legacy_sql=false \
  'SELECT filename, date, tags, word_count, summary 
   FROM `YOUR_PROJECT_ID.document_processing.document_metadata` 
   ORDER BY date DESC LIMIT 5;'
```

---

## 🛡️ Production Resilience & Error Handling

- **Dead-Letter Queue (DLQ)**: If Cloud Run fails to process a document after 5 attempts (due to corrupt files or downstream unreachability), Pub/Sub automatically diverts the message to `doc-pipeline-dlq`.
- **Inspect Failed Messages**:
  ```bash
  gcloud pubsub subscriptions pull doc-pipeline-dlq-sub --auto-ack --limit 5
  ```
- **OIDC Authentication**: The Cloud Run service rejects unauthenticated requests. Only the authorized Pub/Sub invoker service account can trigger endpoints.
- **BigQuery Storage Write API**: Uses the default stream with gRPC streaming buffers, eliminating batching delays and providing at-least-once ingestion.

---

## 🧹 Teardown & Clean Up

To delete cloud resources after the workshop:

```bash
chmod +x scripts/teardown.sh
./scripts/teardown.sh
```

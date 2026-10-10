#!/usr/bin/env bash
# ==============================================================================
# Serverless Event-Driven Document Processing Pipeline Deployment Script
# GDG Manila Workshop
# ==============================================================================
# Architecture:
# GCS (Upload) -> GCS Notification -> Pub/Sub Topic -> Push Sub (OIDC + DLQ)
# -> Cloud Run (Simulated OCR) -> BigQuery Storage Write API
# ==============================================================================

set -euo pipefail

# Configurations (Override via environment variables if desired)
PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null || echo '')}"
REGION="${REGION:-asia-southeast1}"
SERVICE_NAME="${SERVICE_NAME:-doc-processor-service}"
BUCKET_NAME="${BUCKET_NAME:-${PROJECT_ID}-docs-ingest}"
TOPIC_NAME="${TOPIC_NAME:-doc-pipeline-events}"
DLQ_TOPIC_NAME="${DLQ_TOPIC_NAME:-doc-pipeline-dlq}"
DLQ_SUB_NAME="${DLQ_SUB_NAME:-doc-pipeline-dlq-sub}"
SUB_NAME="${SUB_NAME:-doc-pipeline-cloudrun-sub}"
DATASET_ID="${DATASET_ID:-document_processing}"
TABLE_ID="${TABLE_ID:-document_metadata}"

# Service Accounts
RUN_SA_NAME="doc-runner-sa"
INVOKER_SA_NAME="pubsub-invoker-sa"

echo "=============================================================================="
echo " Starting Document Pipeline Deployment"
echo " Project ID:    ${PROJECT_ID}"
echo " Region:        ${REGION}"
echo " GCS Bucket:    gs://${BUCKET_NAME}"
echo " BigQuery:      ${DATASET_ID}.${TABLE_ID}"
echo " Cloud Run:     ${SERVICE_NAME}"
echo "=============================================================================="

if [ -z "${PROJECT_ID}" ]; then
  echo "ERROR: PROJECT_ID is empty. Set it via 'export PROJECT_ID=your-project-id' or 'gcloud config set project your-project-id'"
  exit 1
fi

PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
RUN_SA="${RUN_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
INVOKER_SA="${INVOKER_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
PUBSUB_SERVICE_AGENT="service-${PROJECT_NUMBER}@gcp-sa-pubsub.iam.gserviceaccount.com"

# ------------------------------------------------------------------------------
# 1. Enable Required GCP APIs
# ------------------------------------------------------------------------------
echo "--> [1/8] Enabling Google Cloud Services..."
gcloud services enable \
  run.googleapis.com \
  storage.googleapis.com \
  pubsub.googleapis.com \
  bigquery.googleapis.com \
  bigquerystorage.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  --project="${PROJECT_ID}"

# ------------------------------------------------------------------------------
# 2. Create Cloud Storage Bucket
# ------------------------------------------------------------------------------
echo "--> [2/8] Creating Cloud Storage Bucket: gs://${BUCKET_NAME}..."
if ! gcloud storage buckets describe "gs://${BUCKET_NAME}" --project="${PROJECT_ID}" &>/dev/null; then
  gcloud storage buckets create "gs://${BUCKET_NAME}" \
    --project="${PROJECT_ID}" \
    --location="${REGION}" \
    --uniform-bucket-level-access
else
  echo "Bucket gs://${BUCKET_NAME} already exists."
fi

# ------------------------------------------------------------------------------
# 3. Create BigQuery Dataset and Table
# ------------------------------------------------------------------------------
echo "--> [3/8] Creating BigQuery Dataset & Table..."
if ! bq show "${PROJECT_ID}:${DATASET_ID}" &>/dev/null; then
  bq --location="${REGION}" mk --dataset "${PROJECT_ID}:${DATASET_ID}"
else
  echo "Dataset ${DATASET_ID} already exists."
fi

if ! bq show "${PROJECT_ID}:${DATASET_ID}.${TABLE_ID}" &>/dev/null; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  SCHEMA_FILE="${SCRIPT_DIR}/../app/schema.json"
  bq mk --table "${PROJECT_ID}:${DATASET_ID}.${TABLE_ID}" "${SCHEMA_FILE}"
  echo "Created BigQuery table ${DATASET_ID}.${TABLE_ID}"
else
  echo "Table ${DATASET_ID}.${TABLE_ID} already exists."
fi

# ------------------------------------------------------------------------------
# 4. Create Service Accounts and Assign IAM Roles
# ------------------------------------------------------------------------------
echo "--> [4/8] Configuring Service Accounts and IAM permissions..."

# 4a. Cloud Run Service Account
if ! gcloud iam service-accounts describe "${RUN_SA}" --project="${PROJECT_ID}" &>/dev/null; then
  gcloud iam service-accounts create "${RUN_SA_NAME}" \
    --display-name="Cloud Run Document Processor SA" \
    --project="${PROJECT_ID}"
fi

# Grant Cloud Run SA read access to GCS and write access to BigQuery
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${RUN_SA}" \
  --role="roles/storage.objectViewer" >/dev/null

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${RUN_SA}" \
  --role="roles/bigquery.dataEditor" >/dev/null

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${RUN_SA}" \
  --role="roles/bigquery.jobUser" >/dev/null

# 4b. Pub/Sub Push Invoker Service Account
if ! gcloud iam service-accounts describe "${INVOKER_SA}" --project="${PROJECT_ID}" &>/dev/null; then
  gcloud iam service-accounts create "${INVOKER_SA_NAME}" \
    --display-name="Pub/Sub Cloud Run Invoker SA" \
    --project="${PROJECT_ID}"
fi

# ------------------------------------------------------------------------------
# 5. Build and Deploy Cloud Run Service
# ------------------------------------------------------------------------------
echo "--> [5/8] Deploying Cloud Run Service: ${SERVICE_NAME}..."
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

gcloud run deploy "${SERVICE_NAME}" \
  --source="${PROJECT_ROOT}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --service-account="${RUN_SA}" \
  --set-env-vars="PROJECT_ID=${PROJECT_ID},REGION=${REGION},GCS_BUCKET_NAME=${BUCKET_NAME},BQ_DATASET_ID=${DATASET_ID},BQ_TABLE_ID=${TABLE_ID},MOCK_GCP=false" \
  --no-allow-unauthenticated

# Retrieve deployed Cloud Run URL
CLOUD_RUN_URL="$(gcloud run services describe "${SERVICE_NAME}" --platform=managed --region="${REGION}" --project="${PROJECT_ID}" --format='value(status.url)')"
echo "Cloud Run Service deployed at: ${CLOUD_RUN_URL}"

# Grant Pub/Sub Invoker SA permission to invoke Cloud Run
gcloud run services add-iam-policy-binding "${SERVICE_NAME}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --member="serviceAccount:${INVOKER_SA}" \
  --role="roles/run.invoker" >/dev/null

# ------------------------------------------------------------------------------
# 6. Create Pub/Sub Topics (Main + Dead-Letter Queue)
# ------------------------------------------------------------------------------
echo "--> [6/8] Configuring Pub/Sub Topics & DLQ..."

# Main Event Topic
if ! gcloud pubsub topics describe "${TOPIC_NAME}" --project="${PROJECT_ID}" &>/dev/null; then
  gcloud pubsub topics create "${TOPIC_NAME}" --project="${PROJECT_ID}"
fi

# Dead-Letter Topic
if ! gcloud pubsub topics describe "${DLQ_TOPIC_NAME}" --project="${PROJECT_ID}" &>/dev/null; then
  gcloud pubsub topics create "${DLQ_TOPIC_NAME}" --project="${PROJECT_ID}"
fi

# Dead-Letter Subscription (for inspecting failed poison-pill messages)
if ! gcloud pubsub subscriptions describe "${DLQ_SUB_NAME}" --project="${PROJECT_ID}" &>/dev/null; then
  gcloud pubsub subscriptions create "${DLQ_SUB_NAME}" \
    --topic="${DLQ_TOPIC_NAME}" \
    --project="${PROJECT_ID}"
fi

# Grant Pub/Sub Service Agent permission to publish to DLQ topic
gcloud pubsub topics add-iam-policy-binding "${DLQ_TOPIC_NAME}" \
  --member="serviceAccount:${PUBSUB_SERVICE_AGENT}" \
  --role="roles/pubsub.publisher" \
  --project="${PROJECT_ID}" >/dev/null

# ------------------------------------------------------------------------------
# 7. Create Pub/Sub Push Subscription with OIDC & Exponential Backoff DLQ
# ------------------------------------------------------------------------------
echo "--> [7/8] Configuring Push Subscription with OIDC Auth & Dead-Letter Queue..."
PUSH_ENDPOINT="${CLOUD_RUN_URL}/api/v1/process-event"

if gcloud pubsub subscriptions describe "${SUB_NAME}" --project="${PROJECT_ID}" &>/dev/null; then
  echo "Deleting existing subscription to update configuration..."
  gcloud pubsub subscriptions delete "${SUB_NAME}" --project="${PROJECT_ID}" --quiet
fi

# Grant Pub/Sub Service Agent subscriber permission on the main subscription for DLQ forwarding
gcloud pubsub subscriptions create "${SUB_NAME}" \
  --topic="${TOPIC_NAME}" \
  --project="${PROJECT_ID}" \
  --push-endpoint="${PUSH_ENDPOINT}" \
  --push-auth-service-account="${INVOKER_SA}" \
  --dead-letter-topic="${DLQ_TOPIC_NAME}" \
  --max-delivery-attempts=5 \
  --min-retry-delay=10s \
  --max-retry-delay=600s \
  --ack-deadline=60

gcloud pubsub subscriptions add-iam-policy-binding "${SUB_NAME}" \
  --member="serviceAccount:${PUBSUB_SERVICE_AGENT}" \
  --role="roles/pubsub.subscriber" \
  --project="${PROJECT_ID}" >/dev/null

# ------------------------------------------------------------------------------
# 8. Wire Cloud Storage Bucket Notification to Pub/Sub
# ------------------------------------------------------------------------------
echo "--> [8/8] Creating GCS Bucket Notification Trigger..."
# Check existing notifications to avoid duplicates
EXISTING_NOTIFS="$(gcloud storage buckets notifications list "gs://${BUCKET_NAME}" --format="value(topic)" 2>/dev/null || echo '')"

if [[ "${EXISTING_NOTIFS}" != *"${TOPIC_NAME}"* ]]; then
  gcloud storage buckets notifications create "gs://${BUCKET_NAME}" \
    --topic="${TOPIC_NAME}" \
    --event-types="OBJECT_FINALIZE" \
    --payload-format="json"
  echo "Configured GCS notification for gs://${BUCKET_NAME} -> ${TOPIC_NAME}"
else
  echo "Notification trigger already active on gs://${BUCKET_NAME} for topic ${TOPIC_NAME}"
fi

echo "=============================================================================="
echo " Pipeline Deployment Complete!"
echo " Ingestion Bucket:      gs://${BUCKET_NAME}"
echo " Main Pub/Sub Topic:    ${TOPIC_NAME}"
echo " DLQ Topic:             ${DLQ_TOPIC_NAME}"
echo " Cloud Run Endpoint:    ${PUSH_ENDPOINT}"
echo " BigQuery Destination:  ${PROJECT_ID}.${DATASET_ID}.${TABLE_ID}"
echo ""
echo " Test by uploading a document:"
echo "   gcloud storage cp test_doc.pdf gs://${BUCKET_NAME}/"
echo " Query results in BigQuery:"
echo "   bq query --use_legacy_sql=false 'SELECT * FROM \`${PROJECT_ID}.${DATASET_ID}.${TABLE_ID}\` LIMIT 10;'"
echo "=============================================================================="

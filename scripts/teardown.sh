#!/usr/bin/env bash
# Clean up resources created by the document processing pipeline

set -euo pipefail

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null || echo '')}"
REGION="${REGION:-asia-southeast1}"
SERVICE_NAME="${SERVICE_NAME:-doc-processor-service}"
BUCKET_NAME="${BUCKET_NAME:-${PROJECT_ID}-docs-ingest}"
TOPIC_NAME="${TOPIC_NAME:-doc-pipeline-events}"
DLQ_TOPIC_NAME="${DLQ_TOPIC_NAME:-doc-pipeline-dlq}"
SUB_NAME="${SUB_NAME:-doc-pipeline-cloudrun-sub}"
DATASET_ID="${DATASET_ID:-document_processing}"

echo "Cleaning up resources in project ${PROJECT_ID}..."

# 1. Delete Pub/Sub Subscriptions & Topics
gcloud pubsub subscriptions delete "${SUB_NAME}" --quiet 2>/dev/null || true
gcloud pubsub subscriptions delete "doc-pipeline-dlq-sub" --quiet 2>/dev/null || true
gcloud pubsub topics delete "${TOPIC_NAME}" --quiet 2>/dev/null || true
gcloud pubsub topics delete "${DLQ_TOPIC_NAME}" --quiet 2>/dev/null || true

# 2. Delete Cloud Run Service
gcloud run services delete "${SERVICE_NAME}" --region="${REGION}" --quiet 2>/dev/null || true

# 3. Optional: Delete Storage Bucket (Caution: deletes all uploaded files)
read -p "Delete GCS bucket gs://${BUCKET_NAME}? (y/N): " -r CONFIRM
if [[ $CONFIRM =~ ^[Yy]$ ]]; then
  gcloud storage rm --recursive "gs://${BUCKET_NAME}" --quiet 2>/dev/null || true
fi

# 4. Optional: Delete BigQuery Dataset
read -p "Delete BigQuery dataset ${DATASET_ID}? (y/N): " -r CONFIRM_BQ
if [[ $CONFIRM_BQ =~ ^[Yy]$ ]]; then
  bq rm -r -f -d "${PROJECT_ID}:${DATASET_ID}" 2>/dev/null || true
fi

echo "Teardown complete!"

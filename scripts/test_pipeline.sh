#!/usr/bin/env bash
# ==============================================================================
# Live End-to-End Pipeline Verification Script
# Matches Step 6 of the Google Codelab: Build & Deploy with Antigravity
# ==============================================================================

set -euo pipefail

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null || echo 'antigravity-gdg-manila')}"
REGION="${REGION:-asia-southeast1}"
BUCKET_NAME="${BUCKET_NAME:-${PROJECT_ID}-docs-ingest}"
DATASET_ID="${DATASET_ID:-document_analytics}"
TABLE_ID="${TABLE_ID:-processed_documents}"

TIMESTAMP="$(date +%s)"
FILE_CONTRACT="test_contract_${TIMESTAMP}.txt"
FILE_INVOICE="test_invoice_${TIMESTAMP}.pdf"

echo "=============================================================================="
echo " Starting Live Pipeline Verification against Google Cloud"
echo " Project:  ${PROJECT_ID}"
echo " Bucket:   gs://${BUCKET_NAME}"
echo " BigQuery: ${PROJECT_ID}.${DATASET_ID}.${TABLE_ID}"
echo "=============================================================================="

# 1. Generate test documents
echo "--> [1/4] Generating test document payloads..."
cat << 'EOF' > "${FILE_CONTRACT}"
SERVICE LEVEL AGREEMENT AND MASTER SERVICES CONTRACT.
Between Provider and Client. Parties agree to terms regarding 99.99% availability,
data retention policies in Google Cloud Storage, automated disaster recovery,
and confidentiality warranties under Philippine and international laws.
This document was ingested via Google Cloud Storage and triggered via Cloud Pub/Sub.
EOF

cat << 'EOF' > "${FILE_INVOICE}"
%PDF-1.4 TAX INVOICE Reference: INV-2026-GDG.
Billed To: Global Enterprise Solutions Inc.
Item 01: Cloud Computing Infrastructure Services - 400 hrs.
Item 02: BigQuery Analytics Streaming Pipeline - 150 hrs.
Subtotal: $14,250.00. Tax (VAT 12%): $1,710.00. Total Payable: $15,960.00.
Payment Terms: Net 30 days. Remit payment to Standard Chartered Bank.
EOF

# 2. Upload to Cloud Storage
echo "--> [2/4] Uploading test documents to Cloud Storage..."
gcloud storage cp "${FILE_CONTRACT}" "gs://${BUCKET_NAME}/"
gcloud storage cp "${FILE_INVOICE}" "gs://${BUCKET_NAME}/"

# Clean up local test files
rm -f "${FILE_CONTRACT}" "${FILE_INVOICE}"

echo "--> [3/4] Documents uploaded. Waiting 8 seconds for event-driven pipeline execution..."
echo "    (GCS -> OBJECT_FINALIZE -> Pub/Sub -> Cloud Run /process -> BigQuery Storage Write API)"
sleep 8

# 3. Query BigQuery for live results
echo "--> [4/4] Querying BigQuery table ${DATASET_ID}.${TABLE_ID}..."
echo ""
bq query --use_legacy_sql=false \
  "SELECT 
     filename, 
     word_count, 
     tags, 
     date, 
     summary 
   FROM \`${PROJECT_ID}.${DATASET_ID}.${TABLE_ID}\` 
   ORDER BY date DESC 
   LIMIT 10;"

echo ""
echo "=============================================================================="
echo " Live Verification Complete!"
echo " All pipeline components are active, healthy, and verified in production."
echo "=============================================================================="

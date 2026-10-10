# Chronological Execution & Testing Guide

A simple, step-by-step checklist to complete your Google Cloud deployment and test the pipeline.

---

### Step 1: Fix Cloud Build Permissions & Reset Repository

Run this in **Google Cloud Shell** to unblock `git pull` and grant the required build permissions:

```bash
# 1. Reset local changes and pull the latest scripts
git reset --hard origin/main
git pull

# 2. Grant build permissions to your Compute Engine service account
gcloud projects add-iam-policy-binding antigravity-gdg-manila \
  --member="serviceAccount:791547156353-compute@developer.gserviceaccount.com" \
  --role="roles/storage.admin"

gcloud projects add-iam-policy-binding antigravity-gdg-manila \
  --member="serviceAccount:791547156353-compute@developer.gserviceaccount.com" \
  --role="roles/artifactregistry.writer"
```

---

### Step 2: Run the Deployment

Run the master deployment script and wait for it to reach **Step 8**:

```bash
chmod +x scripts/deploy.sh scripts/test_pipeline.sh
./scripts/deploy.sh
```

> [!NOTE]
> When prompted: `Do you want to continue (Y/n)?`, type `Y` and press Enter.
> Wait until you see: **"Pipeline Deployment Complete!"**.

---

### Step 3: Run the Live Pipeline Test

Run the automated verification script:

```bash
./scripts/test_pipeline.sh
```

**What this does automatically:**
1. Generates `test_contract_<timestamp>.txt` and `test_invoice_<timestamp>.pdf`.
2. Uploads them to `gs://antigravity-gdg-manila-docs-ingest/`.
3. Waits 8 seconds for the event-driven trigger (`GCS` → `Pub/Sub` → `Cloud Run` → `BigQuery`).
4. Queries BigQuery and prints the table with extracted tags and word counts.

---

### Step 4: Verify in Google Cloud Console (Optional)

1. **BigQuery**:
   * Open [console.cloud.google.com/bigquery](https://console.cloud.google.com/bigquery).
   * Expand `antigravity-gdg-manila` > `document_analytics` > `processed_documents`.
   * Click **Query** to see the extracted records.

2. **Cloud Run**:
   * Open [console.cloud.google.com/run](https://console.cloud.google.com/run).
   * Click `doc-processor-service` > **Logs** to view execution events.

---

### Step 5: Clean Up Resources (When Workshop Ends)

To prevent any future resource usage:

```bash
chmod +x scripts/teardown.sh
./scripts/teardown.sh
```

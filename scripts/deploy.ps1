<#
.SYNOPSIS
    Serverless Event-Driven Document Processing Pipeline Deployment Script (PowerShell)
    GDG Manila Workshop
.DESCRIPTION
    Provisions and configures:
    1. GCP API Services (Cloud Run, Storage, Pub/Sub, BigQuery, BigQuery Storage)
    2. Cloud Storage Ingestion Bucket
    3. BigQuery Dataset and Table with Storage Write API schema
    4. Service Accounts (Cloud Run & Pub/Sub Invoker) with IAM permissions
    5. Cloud Run Service deployment
    6. Pub/Sub Topics (Main & Dead-Letter Queue DLQ)
    7. Pub/Sub Push Subscription with OIDC Authentication & Exponential Backoff
    8. GCS Bucket Notification Trigger
#>

[CmdletBinding()]
param(
    [string]$ProjectId = $env:PROJECT_ID,
    [string]$Region = "asia-southeast1",
    [string]$ServiceName = "doc-processor-service",
    [string]$BucketName = "",
    [string]$TopicName = "doc-processing-topic",
    [string]$DlqTopicName = "doc-processing-dlq",
    [string]$DlqSubName = "doc-processing-dlq-sub",
    [string]$SubName = "doc-processing-push-sub",
    [string]$DatasetId = "document_analytics",
    [string]$TableId = "processed_documents"
)

$ErrorActionPreference = "Stop"

if (-not $ProjectId) {
    $ProjectId = (gcloud config get-value project 2>$null)
}

if (-not $ProjectId) {
    Write-Error "PROJECT_ID is empty. Run 'gcloud config set project <your-project-id>' or pass -ProjectId parameter."
    exit 1
}

if (-not $BucketName) {
    $BucketName = "$ProjectId-docs-ingest"
}

Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host " Starting Document Processing Pipeline Deployment" -ForegroundColor Cyan
Write-Host " Project ID:    $ProjectId"
Write-Host " Region:        $Region"
Write-Host " GCS Bucket:    gs://$BucketName"
Write-Host " BigQuery:      $DatasetId.$TableId"
Write-Host " Cloud Run:     $ServiceName"
Write-Host "==============================================================================" -ForegroundColor Cyan

$ProjectNumber = (gcloud projects describe $ProjectId --format="value(projectNumber)")
$RunSa = "doc-runner-sa@$ProjectId.iam.gserviceaccount.com"
$InvokerSa = "pubsub-invoker-sa@$ProjectId.iam.gserviceaccount.com"
$PubsubAgent = "service-$ProjectNumber@gcp-sa-pubsub.iam.gserviceaccount.com"

# 1. Enable Required GCP APIs
Write-Host "`n--> [1/8] Enabling Google Cloud Services..." -ForegroundColor Yellow
gcloud services enable `
    run.googleapis.com `
    storage.googleapis.com `
    pubsub.googleapis.com `
    bigquery.googleapis.com `
    bigquerystorage.googleapis.com `
    cloudbuild.googleapis.com `
    artifactregistry.googleapis.com `
    --project=$ProjectId

# 2. Create Cloud Storage Bucket
Write-Host "`n--> [2/8] Creating Cloud Storage Bucket gs://$BucketName..." -ForegroundColor Yellow
$bucketExists = gcloud storage buckets describe "gs://$BucketName" --project=$ProjectId 2>$null
if (-not $bucketExists) {
    gcloud storage buckets create "gs://$BucketName" --project=$ProjectId --location=$Region --uniform-bucket-level-access
} else {
    Write-Host "Bucket gs://$BucketName already exists." -ForegroundColor Gray
}

# 3. Create BigQuery Dataset and Table
Write-Host "`n--> [3/8] Creating BigQuery Dataset & Table..." -ForegroundColor Yellow
$datasetExists = bq show "$($ProjectId):$DatasetId" 2>$null
if (-not $datasetExists) {
    bq --location=$Region mk --dataset "$($ProjectId):$DatasetId"
}

$tableExists = bq show "$($ProjectId):$DatasetId.$TableId" 2>$null
if (-not $tableExists) {
    $SchemaPath = Join-Path $PSScriptRoot "..\app\schema.json"
    bq mk --table "$($ProjectId):$DatasetId.$TableId" "$SchemaPath"
} else {
    Write-Host "Table $DatasetId.$TableId already exists." -ForegroundColor Gray
}

# 4. Service Accounts and IAM Roles
Write-Host "`n--> [4/8] Configuring Service Accounts & IAM permissions..." -ForegroundColor Yellow
$runSaExists = gcloud iam service-accounts describe $RunSa --project=$ProjectId 2>$null
if (-not $runSaExists) {
    gcloud iam service-accounts create "doc-runner-sa" --display-name="Cloud Run Document Processor SA" --project=$ProjectId
}

# Grant Cloud Run SA GCS read and BigQuery write roles
gcloud projects add-iam-policy-binding $ProjectId --member="serviceAccount:$RunSa" --role="roles/storage.objectViewer" | Out-Null
gcloud projects add-iam-policy-binding $ProjectId --member="serviceAccount:$RunSa" --role="roles/bigquery.dataEditor" | Out-Null
gcloud projects add-iam-policy-binding $ProjectId --member="serviceAccount:$RunSa" --role="roles/bigquery.jobUser" | Out-Null

$invokerSaExists = gcloud iam service-accounts describe $InvokerSa --project=$ProjectId 2>$null
if (-not $invokerSaExists) {
    gcloud iam service-accounts create "pubsub-invoker-sa" --display-name="Pub/Sub Cloud Run Invoker SA" --project=$ProjectId
}

# Grant default Compute SA storage and build permissions for Cloud Build
gcloud projects add-iam-policy-binding $ProjectId --member="serviceAccount:$ProjectNumber-compute@developer.gserviceaccount.com" --role="roles/storage.admin" | Out-Null
gcloud projects add-iam-policy-binding $ProjectId --member="serviceAccount:$ProjectNumber-compute@developer.gserviceaccount.com" --role="roles/artifactregistry.writer" | Out-Null
gcloud projects add-iam-policy-binding $ProjectId --member="serviceAccount:$ProjectNumber-compute@developer.gserviceaccount.com" --role="roles/cloudbuild.builds.builder" | Out-Null


# 5. Build and Deploy Cloud Run Service
Write-Host "`n--> [5/8] Deploying Cloud Run Service $ServiceName..." -ForegroundColor Yellow
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")

gcloud run deploy $ServiceName `
    --source="$ProjectRoot" `
    --region=$Region `
    --project=$ProjectId `
    --service-account=$RunSa `
    --set-env-vars="PROJECT_ID=$ProjectId,REGION=$Region,GCS_BUCKET_NAME=$BucketName,BQ_DATASET_ID=$DatasetId,BQ_TABLE_ID=$TableId,MOCK_GCP=false" `
    --no-allow-unauthenticated

$CloudRunUrl = (gcloud run services describe $ServiceName --platform=managed --region=$Region --project=$ProjectId --format="value(status.url)")
Write-Host "Cloud Run deployed at: $CloudRunUrl" -ForegroundColor Green

# Grant Invoker SA run.invoker role
gcloud run services add-iam-policy-binding $ServiceName `
    --region=$Region `
    --project=$ProjectId `
    --member="serviceAccount:$InvokerSa" `
    --role="roles/run.invoker" | Out-Null

# 6. Create Pub/Sub Topics & DLQ
Write-Host "`n--> [6/8] Configuring Pub/Sub Topics & DLQ..." -ForegroundColor Yellow
if (-not (gcloud pubsub topics describe $TopicName --project=$ProjectId 2>$null)) {
    gcloud pubsub topics create $TopicName --project=$ProjectId
}

if (-not (gcloud pubsub topics describe $DlqTopicName --project=$ProjectId 2>$null)) {
    gcloud pubsub topics create $DlqTopicName --project=$ProjectId
}

if (-not (gcloud pubsub subscriptions describe $DlqSubName --project=$ProjectId 2>$null)) {
    gcloud pubsub subscriptions create $DlqSubName --topic=$DlqTopicName --project=$ProjectId
}

# Grant Pub/Sub agent publisher permission on DLQ
gcloud pubsub topics add-iam-policy-binding $DlqTopicName `
    --member="serviceAccount:$PubsubAgent" `
    --role="roles/pubsub.publisher" `
    --project=$ProjectId | Out-Null

# 7. Create Pub/Sub Push Subscription
Write-Host "`n--> [7/8] Creating Push Subscription with OIDC & Exponential Backoff..." -ForegroundColor Yellow
$PushEndpoint = "$CloudRunUrl/process"

if (gcloud pubsub subscriptions describe $SubName --project=$ProjectId 2>$null) {
    gcloud pubsub subscriptions delete $SubName --project=$ProjectId --quiet
}

gcloud pubsub subscriptions create $SubName `
    --topic=$TopicName `
    --project=$ProjectId `
    --push-endpoint=$PushEndpoint `
    --push-auth-service-account=$InvokerSa `
    --dead-letter-topic=$DlqTopicName `
    --max-delivery-attempts=5 `
    --min-retry-delay=10s `
    --max-retry-delay=600s `
    --ack-deadline=60

gcloud pubsub subscriptions add-iam-policy-binding $SubName `
    --member="serviceAccount:$PubsubAgent" `
    --role="roles/pubsub.subscriber" `
    --project=$ProjectId | Out-Null

# 8. Create GCS Notification Trigger
Write-Host "`n--> [8/8] Creating GCS Bucket Notification..." -ForegroundColor Yellow
$existingNotifs = (gcloud storage buckets notifications list "gs://$BucketName" --format="value(topic)" 2>$null)

if ($existingNotifs -notcontains $TopicName) {
    gcloud storage buckets notifications create "gs://$BucketName" `
        --topic=$TopicName `
        --event-types="OBJECT_FINALIZE" `
        --payload-format="json"
    Write-Host "Configured GCS notification trigger." -ForegroundColor Green
} else {
    Write-Host "Notification trigger already exists." -ForegroundColor Gray
}

Write-Host "`n==============================================================================" -ForegroundColor Green
Write-Host " Pipeline Deployment Complete!" -ForegroundColor Green
Write-Host " Bucket:      gs://$BucketName"
Write-Host " Main Topic:  $TopicName"
Write-Host " DLQ Topic:   $DlqTopicName"
Write-Host " Cloud Run:   $PushEndpoint"
Write-Host " BigQuery:    $ProjectId.$DatasetId.$TableId"
Write-Host "==============================================================================" -ForegroundColor Green

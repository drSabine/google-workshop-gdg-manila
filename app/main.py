"""FastAPI Cloud Run Service for Event-Driven Document Processing.
Receives Cloud Storage OBJECT_FINALIZE events via Pub/Sub Push Subscription,
processes documents with simulated OCR, and streams metadata to BigQuery.
"""

import base64
import json
import logging
import os
from typing import Dict, Any, Optional, List
from fastapi import FastAPI, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.config import settings
from app.ocr_processor import DocumentOCRProcessor
from app.bq_writer import BigQueryStorageWriter

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] [%(name)s]: %(message)s"
)
logger = logging.getLogger("document_processor.api")

app = FastAPI(
    title="GDG Serverless Document Processing Pipeline",
    description="Event-driven Cloud Storage -> Cloud Pub/Sub -> Cloud Run -> BigQuery Storage Write API",
    version="1.0.0"
)

# Instantiate core pipeline services
ocr_processor = DocumentOCRProcessor(mock_mode=settings.mock_gcp)
bq_writer = BigQueryStorageWriter(
    project_id=settings.project_id,
    dataset_id=settings.bq_dataset,
    table_id=settings.bq_table,
    mock_mode=settings.mock_gcp
)


# Pydantic models for Cloud Pub/Sub Push Subscription format
class PubSubMessage(BaseModel):
    attributes: Optional[Dict[str, str]] = Field(default_factory=dict)
    data: Optional[str] = None
    messageId: Optional[str] = None
    publishTime: Optional[str] = None


class PubSubPushEnvelope(BaseModel):
    message: PubSubMessage
    subscription: Optional[str] = None


class SimulateUploadRequest(BaseModel):
    bucket_name: Optional[str] = None
    filename: str
    sample_text: Optional[str] = None


@app.get("/", tags=["Monitoring"])
def root():
    """Service status and pipeline configuration overview."""
    return {
        "service": "gdg-document-processing-pipeline",
        "status": "online",
        "mock_gcp": settings.mock_gcp,
        "config": {
            "project_id": settings.project_id,
            "region": settings.region,
            "bucket_name": settings.bucket_name,
            "bq_dataset": settings.bq_dataset,
            "bq_table": settings.bq_table
        },
        "endpoints": {
            "health": "/health",
            "pubsub_push_handler": "/api/v1/process-event",
            "simulation_test": "/api/v1/simulate-upload",
            "mock_records": "/api/v1/mock-records"
        }
    }


@app.get("/health", tags=["Monitoring"])
def health_check():
    """Liveness & readiness probe for Cloud Run."""
    return {"status": "healthy", "service": "document-processor"}


@app.post("/api/v1/process-event", status_code=status.HTTP_200_OK, tags=["Pipeline Trigger"])
async def handle_pubsub_event(envelope: PubSubPushEnvelope):
    """Primary handler for Pub/Sub Push Subscription.

    Receives Cloud Storage notifications (OBJECT_FINALIZE), downloads the document,
    runs OCR metadata extraction, and streams results into BigQuery via the Storage Write API.
    """
    message = envelope.message
    attrs = message.attributes or {}
    logger.info("Received Pub/Sub message ID: %s, attributes: %s", message.messageId, attrs)

    # 1. Inspect Event Type (Cloud Storage sends eventType in attributes)
    event_type = attrs.get("eventType", "")
    if event_type and event_type != "OBJECT_FINALIZE":
        logger.info("Skipping non-finalize event: '%s'. Acknowledging message.", event_type)
        return {"status": "skipped", "reason": f"Ignored event type: {event_type}"}

    # 2. Extract Bucket and Object name
    bucket_name = attrs.get("bucketId")
    object_name = attrs.get("objectId")

    # If not present in attributes, decode message payload data
    if (not bucket_name or not object_name) and message.data:
        try:
            decoded_bytes = base64.b64decode(message.data)
            payload_json = json.loads(decoded_bytes.decode("utf-8"))
            bucket_name = bucket_name or payload_json.get("bucket")
            object_name = object_name or payload_json.get("name")
            logger.info("Parsed GCS notification data from base64 payload: bucket=%s, object=%s", bucket_name, object_name)
        except Exception as e:
            logger.warning("Could not decode Pub/Sub data payload as JSON: %s", e)

    # Fallback to configured default bucket if not specified
    bucket_name = bucket_name or settings.bucket_name

    if not object_name:
        logger.error("No valid objectId found in Pub/Sub message. Acknowledging to avoid poison pill.")
        return {"status": "ignored", "reason": "No objectId in event"}

    # Ignore directory creation / placeholder events in GCS (ending with '/')
    if object_name.endswith("/"):
        logger.info("Ignoring folder marker object: %s", object_name)
        return {"status": "ignored", "reason": "Directory marker"}

    try:
        logger.info("Starting processing pipeline for file: gs://%s/%s", bucket_name, object_name)

        # 3. OCR and Metadata Extraction
        metadata = ocr_processor.extract_metadata(bucket_name, object_name)

        # 4. Stream Metadata to BigQuery via Storage Write API
        bq_writer.write_record(metadata)

        logger.info(
            "Document pipeline completed successfully for gs://%s/%s (words=%d, tags=%s)",
            bucket_name,
            object_name,
            metadata["word_count"],
            metadata["tags"]
        )

        return {
            "status": "success",
            "message": "Document processed and streamed to BigQuery",
            "metadata": metadata
        }

    except Exception as e:
        logger.exception("Error processing document %s: %s", object_name, str(e))
        # Returning HTTP 500 signals Pub/Sub that delivery failed, triggering exponential backoff
        # and forwarding to Dead-Letter Queue (DLQ) if max retries are exceeded.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Pipeline processing failed: {str(e)}"
        )


@app.post("/api/v1/simulate-upload", tags=["Testing & Simulation"])
def simulate_upload(req: SimulateUploadRequest):
    """Directly triggers document processing and BigQuery streaming without needing a real GCS upload.

    Ideal for live GDG workshops, development testing, and verification.
    """
    bucket = req.bucket_name or settings.bucket_name
    content_bytes = req.sample_text.encode("utf-8") if req.sample_text else None

    metadata = ocr_processor.extract_metadata(
        bucket_name=bucket,
        object_name=req.filename,
        content_bytes=content_bytes
    )
    bq_writer.write_record(metadata)

    return {
        "status": "simulated_success",
        "processed_file": req.filename,
        "bucket": bucket,
        "metadata": metadata
    }


@app.get("/api/v1/mock-records", tags=["Testing & Simulation"])
def get_mock_records():
    """Retrieve locally streamed BigQuery records generated during simulation mode."""
    mock_file = bq_writer.mock_output_path
    if not os.path.exists(mock_file):
        return {"records": [], "count": 0, "message": "No mock records written yet."}

    records = []
    with open(mock_file, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line.strip()))

    return {
        "records": records,
        "count": len(records),
        "file_path": mock_file
    }

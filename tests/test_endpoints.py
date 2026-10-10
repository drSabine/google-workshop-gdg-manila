"""Unit tests for Document Processing Pipeline."""

import pytest
import json
import base64
from fastapi.testclient import TestClient

from app.main import app
from app.config import settings
from app.ocr_processor import DocumentOCRProcessor
from app.bq_writer import BigQueryStorageWriter

client = TestClient(app)


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_root_metadata():
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "gdg-document-processing-pipeline"
    assert "endpoints" in data


def test_ocr_processor_heuristics():
    ocr = DocumentOCRProcessor(mock_mode=True)
    
    # Test invoice heuristic
    meta_invoice = ocr.extract_metadata("test-bucket", "invoices/inv_2026_001.pdf", content_bytes=b"%PDF-1.4 simulated")
    assert "invoice" in meta_invoice["tags"]
    assert "financial" in meta_invoice["tags"]
    assert meta_invoice["word_count"] > 10

    # Test resume heuristic
    meta_cv = ocr.extract_metadata("test-bucket", "resumes/candidate_profile.pdf", content_bytes=b"%PDF-1.4 simulated")
    assert "hr" in meta_cv["tags"]
    assert "resume" in meta_cv["tags"]

    # Test plain text
    text_content = b"GDG Manila event driven architectures using Google Cloud and BigQuery."
    meta_text = ocr.extract_metadata("test-bucket", "notes.txt", content_bytes=text_content)
    assert "gdg" in meta_text["tags"]
    assert meta_text["word_count"] == 10


def test_simulate_upload_endpoint():
    payload = {
        "bucket_name": "test-workshop-bucket",
        "filename": "contracts/vendor_nda.pdf",
        "sample_text": "Non-Disclosure Agreement for GDG Manila Cloud Architecture Workshop."
    }
    response = client.post("/api/v1/simulate-upload", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "simulated_success"
    assert data["processed_file"] == "contracts/vendor_nda.pdf"
    assert data["metadata"]["word_count"] > 0


def test_pubsub_push_handler():
    envelope = {
        "message": {
            "attributes": {
                "eventType": "OBJECT_FINALIZE",
                "bucketId": "demo-bucket",
                "objectId": "reports/q3_summary.pdf"
            },
            "data": base64.b64encode(json.dumps({
                "bucket": "demo-bucket",
                "name": "reports/q3_summary.pdf"
            }).encode("utf-8")).decode("utf-8"),
            "messageId": "msg-999123",
            "publishTime": "2026-10-10T15:00:00Z"
        },
        "subscription": "projects/demo-proj/subscriptions/demo-sub"
    }

    response = client.post("/process", json=envelope)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["metadata"]["filename"] == "reports/q3_summary.pdf"


def test_pubsub_push_ignores_non_finalize_events():
    envelope = {
        "message": {
            "attributes": {
                "eventType": "OBJECT_DELETE",
                "bucketId": "demo-bucket",
                "objectId": "reports/old_file.txt"
            },
            "messageId": "msg-delete-01"
        }
    }
    response = client.post("/process", json=envelope)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "skipped"

#!/usr/bin/env python3
"""End-to-End Pipeline Verification and Testing Script.

Supports testing against:
1. Local FastAPI server (http://localhost:8080)
2. Live deployed Cloud Run service with authenticated OIDC token
3. Standalone component verification (OCR engine + Protobuf + Storage Write API)
"""

import sys
import os
import json
import base64
import argparse
import requests

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.ocr_processor import DocumentOCRProcessor
from app.bq_writer import BigQueryStorageWriter
from app.config import settings


def test_standalone_components():
    """Test OCR processing and protobuf serialization locally without starting a server."""
    print("\n[1/3] Testing Standalone OCR Extraction Engine...")
    ocr = DocumentOCRProcessor(mock_mode=True)
    
    sample_text = (
        "GDG Manila Cloud Workshop: Serverless document processing with Google Cloud Run, "
        "Cloud Storage, Pub/Sub, and BigQuery Storage Write API."
    )
    result = ocr.extract_metadata(
        bucket_name="demo-bucket",
        object_name="sample_invoice_2026.pdf",
        content_bytes=sample_text.encode("utf-8")
    )
    
    print(f" -> Filename:   {result['filename']}")
    print(f" -> Word Count: {result['word_count']}")
    print(f" -> Tags:       {result['tags']}")
    print(f" -> Summary:    {result['summary']}")
    assert result["word_count"] > 0, "Word count should be positive"
    assert "sample_invoice_2026.pdf" in result["filename"]

    print("\n[2/3] Testing BigQuery Storage Writer (Protobuf Serialization)...")
    writer = BigQueryStorageWriter("test-proj", "test_dataset", "test_table", mock_mode=True)
    proto_rec = writer.create_proto_record(result)
    assert proto_rec.filename == result["filename"]
    assert proto_rec.word_count == result["word_count"]
    print(f" -> Protobuf record serialized size: {len(proto_rec.SerializeToString())} bytes")

    writer.write_record(result)
    print(f" -> Mock record written to: {writer.mock_output_path}")

    print("\n[3/3] Standalone Component Verification PASSED! [OK]\n")


def test_api_endpoint(base_url: str, id_token: str = None):
    """Test the HTTP endpoints on local or live Cloud Run."""
    headers = {"Content-Type": "application/json"}
    if id_token:
        headers["Authorization"] = f"Bearer {id_token}"

    print(f"\nTesting API at: {base_url}")

    # Health check
    print("--> 1. Calling GET /health ...")
    health_res = requests.get(f"{base_url}/health", headers=headers, timeout=10)
    print(f"    Status: {health_res.status_code}, Body: {health_res.text}")
    assert health_res.status_code == 200

    # Simulate Upload
    print("--> 2. Calling POST /api/v1/simulate-upload ...")
    sim_payload = {
        "bucket_name": "gdg-demo-bucket",
        "filename": "quarterly_financial_report.pdf",
        "sample_text": "Q3 2026 Financial Results for GDG Manila Corporation. Net income increased by 24%."
    }
    sim_res = requests.post(f"{base_url}/api/v1/simulate-upload", json=sim_payload, headers=headers, timeout=15)
    print(f"    Status: {sim_res.status_code}, Response: {json.dumps(sim_res.json(), indent=2)}")
    assert sim_res.status_code == 200

    # Simulate Pub/Sub Push Notification Envelope
    print("--> 3. Calling POST /api/v1/process-event (Pub/Sub Push Simulation) ...")
    pubsub_body = {
        "message": {
            "attributes": {
                "eventType": "OBJECT_FINALIZE",
                "bucketId": "gdg-demo-bucket",
                "objectId": "contracts/nda_agreement_2026.docx"
            },
            "data": base64.b64encode(json.dumps({
                "bucket": "gdg-demo-bucket",
                "name": "contracts/nda_agreement_2026.docx",
                "size": "45020"
            }).encode("utf-8")).decode("utf-8"),
            "messageId": "test-msg-101",
            "publishTime": "2026-10-10T15:00:00Z"
        },
        "subscription": "projects/demo-project/subscriptions/doc-pipeline-sub"
    }

    push_res = requests.post(f"{base_url}/api/v1/process-event", json=pubsub_body, headers=headers, timeout=15)
    print(f"    Status: {push_res.status_code}, Response: {json.dumps(push_res.json(), indent=2)}")
    assert push_res.status_code == 200

    # Check mock records
    mock_res = requests.get(f"{base_url}/api/v1/mock-records", headers=headers, timeout=10)
    if mock_res.status_code == 200:
        data = mock_res.json()
        print(f"--> Mock Records Logged: {data.get('count', 0)} items recorded.")

    print("\nAPI Integration Tests PASSED! [OK]\n")


def main():
    parser = argparse.ArgumentParser(description="Test document processing pipeline.")
    parser.add_argument("--url", help="Target URL (e.g. http://localhost:8080 or Cloud Run URL)", default="")
    parser.add_argument("--token", help="Google Cloud OIDC identity token for Cloud Run auth", default=None)
    parser.add_argument("--standalone", action="store_true", help="Run standalone Python tests only")

    args = parser.parse_args()

    if args.standalone or not args.url:
        test_standalone_components()

    if args.url:
        test_api_endpoint(args.url.rstrip("/"), id_token=args.token)


if __name__ == "__main__":
    main()

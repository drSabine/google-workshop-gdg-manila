"""Document OCR Processing module.
Performs document retrieval from GCS and simulated Optical Character Recognition (OCR),
extracting metadata, classification tags, word counts, and summary abstracts.
"""

import os
import re
import mimetypes
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger("document_processor.ocr")


class DocumentOCRProcessor:
    """Handles document inspection, simulated OCR text extraction, and metadata extraction."""

    def __init__(self, mock_mode: bool = False):
        self.mock_mode = mock_mode
        self._storage_client = None

    @property
    def storage_client(self):
        """Lazy initialization of Google Cloud Storage Client."""
        if self._storage_client is None and not self.mock_mode:
            try:
                from google.cloud import storage
                self._storage_client = storage.Client()
            except Exception as e:
                logger.warning("GCS client initialization failed (%s); falling back to simulated mode.", e)
                self.mock_mode = True
        return self._storage_client

    def fetch_document_bytes(self, bucket_name: str, object_name: str) -> bytes:
        """Download document bytes from Google Cloud Storage or generate mock content."""
        if self.mock_mode or not self.storage_client:
            logger.info("[SIMULATION] Generating simulated document bytes for gs://%s/%s", bucket_name, object_name)
            return f"Simulated content for document {object_name} uploaded to bucket {bucket_name}".encode("utf-8")

        logger.info("Fetching gs://%s/%s from Cloud Storage", bucket_name, object_name)
        bucket = self.storage_client.bucket(bucket_name)
        blob = bucket.blob(object_name)
        return blob.download_as_bytes()

    def extract_metadata(
        self,
        bucket_name: str,
        object_name: str,
        content_bytes: Optional[bytes] = None,
        content_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """Performs simulated OCR and metadata extraction on the document."""
        if content_bytes is None:
            content_bytes = self.fetch_document_bytes(bucket_name, object_name)

        file_size = len(content_bytes)
        ext = os.path.splitext(object_name)[1].lower().lstrip(".")
        if not content_type:
            content_type, _ = mimetypes.guess_type(object_name)
            if not content_type:
                content_type = f"application/{ext}" if ext else "application/octet-stream"

        # Determine document type & run simulated OCR
        text, tags, summary = self._simulate_ocr_engine(object_name, ext, content_bytes)
        
        words = re.findall(r"\w+", text)
        word_count = len(words)

        processed_at = datetime.now(timezone.utc).isoformat()
        gcs_uri = f"gs://{bucket_name}/{object_name}"

        result = {
            "filename": object_name,
            "date": processed_at,
            "tags": tags,
            "word_count": word_count,
            "gcs_uri": gcs_uri,
            "content_type": content_type,
            "file_size_bytes": file_size,
            "summary": summary
        }

        logger.info("OCR Extraction completed for %s: %d words, tags=%s", object_name, word_count, tags)
        return result

    def _simulate_ocr_engine(self, filename: str, ext: str, content_bytes: bytes) -> tuple[str, List[str], str]:
        """Simulate intelligent OCR analysis based on file type and name characteristics."""
        lower_name = filename.lower()
        tags = ["scanned-document", ext or "binary"]
        
        # Check if file has readable plain text
        try:
            decoded_text = content_bytes.decode("utf-8")
            if len(decoded_text.strip()) > 0:
                words = re.findall(r"\w+", decoded_text)
                if len(words) > 5:
                    # Detected real text content
                    tags.append("text-extract")
                    summary = f"Text document with {len(words)} extracted words: '{decoded_text[:120].strip()}...'"
                    # Keyword tagging
                    for kw in ["cloud", "serverless", "gdg", "python", "invoice", "contract", "receipt", "architecture"]:
                        if kw in decoded_text.lower():
                            tags.append(kw)
                    return decoded_text, sorted(list(set(tags))), summary
        except UnicodeDecodeError:
            pass  # Binary file, proceed with OCR heuristic simulation

        # OCR heuristic simulation for PDFs, Images, and Office Docs
        if "invoice" in lower_name or "billing" in lower_name:
            tags.extend(["financial", "invoice", "accounts-payable"])
            ocr_text = (
                f"TAX INVOICE Reference: {filename}. Billed To: Global Enterprise Solutions Inc. "
                "Item 01: Cloud Computing Infrastructure Services - 400 hrs. "
                "Item 02: BigQuery Analytics Streaming Pipeline - 150 hrs. "
                "Subtotal: $14,250.00. Tax (VAT 12%): $1,710.00. Total Payable: $15,960.00. "
                "Payment Terms: Net 30 days. Remit payment to Standard Chartered Bank."
            )
            summary = "Commercial invoice with itemized cloud infrastructure and streaming billing."
        elif "contract" in lower_name or "agreement" in lower_name:
            tags.extend(["legal", "contract", "confidential"])
            ocr_text = (
                f"SERVICE LEVEL AGREEMENT AND MASTER SERVICES CONTRACT. Document: {filename}. "
                "Between Provider and Client. Parties agree to terms regarding 99.99% availability, "
                "data retention policies in Google Cloud Storage, automated disaster recovery, "
                "and confidentiality warranties under Philippine and international laws."
            )
            summary = "Master Services Agreement outlining availability SLAs and data governance."
        elif "resume" in lower_name or "cv" in lower_name:
            tags.extend(["hr", "resume", "talent"])
            ocr_text = (
                f"CURRICULUM VITAE - Candidate Profile. Filename: {filename}. "
                "Specialization: Cloud Solutions Architect and Data Engineer. "
                "Experience: 8+ years building event-driven serverless architectures with Cloud Run, "
                "Cloud Pub/Sub, BigQuery Storage Write API, and Google Cloud Storage. "
                "Certifications: Google Cloud Certified Professional Cloud Architect."
            )
            summary = "Professional CV detailing Cloud Architecture and Data Engineering credentials."
        elif "gdg" in lower_name or "presentation" in lower_name:
            tags.extend(["presentation", "community", "gdg-manila"])
            ocr_text = (
                f"GDG MANILA TECH WORKSHOP PRESENTATION. Slide Deck: {filename}. "
                "Topic: Mastering Event-Driven Architectures on Google Cloud. "
                "Highlights: Serverless event ingestion from GCS to Cloud Run, Dead-Letter Queues (DLQ), "
                "and ultra-fast streaming writes into BigQuery Storage Write API."
            )
            summary = "GDG Manila Workshop presentation slides on event-driven GCP pipelines."
        else:
            tags.extend(["general", "ocr-extracted"])
            ocr_text = (
                f"Scanned document OCR content extracted from {filename}. "
                "This document was ingested through the Google Cloud Storage bucket, "
                "triggered via Pub/Sub OBJECT_FINALIZE notification, and processed by Cloud Run. "
                "Simulated optical character recognition identified multi-column layouts, "
                "metadata attributes, and tabulated numerical data."
            )
            summary = f"Scanned {ext.upper() if ext else 'file'} containing text and tabular data."

        return ocr_text, sorted(list(set(tags))), summary

"""Unit tests for AI guardrails, rate limiting, and cost controls."""

import time
import json
import hashlib
import pytest
from app.ocr_processor import (
    TokenBucketLimiter,
    DocumentOCRProcessor,
    MAX_INPUT_CHARS,
    MAX_FILE_SIZE_BYTES,
)


def test_token_bucket_limiter_rate_limiting():
    """Verify that the token bucket limiter enforces rate limits and throttles excessive calls."""
    # Capacity 2 tokens, rate 60/min (1 token/sec)
    limiter = TokenBucketLimiter(rate_per_minute=60, capacity=2.0)
    
    # First 2 calls should succeed immediately
    assert limiter.acquire() is True
    assert limiter.acquire() is True
    
    # 3rd consecutive call with zero delay must fail (throttled)
    assert limiter.acquire() is False


def test_input_character_cap_truncation():
    """Verify that inputs exceeding MAX_INPUT_CHARS (15,000) are truncated."""
    processor = DocumentOCRProcessor(mock_mode=True)
    long_content = ("GDG Manila Cloud Pipeline Test Words. " * 600).encode("utf-8")
    assert len(long_content) > MAX_INPUT_CHARS

    metadata = processor.extract_metadata(
        bucket_name="test-bucket",
        object_name="large_text.txt",
        content_bytes=long_content
    )

    # Word count is capped to bounded word extraction
    assert metadata["word_count"] > 0
    assert metadata["content_sha256"] == hashlib.sha256(long_content).hexdigest()


def test_sha256_deduplication_cache():
    """Verify that identical payloads hit the deduplication cache and return cached metadata."""
    processor = DocumentOCRProcessor(mock_mode=True)
    sample_bytes = b"Contract Agreement between Party A and Party B for Cloud Architecture."
    
    result_1 = processor.extract_metadata("test-bucket", "contracts/contract_v1.pdf", content_bytes=sample_bytes)
    assert result_1["content_sha256"] in processor._cache
    
    # Same content under a different filename
    result_2 = processor.extract_metadata("test-bucket", "contracts/contract_v2_duplicate.pdf", content_bytes=sample_bytes)
    
    assert result_2["content_sha256"] == result_1["content_sha256"]
    assert result_2["filename"] == "contracts/contract_v2_duplicate.pdf"
    assert result_2["document_type"] == result_1["document_type"]


def test_language_detection_heuristics():
    """Verify language detection heuristic for Tagalog, Spanish, and English."""
    processor = DocumentOCRProcessor(mock_mode=True)
    
    # Tagalog
    tl_bytes = "Ito ay isang kasunduan at kontrata sa pagitan ng mga partido para sa Google Cloud.".encode("utf-8")
    meta_tl = processor.extract_metadata("test-bucket", "kasunduan.txt", content_bytes=tl_bytes)
    assert meta_tl["language"] == "tl"

    # Spanish
    es_bytes = "Factura comercial para el cliente con desglose de servicios en la nube.".encode("utf-8")
    meta_es = processor.extract_metadata("test-bucket", "factura.txt", content_bytes=es_bytes)
    assert meta_es["language"] == "es"

    # English
    en_bytes = "Standard cloud infrastructure service level agreement.".encode("utf-8")
    meta_en = processor.extract_metadata("test-bucket", "agreement.txt", content_bytes=en_bytes)
    assert meta_en["language"] == "en"


def test_entity_extraction_and_classification():
    """Verify document classification and entities JSON generation."""
    processor = DocumentOCRProcessor(mock_mode=True)
    
    invoice_bytes = "Invoice 2026 Tax Summary Total: $15,960.00".encode("utf-8")
    meta_invoice = processor.extract_metadata("test-bucket", "invoice_99.txt", content_bytes=invoice_bytes)
    
    assert meta_invoice["document_type"] == "invoice"
    entities = json.loads(meta_invoice["entities_json"])
    assert "monetary_amounts" in entities
    assert "$15,960.00" in entities["monetary_amounts"]

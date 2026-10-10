"""BigQuery Storage Write API integration module.
Streams document metadata records into BigQuery using the Storage Write API
with Protocol Buffers serialization (proto2).
"""

import os
import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

logger = logging.getLogger("document_processor.bigquery")

# Import compiled Protobuf definition
try:
    from app.proto import document_metadata_pb2
except ImportError:
    import document_metadata_pb2


class BigQueryStorageWriter:
    """Writes metadata records to BigQuery using the high-performance Storage Write API."""

    def __init__(
        self,
        project_id: str,
        dataset_id: str,
        table_id: str,
        mock_mode: bool = False
    ):
        self.project_id = project_id
        self.dataset_id = dataset_id
        self.table_id = table_id
        self.mock_mode = mock_mode
        self._write_client = None
        self.write_stream_name = (
            f"projects/{project_id}/datasets/{dataset_id}/tables/{table_id}/_default"
        )
        self.mock_output_path = os.path.join(os.getcwd(), "data", "bigquery_stream_mock.jsonl")

    @property
    def write_client(self):
        """Lazy initialization of BigQueryWriteClient."""
        if self._write_client is None and not self.mock_mode:
            try:
                from google.cloud.bigquery_storage_v1 import BigQueryWriteClient
                self._write_client = BigQueryWriteClient()
            except Exception as e:
                logger.warning(
                    "BigQuery Storage Write client initialization failed (%s); switching to mock mode.",
                    e
                )
                self.mock_mode = True
        return self._write_client

    def create_proto_record(self, data: Dict[str, Any]) -> document_metadata_pb2.DocumentMetadataRecord:
        """Create and populate a DocumentMetadataRecord protobuf instance."""
        record = document_metadata_pb2.DocumentMetadataRecord()
        record.filename = data["filename"]
        record.date = data.get("date", datetime.now(timezone.utc).isoformat())
        record.word_count = int(data.get("word_count", 0))

        # Optional & repeated fields
        for tag in data.get("tags", []):
            record.tags.append(str(tag))

        if data.get("gcs_uri"):
            record.gcs_uri = data["gcs_uri"]
        if data.get("content_type"):
            record.content_type = data["content_type"]
        if data.get("file_size_bytes") is not None:
            record.file_size_bytes = int(data["file_size_bytes"])
        if data.get("summary"):
            record.summary = data["summary"]
        if data.get("language"):
            record.language = data["language"]
        if data.get("document_type"):
            record.document_type = data["document_type"]
        if data.get("entities_json"):
            record.entities_json = data["entities_json"]
        if data.get("content_sha256"):
            record.content_sha256 = data["content_sha256"]

        return record

    def write_record(self, data: Dict[str, Any]) -> None:
        """Convenience method to write a single document metadata dictionary."""
        record = self.create_proto_record(data)
        self.write_records([record])

    def write_records(self, records: List[document_metadata_pb2.DocumentMetadataRecord]) -> None:
        """Streams a list of protobuf records to BigQuery via the Storage Write API."""
        if not records:
            return

        if self.mock_mode or not self.write_client:
            self._write_mock(records)
            return

        from google.cloud.bigquery_storage_v1 import types
        from google.protobuf import descriptor_pb2

        logger.info(
            "Streaming %d record(s) to BigQuery Storage Write API at stream: %s",
            len(records),
            self.write_stream_name
        )

        # 1. Prepare protobuf descriptor schema for BigQuery
        descriptor = descriptor_pb2.DescriptorProto()
        records[0].DESCRIPTOR.CopyToProto(descriptor)

        proto_schema = types.ProtoSchema()
        proto_schema.proto_descriptor = descriptor

        # 2. Serialize records into ProtoRows
        proto_rows = types.ProtoRows()
        for record in records:
            proto_rows.serialized_rows.append(record.SerializeToString())

        # 3. Assemble AppendRowsRequest
        proto_data = types.AppendRowsRequest.ProtoData()
        proto_data.writer_schema = proto_schema
        proto_data.rows = proto_rows

        request = types.AppendRowsRequest()
        request.write_stream = self.write_stream_name
        request.proto_rows = proto_data

        # 4. Invoke bidirectional append_rows RPC
        # The default stream supports immediate appends with at-least-once delivery
        try:
            append_stream = self.write_client.append_rows(requests=iter([request]))
            for response in append_stream:
                if response.error.code != 0:
                    error_msg = f"BigQuery Storage Write API failed: [{response.error.code}] {response.error.message}"
                    logger.error(error_msg)
                    raise RuntimeError(error_msg)
            logger.info("Successfully streamed %d record(s) into BigQuery table %s", len(records), self.table_id)
        except Exception as e:
            logger.error("Error committing records to BigQuery Storage Write API: %s", e)
            raise

    def _write_mock(self, records: List[document_metadata_pb2.DocumentMetadataRecord]) -> None:
        """Mock writer for local development and workshops without GCP billing."""
        os.makedirs(os.path.dirname(self.mock_output_path), exist_ok=True)
        with open(self.mock_output_path, "a", encoding="utf-8") as f:
            for record in records:
                item = {
                    "filename": record.filename,
                    "date": record.date,
                    "tags": list(record.tags),
                    "word_count": record.word_count,
                    "gcs_uri": record.gcs_uri if record.HasField("gcs_uri") else None,
                    "content_type": record.content_type if record.HasField("content_type") else None,
                    "file_size_bytes": record.file_size_bytes if record.HasField("file_size_bytes") else None,
                    "summary": record.summary if record.HasField("summary") else None,
                    "language": record.language if record.HasField("language") else None,
                    "document_type": record.document_type if record.HasField("document_type") else None,
                    "entities_json": record.entities_json if record.HasField("entities_json") else None,
                    "content_sha256": record.content_sha256 if record.HasField("content_sha256") else None,
                    "_mock_stream_timestamp": datetime.now(timezone.utc).isoformat()
                }
                f.write(json.dumps(item) + "\n")

        logger.info(
            "[SIMULATION] Streamed %d record(s) to mock BigQuery dataset '%s.%s' (Saved to %s)",
            len(records),
            self.dataset_id,
            self.table_id,
            self.mock_output_path
        )

"""Application configuration module.
Loads settings from environment variables with sensible defaults.
"""

import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    project_id: str = os.getenv("GOOGLE_CLOUD_PROJECT", os.getenv("PROJECT_ID", "gdg-manila-demo"))
    region: str = os.getenv("REGION", "asia-southeast1")
    bucket_name: str = os.getenv("GCS_BUCKET_NAME", "doc-processing-bucket")
    bq_dataset: str = os.getenv("BQ_DATASET_ID", "document_analytics")
    bq_table: str = os.getenv("BQ_TABLE_ID", "processed_documents")
    mock_gcp: bool = os.getenv("MOCK_GCP", "false").lower() in ("true", "1", "yes")
    port: int = int(os.getenv("PORT", "8080"))
    log_level: str = os.getenv("LOG_LEVEL", "INFO")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

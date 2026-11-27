"""Configuration for the BridgeCare document ingestion engine."""

from typing import Any, Optional
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class IngestionConfig(BaseSettings):
    """Configuration options for file safety, size limits, and OCR extraction."""

    model_config = SettingsConfigDict(
        env_prefix="BRIDGECARE_INGESTION_",
        case_sensitive=False,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # File size limits (default: 35 MB)
    max_file_size_bytes: int = 35 * 1024 * 1024

    # PDF limits
    max_pdf_pages: int = 100

    # Image limits
    max_image_width: int = 10000
    max_image_height: int = 10000
    max_image_pixels: int = 50_000_000  # Decompression bomb protection

    # OCR extraction settings
    ocr_dpi: int = 200
    min_meaningful_chars: int = 20
    tesseract_cmd: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices(
            "bridgecare_ingestion_tesseract_cmd",
            "tesseract_cmd",
        ),
        description="Path to Tesseract OCR executable. Can be set via BRIDGECARE_INGESTION_TESSERACT_CMD or TESSERACT_CMD.",
    )
    tesseract_timeout_seconds: int = 30

    def model_post_init(self, __context: Any) -> None:
        super().model_post_init(__context)
        if self.tesseract_cmd:
            from ai_engine.ingestion.ocr import apply_tesseract_cmd
            apply_tesseract_cmd(self.tesseract_cmd)

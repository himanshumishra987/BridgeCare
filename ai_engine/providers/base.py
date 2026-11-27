from abc import ABC, abstractmethod
from typing import Any


class AIProvider(ABC):
    """Base interface for all BridgeCare AI providers."""

    @abstractmethod
    async def classify_document(self, document_text: str) -> dict[str, Any]:
        """Classify a medical document."""
        raise NotImplementedError

    @abstractmethod
    async def extract_information(
        self,
        document_text: str,
        document_type: str,
    ) -> dict[str, Any]:
        """Extract structured medical information."""
        raise NotImplementedError

    @abstractmethod
    async def generate_summary(
        self,
        verified_records: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Generate a summary from verified health records."""
        raise NotImplementedError

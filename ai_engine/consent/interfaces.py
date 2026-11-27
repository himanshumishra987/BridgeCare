"""Backend authorization boundary interface for BridgeCare AI engine."""

from abc import ABC, abstractmethod
from typing import Optional

from ai_engine.schemas.consent import ConsentGrant, SharingPurpose


class ConsentAuthorizationProvider(ABC):
    """Abstract boundary for fetching explicit authorization decisions from the trusted backend.

    The AI engine NEVER grants, infers, or creates consent decisions. In production,
    Shreyash's backend provides the concrete implementation of this interface.
    """

    @abstractmethod
    async def get_authorization(
        self,
        patient_id: str,
        recipient_id: str,
        purpose: SharingPurpose,
        consent_id: Optional[str] = None,
    ) -> Optional[ConsentGrant]:
        """Fetch an explicit ConsentGrant from the trusted backend, or None if unavailable/denied."""
        raise NotImplementedError

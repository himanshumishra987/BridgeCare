from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.schemas.clinical import RecordOut
from app.schemas.common import StrictModel


class AiIngestResult(StrictModel):
    extraction_id: str
    status: str
    created: bool
    records_created: int
    measurements_created: int
    medications_created: int
    verification_status: str | None = None


class AiInsuranceIngestResult(StrictModel):
    """Acknowledgement of an insurance extraction submission."""

    extraction_id: str | None = None
    status: str
    created: bool
    facts_written: int
    members_recorded: int
    policy_conflicts: int
    uncertainties_recorded: int
    verification_status: str | None = None


class AiPatientContext(StrictModel):
    """Verified-only context for assistant and summary generation.

    ``language`` is the patient's saved preference (default ``en``). Only records
    a human moved to ``verified`` are included: unverified, pending-review and
    rejected rows, including AI proposals, are never sent back out as clinical
    fact.
    """

    patient_id: uuid.UUID
    language: str
    record_count: int
    records: list[RecordOut]


class AiDocumentMetadata(StrictModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    kind: str
    status: str
    content_type: str
    byte_size: int
    sha256: str
    original_filename: str
    page_count: int | None = None
    created_at: datetime
    existing_extraction_ids: list[str]
    provenance: dict[str, Any] | None = None

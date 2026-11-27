"""IDTA: malware scanning gate in front of every AI processing path.

Rules enforced here
-------------------
* A document may be processed only after a scanner returned an explicit
  ``clean`` verdict.
* "No scanner configured", "scanner error" and "inconclusive" are all non-clean
  states. None of them is ever treated as clean.
* A positive verdict quarantines the document: the metadata and the verdict are
  retained for audit, the stored bytes are purged, and no read path will serve
  them again.
* Every verdict is written to the append-only audit log.

The adapter is deliberately minimal: :func:`scan_bytes` is the only place a real
engine (for example a ClamAV daemon) is plugged in. Adding one must not change
any caller.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import MalwareDetectedError, ScanRequiredError, ServiceUnavailableError
from app.db.base import utcnow
from app.models.document import Document
from app.models.enums import DocumentScanStatus, DocumentStatus
from app.services.audit import record_audit
from app.services.documents import delete_document_bytes, read_document_bytes

#: Marker used by the deterministic test scanner. A real engine reports its own
#: signature name; this one only exists so the pipeline can be exercised in tests.
STUB_INFECTED_MARKER = b"EICAR-TEST"
STUB_INCONCLUSIVE_MARKER = b"SCANNER-INCONCLUSIVE"


@dataclass(frozen=True)
class ScanOutcome:
    status: DocumentScanStatus
    engine: str
    signature_version: str | None = None
    detail: str | None = None


def _stub_scan(data: bytes) -> ScanOutcome:
    """Deterministic stand-in scanner used by tests and local demos only."""
    if STUB_INFECTED_MARKER in data:
        return ScanOutcome(
            status=DocumentScanStatus.INFECTED,
            engine="stub-scanner",
            signature_version="stub-2026.11",
            detail="Test signature matched.",
        )
    if STUB_INCONCLUSIVE_MARKER in data:
        return ScanOutcome(
            status=DocumentScanStatus.ERROR,
            engine="stub-scanner",
            signature_version="stub-2026.11",
            detail="Scanner could not reach a verdict.",
        )
    return ScanOutcome(
        status=DocumentScanStatus.CLEAN,
        engine="stub-scanner",
        signature_version="stub-2026.11",
    )


def scan_bytes(data: bytes) -> ScanOutcome:
    """Run the configured scanner over ``data``.

    Raises :class:`ServiceUnavailableError` when no scanner is configured: an
    unconfigured deployment must never manufacture a clean verdict.
    """
    provider = get_settings().document_scanner
    if provider == "stub":
        return _stub_scan(data)
    raise ServiceUnavailableError(
        "Document scanning is not configured on this deployment, so no document "
        "can be processed."
    )


def record_verdict(
    db: Session,
    *,
    document: Document,
    outcome: ScanOutcome,
    request: Request | None = None,
    actor_user_id: uuid.UUID | None = None,
    actor_role: str | None = None,
) -> Document:
    """Persist a scan verdict, quarantining the document when it is positive."""
    document.scan_status = outcome.status
    document.scanned_at = utcnow()
    document.scan_engine = outcome.engine
    document.scan_signature_version = outcome.signature_version

    if outcome.status == DocumentScanStatus.INFECTED:
        document.quarantined_at = utcnow()
        document.status = DocumentStatus.FAILED
        delete_document_bytes(document)

    db.flush()
    record_audit(
        db,
        action="document.scanned",
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        patient_id=document.patient_id,
        resource_type="document",
        resource_id=str(document.id),
        request=request,
        outcome="success" if outcome.status != DocumentScanStatus.ERROR else "error",
        context={
            "scan_status": str(outcome.status),
            "scan_engine": outcome.engine,
            "signature_version": outcome.signature_version,
        },
    )
    return document


def scan_document(
    db: Session,
    *,
    document: Document,
    request: Request | None = None,
    actor_user_id: uuid.UUID | None = None,
    actor_role: str | None = None,
) -> Document:
    """Scan a stored document and persist the verdict.

    When the scanner itself is unavailable the document is left in ``ERROR``
    (never ``CLEAN``) and a 503 is raised so the caller can retry later.
    """
    if document.scan_status == DocumentScanStatus.INFECTED:
        raise MalwareDetectedError()

    try:
        outcome = scan_bytes(read_document_bytes(document))
    except ServiceUnavailableError as exc:
        record_verdict(
            db,
            document=document,
            outcome=ScanOutcome(
                status=DocumentScanStatus.ERROR,
                engine="unavailable",
                detail="No scanner configured.",
            ),
            request=request,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
        )
        raise exc

    return record_verdict(
        db,
        document=document,
        outcome=outcome,
        request=request,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
    )


def require_clean(document: Document) -> Document:
    """Assert that a document may be handed to any processing path.

    Ordered so the most serious state wins: infected, then scanner error, then
    never scanned.
    """
    if document.scan_status == DocumentScanStatus.INFECTED:
        raise MalwareDetectedError(
            "This document failed malware scanning and cannot be processed or downloaded."
        )
    if document.scan_status == DocumentScanStatus.ERROR:
        raise ServiceUnavailableError(
            "Malware scanning is unavailable for this document, so processing stays "
            "blocked until a clean verdict exists."
        )
    if document.scan_status != DocumentScanStatus.CLEAN:
        raise ScanRequiredError()
    return document

"""Internal endpoints used by the AI engine.

Authentication is a shared service key (``X-AI-Service-Key``), not a user token.
The key is compared in constant time, and the endpoints fail closed with 503 when
no key is configured. Every call is audited as ``actor_type=ai_service``.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select

from app.api.deps import DbSession, require_ai_service
from app.core.errors import NotFoundError
from app.models.document import Document, DocumentExtraction
from app.models.enums import ActorType
from app.schemas.ai import (
    AiDocumentMetadata,
    AiIngestResult,
    AiInsuranceIngestResult,
    AiPatientContext,
)
from app.schemas.clinical import RecordOut
from app.services.ai_context import (
    DEFAULT_CONTEXT_RECORDS,
    MAX_CONTEXT_RECORDS,
    verified_record_context,
)
from app.services.ai_contract import ExtractionEnvelope, ingest_extraction
from app.services.audit import record_audit
from app.services.documents import read_document_bytes
from app.services.insurance_extraction import (
    InsuranceExtractionEnvelope,
    ingest_insurance_extraction,
)

router = APIRouter(
    prefix="/internal/ai",
    tags=["AI engine (internal)"],
    dependencies=[Depends(require_ai_service)],
)


@router.post(
    "/extractions",
    response_model=AiIngestResult,
    summary="Submit a structured extraction for a document (idempotent)",
)
def submit_extraction(
    envelope: ExtractionEnvelope, request: Request, db: DbSession
) -> AiIngestResult:
    result = ingest_extraction(db, envelope=envelope, request=request)
    return AiIngestResult.model_validate(result)


@router.post(
    "/insurance/extractions",
    response_model=AiInsuranceIngestResult,
    summary="Submit an AI insurance extraction for a policy document (idempotent)",
)
def submit_insurance_extraction(
    envelope: InsuranceExtractionEnvelope, request: Request, db: DbSession
) -> AiInsuranceIngestResult:
    """Accept extracted coverage as *review material* only.

    The document must already have a clean IDTA verdict; values land as
    ``needs_review`` facts and only a human can confirm them.
    """
    result = ingest_insurance_extraction(db, envelope=envelope, request=request)
    return AiInsuranceIngestResult.model_validate(result)


@router.get(
    "/patients/{patient_id}/context",
    response_model=AiPatientContext,
    summary="Verified records plus the saved language for assistant/summary calls",
)
def patient_context(
    patient_id: uuid.UUID,
    request: Request,
    db: DbSession,
    limit: int = Query(default=DEFAULT_CONTEXT_RECORDS, ge=1, le=MAX_CONTEXT_RECORDS),
) -> AiPatientContext:
    """Feed for the AI engine: verified records only, with the language to answer in."""
    context = verified_record_context(db, patient_id=patient_id, limit=limit)
    record_audit(
        db,
        action="ai.context_fetched",
        actor_type=ActorType.AI_SERVICE,
        patient_id=context.patient.id,
        resource_type="patient_profile",
        resource_id=str(context.patient.id),
        request=request,
        context={"record_count": len(context.records), "limit": limit},
    )
    return AiPatientContext(
        patient_id=context.patient.id,
        language=context.patient.primary_language,
        record_count=len(context.records),
        records=[RecordOut.model_validate(record) for record in context.records],
    )


@router.get(
    "/documents/{document_id}",
    response_model=AiDocumentMetadata,
    summary="Document metadata for the extraction pipeline",
)
def document_metadata(document_id: uuid.UUID, db: DbSession) -> AiDocumentMetadata:
    document = db.get(Document, document_id)
    if document is None:
        raise NotFoundError("Document not found.")
    extraction_ids = list(
        db.scalars(
            select(DocumentExtraction.extraction_id).where(
                DocumentExtraction.document_id == document.id
            )
        )
    )
    return AiDocumentMetadata(
        id=document.id,
        patient_id=document.patient_id,
        kind=str(document.kind),
        status=str(document.status),
        content_type=document.content_type,
        byte_size=document.byte_size,
        sha256=document.sha256,
        original_filename=document.original_filename,
        page_count=document.page_count,
        created_at=document.created_at,
        existing_extraction_ids=extraction_ids,
    )


@router.get(
    "/documents/{document_id}/content",
    summary="Fetch the original file for OCR (audited, no-store)",
    response_class=Response,
)
def document_content(
    document_id: uuid.UUID, request: Request, db: DbSession
) -> Response:
    document = db.get(Document, document_id)
    if document is None:
        raise NotFoundError("Document not found.")
    content = read_document_bytes(document)
    record_audit(
        db,
        action="ai.document_fetched",
        actor_type=ActorType.AI_SERVICE,
        patient_id=document.patient_id,
        resource_type="document",
        resource_id=str(document.id),
        request=request,
    )
    return Response(
        content=content,
        media_type=document.content_type,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f'attachment; filename="{document.original_filename}"',
        },
    )

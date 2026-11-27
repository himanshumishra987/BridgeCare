"""Document endpoints.

Uploads are sniffed, size-limited, hashed and stored outside the web root.
Downloads are authorized per request and audited; responses are marked
``no-store`` so health documents are not cached by intermediaries.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, File, Form, Request, Response, UploadFile, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.config import get_settings
from app.core.errors import NotFoundError, PayloadTooLargeError
from app.core.pagination import paginate
from app.models.document import Document, DocumentExtraction
from app.models.enums import AccessScope, DocumentKind, DocumentStatus
from app.schemas.clinical import DocumentExtractionOut, DocumentOut
from app.schemas.common import PageMeta, Paginated
from app.services import idta
from app.services.access import require_patient_access, require_patient_write_access
from app.services.audit import record_audit
from app.services.documents import read_document_bytes, store_document

router = APIRouter(tags=["Documents"])

DOCUMENT_NOT_FOUND = "Document not found or not accessible."


async def _read_limited(file: UploadFile) -> bytes:
    limit = get_settings().max_upload_bytes
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(256 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise PayloadTooLargeError(
                f"Documents must be {limit // (1024 * 1024)} MB or smaller."
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _load_document(db: DbSession, document_id: uuid.UUID) -> Document:
    document = db.get(Document, document_id)
    if document is None:
        raise NotFoundError(DOCUMENT_NOT_FOUND)
    return document


@router.post(
    "/patients/{patient_id}/documents",
    response_model=DocumentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a medical document (PDF, PNG or JPEG)",
)
async def upload_document(
    patient_id: uuid.UUID,
    request: Request,
    response: Response,
    user: CurrentUser,
    db: DbSession,
    file: UploadFile = File(...),
    kind: DocumentKind = Form(DocumentKind.UNKNOWN),
) -> Document:
    require_patient_write_access(
        db,
        user=user,
        patient_id=patient_id,
        scope=AccessScope.DOCUMENTS,
        request=request,
        action="document.upload",
    )
    data = await _read_limited(file)
    stored = store_document(
        db,
        patient_id=patient_id,
        uploaded_by_user_id=user.id,
        filename=file.filename,
        declared_content_type=file.content_type,
        data=data,
    )
    document = stored.document
    if kind != DocumentKind.UNKNOWN:
        document.kind = kind
    if not stored.created:
        response.status_code = status.HTTP_200_OK
    record_audit(
        db,
        action="document.uploaded" if stored.created else "document.deduplicated",
        actor_user_id=user.id,
        actor_role=str(user.role),
        patient_id=patient_id,
        resource_type="document",
        resource_id=str(document.id),
        request=request,
        context={"byte_size": document.byte_size, "content_type": document.content_type},
    )
    return document


@router.get(
    "/patients/{patient_id}/documents",
    response_model=Paginated[DocumentOut],
    summary="List document metadata for a patient",
)
def list_documents(
    patient_id: uuid.UUID,
    request: Request,
    user: CurrentUser,
    db: DbSession,
    page: int = 1,
    page_size: int | None = None,
    kind: DocumentKind | None = None,
) -> Paginated[DocumentOut]:
    require_patient_access(
        db,
        user=user,
        patient_id=patient_id,
        scope=AccessScope.DOCUMENTS,
        request=request,
        action="document.list",
    )
    stmt = select(Document).where(
        Document.patient_id == patient_id, Document.archived_at.is_(None)
    )
    if kind is not None:
        stmt = stmt.where(Document.kind == kind)
    stmt = stmt.order_by(Document.created_at.desc())
    page_result = paginate(db, stmt, page=page, page_size=page_size)
    return Paginated[DocumentOut](
        items=[DocumentOut.model_validate(item) for item in page_result.items],
        meta=PageMeta(**page_result.meta()),
    )


@router.get(
    "/documents/{document_id}",
    response_model=DocumentOut,
    summary="Read document metadata",
)
def read_document(
    document_id: uuid.UUID, request: Request, user: CurrentUser, db: DbSession
) -> Document:
    document = _load_document(db, document_id)
    require_patient_access(
        db,
        user=user,
        patient_id=document.patient_id,
        scope=AccessScope.DOCUMENTS,
        request=request,
        action="document.view",
    )
    return document


@router.get(
    "/documents/{document_id}/download",
    summary="Download the original document (authorized and audited)",
    response_class=Response,
)
def download_document(
    document_id: uuid.UUID, request: Request, user: CurrentUser, db: DbSession
) -> Response:
    document = _load_document(db, document_id)
    require_patient_access(
        db,
        user=user,
        patient_id=document.patient_id,
        scope=AccessScope.DOCUMENTS,
        request=request,
        action="document.download",
    )
    content = read_document_bytes(document)
    record_audit(
        db,
        action="document.downloaded",
        actor_user_id=user.id,
        actor_role=str(user.role),
        patient_id=document.patient_id,
        resource_type="document",
        resource_id=str(document.id),
        request=request,
    )
    return Response(
        content=content,
        media_type=document.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{document.original_filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post(
    "/documents/{document_id}/archive",
    response_model=DocumentOut,
    summary="Archive a document (kept, hidden from lists, not downloadable)",
)
def archive_document(
    document_id: uuid.UUID, request: Request, user: CurrentUser, db: DbSession
) -> Document:
    document = _load_document(db, document_id)
    require_patient_write_access(
        db,
        user=user,
        patient_id=document.patient_id,
        scope=AccessScope.DOCUMENTS,
        request=request,
        action="document.archive",
    )
    if document.archived_at is None:
        document.archived_at = datetime.now(UTC)
        document.status = DocumentStatus.ARCHIVED
        db.flush()
        record_audit(
            db,
            action="document.archived",
            actor_user_id=user.id,
            actor_role=str(user.role),
            patient_id=document.patient_id,
            resource_type="document",
            resource_id=str(document.id),
            request=request,
        )
    return document


@router.post(
    "/documents/{document_id}/scan",
    response_model=DocumentOut,
    summary="Run the IDTA malware scan and record its verdict",
)
def scan_document(
    document_id: uuid.UUID, request: Request, user: CurrentUser, db: DbSession
) -> Document:
    """Scan a document. Processing stays blocked unless the verdict is ``clean``.

    An infected verdict quarantines the document: the verdict is recorded, the
    stored bytes are purged, and the response exposes ``scan_status=infected``
    so the UI can say so rather than pretending the upload succeeded.
    """
    document = _load_document(db, document_id)
    require_patient_access(
        db,
        user=user,
        patient_id=document.patient_id,
        scope=AccessScope.DOCUMENTS,
        request=request,
        action="document.scan",
    )
    if document.archived_at is not None:
        raise ConflictError("This document has been archived.")
    return idta.scan_document(
        db,
        document=document,
        request=request,
        actor_user_id=user.id,
        actor_role=str(user.role),
    )


@router.get(
    "/documents/{document_id}/extractions",
    response_model=list[DocumentExtractionOut],
    summary="List AI extraction receipts for a document",
)
def list_extractions(
    document_id: uuid.UUID, request: Request, user: CurrentUser, db: DbSession
) -> list[DocumentExtractionOut]:
    document = _load_document(db, document_id)
    require_patient_access(
        db,
        user=user,
        patient_id=document.patient_id,
        scope=AccessScope.DOCUMENTS,
        request=request,
        action="document.extractions",
    )
    rows = db.scalars(
        select(DocumentExtraction)
        .where(DocumentExtraction.document_id == document.id)
        .order_by(DocumentExtraction.received_at.desc())
    )
    return [DocumentExtractionOut.model_validate(row) for row in rows]

"""Provenance validation safeguards for extracted medical information."""

from typing import Optional

from ai_engine.schemas.common import FieldUncertainty, SourceReference
from ai_engine.schemas.extraction import ExtractionResult
from ai_engine.schemas.ingestion import ExtractedPage


def _normalize_whitespace(text: str) -> str:
    """Collapse whitespace and lowercase for safe excerpt comparison."""
    return " ".join(text.split()).lower()


def _verify_reference(
    ref: Optional[SourceReference],
    page_text_map: dict[int, str],
    field_label: str,
    document_id: Optional[str] = None,
) -> tuple[Optional[SourceReference], Optional[FieldUncertainty]]:
    """Verify that a SourceReference points to a valid ingested page and matching excerpt.

    Never treats a structurally valid model reference as verified without checking
    against actual ingested page text. Flags unsupported/mismatched references as uncertain.
    """
    if ref is None:
        return None, None

    if ref.page_number not in page_text_map:
        return None, FieldUncertainty(
            field_name=ref.field_name or field_label,
            reason=(
                f"Source reference cites page {ref.page_number}, which does not exist "
                f"in the ingested document (valid pages: {sorted(page_text_map.keys())})."
            ),
        )

    normalized_page_text = page_text_map[ref.page_number]
    normalized_excerpt = _normalize_whitespace(ref.excerpt)

    if not normalized_excerpt or normalized_excerpt not in normalized_page_text:
        return None, FieldUncertainty(
            field_name=ref.field_name or field_label,
            reason=(
                f"Quoted excerpt for '{ref.field_name or field_label}' could not be verified "
                f"against extracted text on page {ref.page_number}."
            ),
        )

    verified_ref = SourceReference(
        document_id=ref.document_id or document_id,
        page_number=ref.page_number,
        excerpt=ref.excerpt,
        field_name=ref.field_name or field_label,
    )
    return verified_ref, None


def validate_extraction_provenance(
    extraction: ExtractionResult,
    pages: list[ExtractedPage],
    document_id: Optional[str] = None,
) -> ExtractionResult:
    """Validate all SourceReferences in an ExtractionResult against ingested pages."""
    page_text_map = {
        page.page_number: _normalize_whitespace(page.text)
        for page in pages
    }

    additional_uncertainties: list[FieldUncertainty] = []

    updated_biomarkers = []
    for biomarker in extraction.biomarkers:
        ref, flag = _verify_reference(
            biomarker.source_reference,
            page_text_map,
            biomarker.name,
            document_id=document_id,
        )
        if flag:
            additional_uncertainties.append(flag)
        updated_biomarkers.append(biomarker.model_copy(update={"source_reference": ref}))

    updated_medications = []
    for med in extraction.medications:
        label = med.brand_name or (med.generic_ingredients[0] if med.generic_ingredients else "medication")
        ref, flag = _verify_reference(
            med.source_reference,
            page_text_map,
            label,
            document_id=document_id,
        )
        if flag:
            additional_uncertainties.append(flag)
        updated_medications.append(med.model_copy(update={"source_reference": ref}))

    updated_events = []
    for event in extraction.clinical_events:
        ref, flag = _verify_reference(
            event.source_reference,
            page_text_map,
            event.event_type,
            document_id=document_id,
        )
        if flag:
            additional_uncertainties.append(flag)
        updated_events.append(event.model_copy(update={"source_reference": ref}))

    updated_uncertainties = []
    for u in extraction.uncertainty_flags:
        ref, flag = _verify_reference(
            u.source_reference,
            page_text_map,
            u.field_name,
            document_id=document_id,
        )
        if flag:
            additional_uncertainties.append(flag)
        updated_uncertainties.append(u.model_copy(update={"source_reference": ref}))

    return extraction.model_copy(
        update={
            "biomarkers": updated_biomarkers,
            "medications": updated_medications,
            "clinical_events": updated_events,
            "uncertainty_flags": updated_uncertainties + additional_uncertainties,
        }
    )

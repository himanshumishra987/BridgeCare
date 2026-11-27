"""Consent enforcement and privacy-preserving record filtering."""

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import Any, Optional

from ai_engine.consent.interfaces import ConsentAuthorizationProvider
from ai_engine.schemas.common import VerificationStatus
from ai_engine.schemas.consent import (
    ConsentAuditMetadata,
    ConsentGrant,
    ConsentStatus,
    PermittedDataCategory,
    SharingPurpose,
)

logger = logging.getLogger(__name__)

_APPROVED_VERIFICATION_VALUES = frozenset(
    {VerificationStatus.VERIFIED.value, VerificationStatus.EDITED_VERIFIED.value}
)


@dataclass(frozen=True)
class ConsentEvaluationResult:
    """Outcome of evaluating consent and filtering records."""

    authorized: bool
    filtered_records: list[dict[str, Any]]
    audit: ConsentAuditMetadata
    denial_code: Optional[str] = None
    denial_reason: Optional[str] = None


class ConsentEnforcer:
    """Enforces explicit backend consent grants and human-verification rules.

    Denies access by default whenever consent is missing, expired, revoked,
    mismatched, or the authorization provider is unavailable.
    """

    def __init__(
        self,
        auth_provider: Optional[ConsentAuthorizationProvider] = None,
    ):
        self.auth_provider = auth_provider

    async def evaluate_and_filter(
        self,
        *,
        patient_id: str,
        recipient_id: str,
        purpose: SharingPurpose,
        records: list[dict[str, Any]],
        consent: Optional[ConsentGrant] = None,
        consent_id: Optional[str] = None,
        now_utc: Optional[datetime] = None,
    ) -> ConsentEvaluationResult:
        """Resolve authorization and filter records before any AI prompt is constructed."""
        current_time = now_utc or datetime.now(timezone.utc)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)

        resolved_consent = consent
        if resolved_consent is None:
            if self.auth_provider is None:
                return self._deny(
                    patient_id=patient_id,
                    recipient_id=recipient_id,
                    purpose=purpose,
                    consent_id=consent_id,
                    code="AUTHORIZATION_UNAVAILABLE",
                    reason=(
                        "Access denied: no explicit consent grant or backend authorization "
                        "provider is available."
                    ),
                )
            try:
                resolved_consent = await self.auth_provider.get_authorization(
                    patient_id=patient_id,
                    recipient_id=recipient_id,
                    purpose=purpose,
                    consent_id=consent_id,
                )
            except Exception as e:
                logger.warning("Authorization provider lookup failed: %s", type(e).__name__)
                return self._deny(
                    patient_id=patient_id,
                    recipient_id=recipient_id,
                    purpose=purpose,
                    consent_id=consent_id,
                    code="AUTHORIZATION_UNAVAILABLE",
                    reason="Access denied: backend authorization service is unavailable.",
                )

        if resolved_consent is None:
            return self._deny(
                patient_id=patient_id,
                recipient_id=recipient_id,
                purpose=purpose,
                consent_id=consent_id,
                code="CONSENT_MISSING",
                reason="Access denied: no matching consent grant found.",
            )

        # Validate consent grant ownership, recipient, purpose, status, expiry, revocation
        denial = self._validate_grant(
            grant=resolved_consent,
            patient_id=patient_id,
            recipient_id=recipient_id,
            purpose=purpose,
            current_time=current_time,
        )
        if denial is not None:
            code, reason = denial
            return self._deny(
                patient_id=patient_id,
                recipient_id=recipient_id,
                purpose=purpose,
                consent_id=resolved_consent.consent_id,
                code=code,
                reason=reason,
            )

        # Filter records strictly by verification status, permitted_document_ids, and categories
        permitted_docs = set(resolved_consent.permitted_document_ids)
        permitted_cats = set(resolved_consent.permitted_categories)

        filtered: list[dict[str, Any]] = []
        included_ids: list[str] = []
        excluded_reasons: set[str] = set()
        excluded_count = 0

        for rec in records:
            if not isinstance(rec, dict):
                excluded_count += 1
                excluded_reasons.add("invalid_record_format")
                continue

            # 1. Human-verification gate
            ver_status = str(rec.get("verification_status") or "").strip().lower()
            if ver_status not in _APPROVED_VERIFICATION_VALUES:
                excluded_count += 1
                excluded_reasons.add("unverified_or_rejected_record")
                continue

            # 2. Patient ownership check (if record carries patient_id)
            rec_patient_id = rec.get("patient_id")
            if rec_patient_id and str(rec_patient_id) != patient_id:
                excluded_count += 1
                excluded_reasons.add("patient_id_mismatch")
                continue

            # 3. Document-level consent check
            doc_id = rec.get("document_id")
            if not doc_id or str(doc_id) not in permitted_docs:
                excluded_count += 1
                excluded_reasons.add("document_not_in_consent")
                continue

            # 4. Category-level field filtering (preserving source_references on allowed items)
            scoped = self._filter_record_categories(rec, permitted_cats)
            if scoped is None:
                excluded_count += 1
                excluded_reasons.add("no_permitted_category_data")
                continue

            filtered.append(scoped)
            included_ids.append(str(doc_id))

        if not filtered:
            return self._deny(
                patient_id=patient_id,
                recipient_id=recipient_id,
                purpose=purpose,
                consent_id=resolved_consent.consent_id,
                code="NO_AUTHORIZED_RECORDS",
                reason=(
                    "Access denied: no verified records are authorized for the requested "
                    "recipient, purpose, and data categories."
                ),
                excluded_count=excluded_count,
                excluded_reasons=sorted(excluded_reasons),
                permitted_categories=list(resolved_consent.permitted_categories),
            )

        audit = ConsentAuditMetadata(
            consent_id=resolved_consent.consent_id,
            patient_id=patient_id,
            recipient_id=recipient_id,
            purpose=purpose,
            decision="allowed",
            included_document_ids=sorted(set(included_ids)),
            excluded_record_count=excluded_count,
            excluded_reasons=sorted(excluded_reasons),
            permitted_categories=list(resolved_consent.permitted_categories),
        )
        return ConsentEvaluationResult(
            authorized=True,
            filtered_records=filtered,
            audit=audit,
        )

    @staticmethod
    def _validate_grant(
        *,
        grant: ConsentGrant,
        patient_id: str,
        recipient_id: str,
        purpose: SharingPurpose,
        current_time: datetime,
    ) -> Optional[tuple[str, str]]:
        if grant.patient_id != patient_id:
            return ("PATIENT_MISMATCH", "Access denied: consent patient_id does not match request.")
        if grant.recipient_id != recipient_id:
            return ("RECIPIENT_MISMATCH", "Access denied: consent does not authorize this recipient.")
        if grant.purpose != purpose:
            return ("PURPOSE_MISMATCH", "Access denied: consent does not authorize this sharing purpose.")
        if grant.revoked_at is not None or grant.status == ConsentStatus.REVOKED:
            return ("CONSENT_REVOKED", "Access denied: consent has been revoked.")
        if grant.status == ConsentStatus.EXPIRED:
            return ("CONSENT_EXPIRED", "Access denied: consent has expired.")
        if grant.expires_at is not None:
            exp = grant.expires_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp <= current_time:
                return ("CONSENT_EXPIRED", "Access denied: consent has expired.")
        if grant.status != ConsentStatus.ACTIVE:
            return (
                "CONSENT_INACTIVE",
                f"Access denied: consent status '{grant.status.value}' is not active.",
            )
        if not grant.permitted_categories:
            return ("NO_PERMITTED_CATEGORIES", "Access denied: no data categories are permitted.")
        if not grant.permitted_document_ids:
            return ("NO_PERMITTED_DOCUMENTS", "Access denied: no documents are permitted.")
        return None

    @staticmethod
    def _filter_record_categories(
        rec: dict[str, Any],
        permitted_cats: set[PermittedDataCategory],
    ) -> Optional[dict[str, Any]]:
        """Filter record fields strictly to permitted categories without mutating input."""
        scoped: dict[str, Any] = {
            "document_id": rec.get("document_id"),
            "verification_status": rec.get("verification_status"),
            "document_type": rec.get("document_type"),
        }

        has_data = False

        if PermittedDataCategory.DOCUMENT_METADATA in permitted_cats:
            for field in ("document_date", "hospital_or_lab_name", "doctor_name", "patient_name"):
                if rec.get(field) is not None:
                    scoped[field] = rec[field]
                    has_data = True

        if PermittedDataCategory.LAB_RESULTS in permitted_cats:
            biomarkers = deepcopy(rec.get("biomarkers") or [])
            scoped["biomarkers"] = biomarkers
            if biomarkers:
                has_data = True
        else:
            scoped["biomarkers"] = []

        if PermittedDataCategory.MEDICATIONS in permitted_cats:
            medications = deepcopy(rec.get("medications") or [])
            scoped["medications"] = medications
            if medications:
                has_data = True
        else:
            scoped["medications"] = []

        if PermittedDataCategory.CLINICAL_EVENTS in permitted_cats:
            events = deepcopy(rec.get("clinical_events") or [])
            scoped["clinical_events"] = events
            if events:
                has_data = True
        else:
            scoped["clinical_events"] = []

        return scoped if has_data else None

    @staticmethod
    def _deny(
        *,
        patient_id: str,
        recipient_id: str,
        purpose: SharingPurpose,
        consent_id: Optional[str],
        code: str,
        reason: str,
        excluded_count: int = 0,
        excluded_reasons: Optional[list[str]] = None,
        permitted_categories: Optional[list[PermittedDataCategory]] = None,
    ) -> ConsentEvaluationResult:
        audit = ConsentAuditMetadata(
            consent_id=consent_id,
            patient_id=patient_id,
            recipient_id=recipient_id,
            purpose=purpose,
            decision="denied",
            denial_code=code,
            denial_reason=reason,
            included_document_ids=[],
            excluded_record_count=excluded_count,
            excluded_reasons=excluded_reasons or [],
            permitted_categories=permitted_categories or [],
        )
        return ConsentEvaluationResult(
            authorized=False,
            filtered_records=[],
            audit=audit,
            denial_code=code,
            denial_reason=reason,
        )

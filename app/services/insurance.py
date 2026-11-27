"""Insurance domain logic: coverage facts, policy versions and guidance.

Design notes
------------
* Coverage is stored as *facts* (one row per field) so every number can carry its
  own provenance, confidence and verification state instead of being buried in a
  single JSON blob.
* ``original`` is written once. A correction supersedes a fact (``is_active``
  flips) and creates a new row; the extracted value is never overwritten.
* Only the insurer verification boundary may write ``INSURER_VERIFIED``. A
  patient confirmation is recorded as ``PATIENT_CONFIRMED`` and stays distinct.
* Guidance is deterministic template text derived from stored facts. It is not
  medical advice, not a claim, and never submitted anywhere.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ValidationAppError
from app.db.base import utcnow
from app.models.consent import ConsentGrant
from app.models.enums import (
    ConsentBasis,
    ConsentStatus,
    CoverageFactSource,
    CoverageSource,
    CoverageVerificationStatus,
    PolicyCoverageClass,
    PolicyVersionKind,
)
from app.models.insurance import (
    InsuranceCoverageFact,
    InsuranceInsuredMember,
    InsurancePolicy,
    InsurancePolicyVersion,
)
from app.models.patient import PatientProfile

FIELD_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_.]{1,59}$")

#: Fields the guidance endpoint knows how to talk about, with their value kind.
COVERAGE_FIELDS: dict[str, tuple[str, str, str | None]] = {
    # key: (label, kind, unit)
    "sum_insured": ("Sum insured", "money", "INR"),
    "room_rent_limit": ("Room rent limit", "money", "INR/day"),
    "icu_limit": ("ICU limit", "money", "INR/day"),
    "sub_limit": ("Sub-limit", "money", "INR"),
    "ambulance_cover": ("Ambulance cover", "money", "INR"),
    "hospitalisation_benefit": ("Hospitalisation benefit", "money", "INR"),
    "restoration_benefit": ("Restoration benefit", "money", "INR"),
    "copay_percent": ("Co-payment", "percent", "%"),
    "deductible": ("Deductible", "money", "INR"),
    "waiting_period_months": ("Initial waiting period", "months", "months"),
    "pre_existing_waiting_months": ("Pre-existing disease waiting period", "months", "months"),
    "maternity_waiting_months": ("Maternity waiting period", "months", "months"),
    "specific_disease_waiting_months": ("Specific disease waiting period", "months", "months"),
    "claim_intimation_days": ("Claim intimation window", "days", "days"),
    "pre_auth_validity_days": ("Pre-authorisation validity", "days", "days"),
    "day_care_procedures": ("Day-care procedures covered", "bool", None),
    "domiciliary_hospitalisation": ("Domiciliary hospitalisation", "bool", None),
    "organ_donor_cover": ("Organ donor cover", "bool", None),
    "cashless_facility": ("Cashless facility", "bool", None),
    "room_category": ("Eligible room category", "text", None),
    "medicine_coverage": ("Medicine coverage", "text", None),
    "diagnostics_coverage": ("Diagnostic coverage", "text", None),
    "exclusions": ("Exclusions", "list", None),
    "additional_benefits": ("Additional benefits", "list", None),
    "required_documents": ("Documents the insurer asks for", "list", None),
    "claim_procedure": ("Claim procedure", "text", None),
    "tpa_name": ("TPA", "text", None),
    "tpa_contact": ("TPA contact", "text", None),
    "insurer_contact": ("Insurer contact", "text", None),
    "network_hospitals": ("Network hospitals", "text", None),
}

MONEY_MAX = Decimal("1000000000")
PERCENT_MAX = Decimal("100")
MONTHS_MAX = Decimal("600")
DAYS_MAX = Decimal("365")


@dataclass(frozen=True)
class FactValues:
    value_text: str | None = None
    value_numeric: Decimal | None = None
    value_percent: Decimal | None = None
    value_boolean: bool | None = None
    unit: str | None = None
    currency: str | None = None


def field_spec(field_key: str) -> tuple[str, str, str | None]:
    return COVERAGE_FIELDS.get(field_key, (field_key.replace("_", " ").title(), "text", None))


def validate_value(
    field_key: str,
    *,
    value_text: str | None = None,
    value_numeric: Decimal | None = None,
    value_percent: Decimal | None = None,
    value_boolean: bool | None = None,
) -> FactValues:
    """Validate one coverage value against its field kind.

    Unknown keys are accepted as free text so the extractor can add fields
    without a backend release, but known keys get strict typing.
    """
    if not FIELD_KEY_PATTERN.match(field_key):
        raise ValidationAppError(
            "field_key must start with a letter and contain only a-z, 0-9, '_' or '.'."
        )
    label, kind, unit = field_spec(field_key)
    supply = [
        value_text is not None,
        value_numeric is not None,
        value_percent is not None,
        value_boolean is not None,
    ]
    if sum(supply) != 1:
        raise ValidationAppError(f"Field '{field_key}' needs exactly one value.")

    if kind == "money":
        if value_numeric is None:
            raise ValidationAppError(f"Field '{field_key}' must be a number.")
        if value_numeric < 0 or value_numeric > MONEY_MAX:
            raise ValidationAppError(f"Field '{field_key}' is outside the allowed range.")
        return FactValues(value_numeric=value_numeric, unit=unit, currency="INR")

    if kind == "percent":
        if value_percent is None:
            raise ValidationAppError(f"Field '{field_key}' must be a percentage.")
        if value_percent < 0 or value_percent > PERCENT_MAX:
            raise ValidationAppError(f"Field '{field_key}' must be between 0 and 100.")
        return FactValues(value_percent=value_percent, unit="%")

    if kind == "months":
        if value_numeric is None:
            raise ValidationAppError(f"Field '{field_key}' must be a number of months.")
        if value_numeric < 0 or value_numeric > MONTHS_MAX:
            raise ValidationAppError(f"Field '{field_key}' is outside the allowed range.")
        return FactValues(value_numeric=value_numeric, unit="months")

    if kind == "days":
        if value_numeric is None:
            raise ValidationAppError(f"Field '{field_key}' must be a number of days.")
        if value_numeric < 0 or value_numeric > DAYS_MAX:
            raise ValidationAppError(f"Field '{field_key}' is outside the allowed range.")
        return FactValues(value_numeric=value_numeric, unit="days")

    if kind == "bool":
        if value_boolean is None:
            raise ValidationAppError(f"Field '{field_key}' must be true or false.")
        return FactValues(value_boolean=value_boolean)

    if kind == "list":
        if value_text is None or not value_text.strip():
            raise ValidationAppError(f"Field '{field_key}' needs at least one entry.")
        return FactValues(value_text=value_text.strip()[:1500])

    if value_text is None or not value_text.strip():
        raise ValidationAppError(f"Field '{field_key}' needs a non-empty value.")
    return FactValues(value_text=value_text.strip()[:500], unit=unit)


def fact_value_dict(fact: InsuranceCoverageFact) -> dict[str, Any]:
    return {
        "value_text": fact.value_text,
        "value_numeric": str(fact.value_numeric) if fact.value_numeric is not None else None,
        "value_percent": str(fact.value_percent) if fact.value_percent is not None else None,
        "value_boolean": fact.value_boolean,
        "unit": fact.unit,
        "currency": fact.currency,
    }


def normalize_for_compare(values: dict[str, Any]) -> str:
    """Stable string used to compare an insurer-confirmed value with a stored one."""
    for key in ("value_numeric", "value_percent"):
        raw = values.get(key)
        if raw is not None:
            try:
                return str(Decimal(str(raw)).normalize())
            except Exception:  # noqa: BLE001 - fall through to text comparison
                return str(raw)
    if values.get("value_boolean") is not None:
        return "true" if values["value_boolean"] else "false"
    text = (values.get("value_text") or "").strip().lower()
    return re.sub(r"\s+", " ", text)


def policy_snapshot(policy: InsurancePolicy, facts: list[InsuranceCoverageFact]) -> dict[str, Any]:
    """JSON snapshot stored on each version row."""
    return {
        "policy_number": policy.policy_number,
        "policy_type": str(policy.policy_type),
        "coverage_class": str(policy.coverage_class),
        "insurer_id": str(policy.insurer_id) if policy.insurer_id else None,
        "insurer_name_text": policy.insurer_name_text,
        "holder_name": policy.holder_name,
        "valid_from": policy.valid_from.isoformat() if policy.valid_from else None,
        "valid_to": policy.valid_to.isoformat() if policy.valid_to else None,
        "sum_insured": str(policy.sum_insured) if policy.sum_insured is not None else None,
        "coverage_source": str(policy.coverage_source),
        "verification_reference": policy.verification_reference,
        "status": str(policy.status),
        "facts": {
            fact.field_key: {
                **fact_value_dict(fact),
                "verification_status": str(fact.verification_status),
                "source": str(fact.source),
                "provenance": fact.provenance or {},
            }
            for fact in facts
        },
    }


def policyholder_can_include(
    db: Session, *, policy: InsurancePolicy, member_id: uuid.UUID
) -> bool:
    """True only for the policyholder themselves or a profile they are guardian of.

    This is the same rule the AI ingestion path uses, so a floater can never be
    built by naming another patient's profile id.
    """
    if member_id == policy.patient_id:
        return True
    owner = db.get(PatientProfile, policy.patient_id)
    if owner is None or owner.user_id is None:
        return False
    grant = db.scalar(
        select(ConsentGrant).where(
            ConsentGrant.patient_id == member_id,
            ConsentGrant.grantee_user_id == owner.user_id,
            ConsentGrant.basis == ConsentBasis.GUARDIANSHIP,
            ConsentGrant.status == ConsentStatus.ACTIVE,
        )
    )
    return grant is not None


def active_facts(db: Session, policy_id: uuid.UUID) -> list[InsuranceCoverageFact]:
    return list(
        db.scalars(
            select(InsuranceCoverageFact)
            .where(
                InsuranceCoverageFact.policy_id == policy_id,
                InsuranceCoverageFact.is_active.is_(True),
            )
            .order_by(InsuranceCoverageFact.field_key.asc())
        )
    )


def fact_by_key(db: Session, policy_id: uuid.UUID, field_key: str) -> InsuranceCoverageFact | None:
    return db.scalar(
        select(InsuranceCoverageFact).where(
            InsuranceCoverageFact.policy_id == policy_id,
            InsuranceCoverageFact.field_key == field_key,
            InsuranceCoverageFact.is_active.is_(True),
        )
    )


def record_version(
    db: Session,
    *,
    policy: InsurancePolicy,
    kind: PolicyVersionKind,
    actor_user_id: uuid.UUID | None,
    change_summary: str | None = None,
    source_document_id: uuid.UUID | None = None,
    endorsement_reference: str | None = None,
    effective_from: date | None = None,
) -> InsurancePolicyVersion:
    """Append a policy version. Numbers are monotonic per policy."""
    latest = db.scalar(
        select(InsurancePolicyVersion.version_number)
        .where(InsurancePolicyVersion.policy_id == policy.id)
        .order_by(InsurancePolicyVersion.version_number.desc())
        .limit(1)
    )
    version_number = int(latest or 0) + 1
    version = InsurancePolicyVersion(
        policy_id=policy.id,
        version_number=version_number,
        kind=kind,
        effective_from=effective_from or date.today(),
        endorsement_reference=endorsement_reference,
        change_summary=change_summary,
        snapshot=policy_snapshot(policy, active_facts(db, policy.id)),
        source_document_id=source_document_id,
        created_by_user_id=actor_user_id,
    )
    policy.version = version_number
    db.add(version)
    db.flush()
    return version


def upsert_fact(
    db: Session,
    *,
    policy: InsurancePolicy,
    field_key: str,
    values: FactValues,
    source: CoverageFactSource,
    verification_status: CoverageVerificationStatus,
    provenance: dict[str, Any] | None = None,
    confidence: float | None = None,
    source_document_id: uuid.UUID | None = None,
) -> InsuranceCoverageFact:
    """Supersede the active fact for ``field_key`` and store the new one."""
    previous = fact_by_key(db, policy.id, field_key)
    original: dict[str, Any] = {}
    if previous is not None:
        previous.is_active = False
        original = previous.original or fact_value_dict(previous)
        db.flush()

    label, _kind, _unit = field_spec(field_key)
    fact = InsuranceCoverageFact(
        policy_id=policy.id,
        policy_version=policy.version,
        field_key=field_key,
        label=label,
        value_text=values.value_text,
        value_numeric=values.value_numeric,
        value_percent=values.value_percent,
        value_boolean=values.value_boolean,
        unit=values.unit,
        currency=values.currency,
        source=source,
        verification_status=verification_status,
        confidence=confidence,
        provenance=provenance or {},
        original=original or fact_value_dict(values),
        source_document_id=source_document_id,
        is_active=True,
    )
    db.add(fact)
    db.flush()
    return fact


def correct_fact(
    db: Session,
    *,
    policy: InsurancePolicy,
    fact: InsuranceCoverageFact,
    values: FactValues,
    corrected_by_user_id: uuid.UUID,
    note: str | None = None,
) -> InsuranceCoverageFact:
    """Apply a patient correction without destroying the original value."""
    previous_original = fact.original or fact_value_dict(fact)
    fact.is_active = False
    db.flush()

    label, _kind, _unit = field_spec(fact.field_key)
    replacement = InsuranceCoverageFact(
        policy_id=policy.id,
        policy_version=policy.version,
        field_key=fact.field_key,
        label=label,
        value_text=values.value_text,
        value_numeric=values.value_numeric,
        value_percent=values.value_percent,
        value_boolean=values.value_boolean,
        unit=values.unit,
        currency=values.currency,
        source=CoverageFactSource.MANUAL,
        verification_status=CoverageVerificationStatus.MANUALLY_ENTERED,
        provenance={**(fact.provenance or {}), "correction_note": note},
        original=previous_original,
        corrected_at=utcnow(),
        corrected_by_user_id=corrected_by_user_id,
        source_document_id=fact.source_document_id,
        is_active=True,
    )
    db.add(replacement)
    db.flush()
    return replacement


def confirm_facts(
    db: Session,
    *,
    policy: InsurancePolicy,
    facts: list[InsuranceCoverageFact],
    confirmed_by_user_id: uuid.UUID,
) -> None:
    """Mark values patient-confirmed. Never produces an insurer verification."""
    for fact in facts:
        if fact.verification_status != CoverageVerificationStatus.INSURER_VERIFIED:
            fact.verification_status = CoverageVerificationStatus.PATIENT_CONFIRMED
    db.flush()
    record_version(
        db,
        policy=policy,
        kind=PolicyVersionKind.PATIENT_CONFIRMATION,
        actor_user_id=confirmed_by_user_id,
        change_summary="Patient confirmed coverage values.",
    )


def coverage_summary(policy: InsurancePolicy, facts: list[InsuranceCoverageFact]) -> dict[str, Any]:
    counts: dict[str, int] = {status.value: 0 for status in CoverageVerificationStatus}
    for fact in facts:
        counts[str(fact.verification_status)] += 1
    insurer_verified_fields = [
        fact.field_key
        for fact in facts
        if fact.verification_status == CoverageVerificationStatus.INSURER_VERIFIED
    ]
    unconfirmed = [
        fact.field_key
        for fact in facts
        if fact.verification_status
        in {
            CoverageVerificationStatus.EXTRACTED,
            CoverageVerificationStatus.NEEDS_REVIEW,
            CoverageVerificationStatus.DISCREPANCY,
        }
    ]
    # Derived from the facts themselves: a policy marked ``document`` with no
    # extracted value has no extraction to talk about.
    has_document = any(fact.source_document_id is not None for fact in facts)
    return {
        "policy_id": policy.id,
        "coverage_class": policy.coverage_class,
        "coverage_source": policy.coverage_source,
        "coverage_confirmed": policy.coverage_confirmed,
        "coverage_note": policy.coverage_note,
        "field_count": len(facts),
        "status_counts": counts,
        "insurer_verified_fields": insurer_verified_fields,
        "unconfirmed_fields": unconfirmed,
        "has_extracted_document": has_document,
        "policy_expired": is_expired(policy),
    }


def is_expired(policy: InsurancePolicy, today: date | None = None) -> bool:
    current = today or date.today()
    return policy.valid_to is not None and policy.valid_to < current


def _fact_line(fact: InsuranceCoverageFact) -> str:
    if fact.value_numeric is not None:
        amount = f"{fact.value_numeric.normalize():f}"
        return f"{amount} {fact.unit}".strip()
    if fact.value_percent is not None:
        return f"{fact.value_percent.normalize():f}%"
    if fact.value_boolean is not None:
        return "yes" if fact.value_boolean else "no"
    return (fact.value_text or "").strip()


def _source_of(fact: InsuranceCoverageFact | None) -> dict[str, Any] | None:
    if fact is None:
        return None
    provenance = fact.provenance or {}
    return {
        "field_key": fact.field_key,
        "verification_status": str(fact.verification_status),
        "page": provenance.get("page"),
        "clause_reference": provenance.get("clause_reference"),
        "source_document_id": str(fact.source_document_id) if fact.source_document_id else None,
    }


def build_guidance(
    policy: InsurancePolicy,
    facts: list[InsuranceCoverageFact],
    *,
    admission_type: str = "planned",
    member_count: int = 0,
) -> dict[str, Any]:
    """Policy-grounded admission and claim guidance.

    Everything here is derived from stored facts. Nothing is submitted to an
    insurer, and nothing here is medical advice.
    """
    by_key = {fact.field_key: fact for fact in facts}
    insured = policy.coverage_class == PolicyCoverageClass.FAMILY_FLOATER

    checklist: list[dict[str, Any]] = [
        {
            "item": "Carry the policy card or policy number",
            "detail": f"Policy {policy.policy_number}"
            + (f" with {policy.insurer_name_text}" if policy.insurer_name_text else ""),
            "source": None,
        },
        {
            "item": "Confirm the hospital is in the insurer's network",
            "detail": "Ask the insurance desk whether this hospital is cashless for this policy.",
            "source": _source_of(by_key.get("network_hospitals")),
        },
        {
            "item": "Check the eligible room category",
            "detail": _fact_line(by_key["room_category"])
            if "room_category" in by_key
            else "Room category is not recorded for this policy yet.",
            "source": _source_of(by_key.get("room_category")),
        },
        {
            "item": "Keep photo ID and the patient's date of birth ready",
            "detail": "The insurance desk will match the insured member listed on the policy.",
            "source": None,
        },
    ]
    if "waiting_period_months" in by_key or "pre_existing_waiting_months" in by_key:
        waiting = by_key.get("pre_existing_waiting_months") or by_key.get("waiting_period_months")
        checklist.append(
            {
                "item": "Check waiting periods before admission",
                "detail": _fact_line(waiting),
                "source": _source_of(waiting),
            }
        )

    preauth_steps = [
        "Contact the hospital insurance desk and say you intend to use cashless admission.",
        "Submit the pre-authorisation form with the policy number and treating doctor's note.",
        "Ask the desk for the pre-authorisation reference number and keep it.",
        "Confirm which planned procedure or diagnosis the approval names before admission.",
    ]
    if admission_type == "emergency":
        preauth_steps = [
            "Inform the hospital insurance desk within the policy's intimation window.",
            "Ask the desk to raise an emergency pre-authorisation; approval can follow admission.",
            "Give the policy number and the insured member's details at the desk.",
            "Keep every bill, discharge summary and prescription for the claim file.",
        ]
    intimation = by_key.get("claim_intimation_days")
    if intimation is not None:
        preauth_steps.append(f"Intimate the insurer within {_fact_line(intimation)} of admission.")

    questions = [
        "Is this hospital cashless for this policy, and is pre-authorisation mandatory?",
        "What room category is covered, and what happens if we take a higher category?",
        "Which expenses are excluded from this admission?",
    ]
    if "copay_percent" in by_key:
        questions.append(f"How is the {_fact_line(by_key['copay_percent'])} co-payment applied?")
    if "deductible" in by_key:
        questions.append(f"When does the {_fact_line(by_key['deductible'])} deductible apply?")
    if insured:
        questions.append("Whose share of the sum insured is being used for this admission?")
    if "sub_limit" in by_key:
        questions.append(f"Does the {_fact_line(by_key['sub_limit'])} sub-limit apply to this treatment?")

    if "required_documents" in by_key:
        documents = [part.strip() for part in _fact_line(by_key["required_documents"]).split(";") if part.strip()]
    else:
        documents = [
            "Policy copy or policy number",
            "Government photo ID of the insured member",
            "Doctor's admission advice or prescription",
            "Pre-authorisation form (for planned admissions)",
            "Previous medical records relevant to the admission",
            "Hospital estimate or bill breakdown",
        ]

    claim_steps = [
        "Intimate the insurer or TPA as soon as admission is decided.",
        "Complete pre-authorisation for cashless, or pay and collect itemised bills for reimbursement.",
        "Submit the claim form with bills, discharge summary and investigation reports.",
        "Track the claim using the reference number the insurer gives you.",
    ]
    if "claim_procedure" in by_key:
        claim_steps = [part.strip() for part in _fact_line(by_key["claim_procedure"]).split(";") if part.strip()]

    contacts = []
    for key, label in (("tpa_name", "TPA"), ("tpa_contact", "TPA contact"), ("insurer_contact", "Insurer contact")):
        if key in by_key:
            contacts.append({"label": label, "value": _fact_line(by_key[key])})

    important = [
        "sum_insured",
        "room_rent_limit",
        "icu_limit",
        "copay_percent",
        "waiting_period_months",
        "exclusions",
        "claim_intimation_days",
    ]
    data_gaps = [
        {"field_key": key, "label": field_spec(key)[0]}
        for key in important
        if key not in by_key
    ]

    warnings: list[str] = []
    if is_expired(policy):
        warnings.append(
            f"This policy's recorded validity ended on {policy.valid_to}; confirm renewal "
            "before relying on it."
        )
    if policy.archived_at is not None:
        warnings.append("This policy is archived and should not be used for a new admission.")
    if not policy.coverage_confirmed:
        warnings.append(
            "Coverage has not been verified by the insurer. Treat these values as the "
            "policyholder's information, not as an approval."
        )

    return {
        "policy_id": policy.id,
        "admission_type": admission_type,
        "insured_member_count": member_count,
        "is_family_floater": insured,
        "policy_summary": {
            "policy_number": policy.policy_number,
            "insurer": policy.insurer_name_text,
            "policy_type": str(policy.policy_type),
            "valid_from": policy.valid_from,
            "valid_to": policy.valid_to,
            "sum_insured": policy.sum_insured,
            "currency": policy.currency,
            "coverage_confirmed": policy.coverage_confirmed,
        },
        "warnings": warnings,
        "admission_checklist": checklist,
        "cashless_preauthorisation": preauth_steps,
        "insurance_desk_questions": questions,
        "required_documents": documents,
        "claim_procedure": claim_steps,
        "contacts": contacts,
        "data_gaps": data_gaps,
        "disclaimer": (
            "Guidance only, generated from the coverage information stored in BridgeCare. "
            "It is not medical advice, not a coverage approval, and not a claim submission. "
            "The insurer or TPA decides coverage."
        ),
    }


def build_guidance_with_members(
    policy: InsurancePolicy,
    facts: list[InsuranceCoverageFact],
    members: list[InsuranceInsuredMember],
    *,
    admission_type: str = "planned",
) -> dict[str, Any]:
    guidance = build_guidance(
        policy, facts, admission_type=admission_type, member_count=len(members)
    )
    guidance["insured_members"] = [
        {
            "patient_id": member.patient_id,
            "relationship": str(member.relationship),
            "name_on_policy": member.name_on_policy,
            "sum_insured_share": member.sum_insured_share,
            "is_primary": member.is_primary,
        }
        for member in members
    ]
    return guidance

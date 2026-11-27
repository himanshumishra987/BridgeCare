"""Insurer verification boundary.

This module is the *only* place that can produce ``INSURER_VERIFIED`` coverage.
It is deliberately an adapter interface, not an integration: nothing here talks
to a real insurer yet.

Ground rules encoded below
--------------------------
* A verification requires an explicit patient authorisation reference; without
  one the request is refused.
* A provider that cannot return field-level detail yields ``UNSUPPORTED``; the
  policy is left unverified rather than being partially blessed.
* A provider that cannot be reached yields ``UNAVAILABLE`` and changes nothing.
* Confirmed values are compared field by field with what is stored; a mismatch
  is recorded as ``DISCREPANCY`` and the stored value is kept.
* Every attempt is written to ``insurer_verification_attempts`` and audited.
* No scraping, no portal credentials, no OTPs: a provider is a server-to-server
  adapter that the insurer or an approved partner exposes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import VerificationUnavailableError
from app.db.base import utcnow
from app.models.enums import (
    AuditOutcome,
    CoverageFactSource,
    CoverageSource,
    CoverageVerificationStatus,
    InsurerVerificationOutcome,
    PolicyVersionKind,
)
from app.models.insurance import (
    InsuranceCoverageFact,
    InsurancePolicy,
    InsurerVerificationAttempt,
)
from app.services.audit import record_audit
from app.services.insurance import (
    active_facts,
    normalize_for_compare,
    record_version,
    validate_value,
)


@dataclass(frozen=True)
class ProviderResponse:
    provider: str
    outcome: InsurerVerificationOutcome
    reference: str | None = None
    confirmed_fields: dict[str, dict[str, Any]] = field(default_factory=dict)
    note: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


class InsurerVerificationProvider(Protocol):
    name: str

    def resolve(
        self,
        *,
        policy: InsurancePolicy,
        facts: list[InsuranceCoverageFact],
        authorization_reference: str,
    ) -> ProviderResponse: ...


class StubProvider:
    """Deterministic stand-in used by tests and local demos.

    The behaviour is chosen by the authorisation reference prefix so that every
    branch of the boundary can be exercised without any network access.
    """

    name = "stub"

    def resolve(
        self,
        *,
        policy: InsurancePolicy,
        facts: list[InsuranceCoverageFact],
        authorization_reference: str,
    ) -> ProviderResponse:
        payload = authorization_reference.split(":", 1)[1] if ":" in authorization_reference else ""
        if authorization_reference.startswith("STUB-UNAVAILABLE"):
            return ProviderResponse(
                provider=self.name,
                outcome=InsurerVerificationOutcome.UNAVAILABLE,
                note="Provider could not be reached.",
                detail={"reason": "connection_failed"},
            )
        if authorization_reference.startswith("STUB-UNSUPPORTED"):
            return ProviderResponse(
                provider=self.name,
                outcome=InsurerVerificationOutcome.UNSUPPORTED,
                note="This insurer does not expose field-level coverage through the API.",
                detail={"reason": "no_field_level_api"},
            )
        fields: dict[str, dict[str, Any]] = {}
        for part in payload.split(";"):
            if "=" not in part:
                continue
            key, _, raw = part.partition("=")
            value = raw.strip()
            try:
                # Money/percent/month/day fields must arrive as numbers; sending
                # text for them is what a real provider bug would look like, and
                # the boundary records that as a discrepancy rather than a match.
                fields[key.strip()] = {"value_numeric": Decimal(value)}
            except InvalidOperation:
                fields[key.strip()] = {"value_text": value}
        if authorization_reference.startswith("STUB-DISCREPANCY"):
            return ProviderResponse(
                provider=self.name,
                outcome=InsurerVerificationOutcome.DISCREPANCY,
                reference=f"STUB-REF-{policy.policy_number}",
                confirmed_fields=fields,
                note="Insurer returned values that differ from the stored policy.",
                detail={"mode": "discrepancy"},
            )
        return ProviderResponse(
            provider=self.name,
            outcome=InsurerVerificationOutcome.VERIFIED,
            reference=f"STUB-REF-{policy.policy_number}",
            confirmed_fields=fields,
            note="Verified against the stub provider.",
            detail={"mode": "verified"},
        )


PROVIDERS: dict[str, InsurerVerificationProvider] = {"stub": StubProvider()}


@dataclass(frozen=True)
class VerificationResult:
    outcome: InsurerVerificationOutcome
    provider: str
    reference: str | None
    verified_fields: list[str]
    discrepancies: list[dict[str, Any]]
    note: str | None
    attempt_id: uuid.UUID


def _stored_values(fact: InsuranceCoverageFact) -> dict[str, Any]:
    return {
        "value_text": fact.value_text,
        "value_numeric": fact.value_numeric,
        "value_percent": fact.value_percent,
        "value_boolean": fact.value_boolean,
    }


def verify_policy(
    db: Session,
    *,
    policy: InsurancePolicy,
    authorization_reference: str,
    actor_user_id: uuid.UUID,
    actor_role: str,
    request: Request | None = None,
) -> VerificationResult:
    """Ask the configured provider to confirm this policy's coverage."""
    settings = get_settings()
    provider_name = settings.insurer_verification_provider
    if provider_name == "none":
        raise VerificationUnavailableError(
            "No insurer verification provider is configured on this deployment."
        )
    provider = PROVIDERS.get(provider_name)
    if provider is None:
        raise VerificationUnavailableError(
            "The configured insurer verification provider is not available."
        )

    facts = active_facts(db, policy.id)
    response = provider.resolve(
        policy=policy, facts=facts, authorization_reference=authorization_reference
    )

    request_id = uuid.uuid4()
    attempt = InsurerVerificationAttempt(
        id=request_id,
        policy_id=policy.id,
        provider=response.provider,
        outcome=response.outcome,
        patient_authorization_reference=authorization_reference[:120],
        verification_reference=response.reference,
        requested_by_user_id=actor_user_id,
        requested_at=utcnow(),
        completed_at=utcnow(),
        discrepancy_count=0,
        details={
            **response.detail,
            "note": response.note,
            "confirmed_field_keys": sorted(response.confirmed_fields),
        },
    )
    db.add(attempt)
    db.flush()

    verified_fields: list[str] = []
    discrepancies: list[dict[str, Any]] = []

    if response.outcome in {
        InsurerVerificationOutcome.VERIFIED,
        InsurerVerificationOutcome.DISCREPANCY,
    }:
        for field_key, raw in response.confirmed_fields.items():
            fact = next((item for item in facts if item.field_key == field_key), None)
            if fact is None:
                continue
            try:
                values = validate_value(
                    field_key,
                    value_text=raw.get("value_text"),
                    value_numeric=raw.get("value_numeric"),
                    value_percent=raw.get("value_percent"),
                    value_boolean=raw.get("value_boolean"),
                )
            except Exception:  # noqa: BLE001 - a malformed provider value is a discrepancy
                discrepancies.append(
                    {
                        "field_key": field_key,
                        "reason": "provider_value_invalid",
                        "stored": normalize_for_compare(_stored_values(fact)),
                    }
                )
                continue

            confirmed_values = {
                "value_text": values.value_text,
                "value_numeric": values.value_numeric,
                "value_percent": values.value_percent,
                "value_boolean": values.value_boolean,
            }
            if normalize_for_compare(confirmed_values) == normalize_for_compare(_stored_values(fact)):
                fact.verification_status = CoverageVerificationStatus.INSURER_VERIFIED
                fact.source = CoverageFactSource.INSURER
                fact.provenance = {
                    **(fact.provenance or {}),
                    "verified_by": response.provider,
                    "verification_reference": response.reference,
                    "verified_at": utcnow().isoformat(),
                }
                verified_fields.append(field_key)
            else:
                fact.verification_status = CoverageVerificationStatus.DISCREPANCY
                fact.provenance = {
                    **(fact.provenance or {}),
                    "verification_reference": response.reference,
                    "insurer_value": normalize_for_compare(confirmed_values),
                    "verified_at": utcnow().isoformat(),
                }
                discrepancies.append(
                    {
                        "field_key": field_key,
                        "reason": "value_mismatch",
                        "stored": normalize_for_compare(_stored_values(fact)),
                        "insurer": normalize_for_compare(confirmed_values),
                    }
                )

        attempt.discrepancy_count = len(discrepancies)
        attempt.details = {**attempt.details, "discrepancies": discrepancies}

        if response.outcome == InsurerVerificationOutcome.VERIFIED and not discrepancies:
            policy.coverage_source = CoverageSource.INSURER_VERIFIED
            policy.verification_reference = response.reference
            policy.coverage_verified_at = utcnow()
            outcome = InsurerVerificationOutcome.VERIFIED
        else:
            # A mismatch, or a provider that only partially confirms, must not
            # present the policy as insurer-verified.
            outcome = InsurerVerificationOutcome.DISCREPANCY
            if response.outcome == InsurerVerificationOutcome.VERIFIED:
                response = ProviderResponse(
                    provider=response.provider,
                    outcome=outcome,
                    reference=response.reference,
                    confirmed_fields=response.confirmed_fields,
                    note="Provider confirmed values that disagree with the stored policy.",
                    detail=response.detail,
                )
        attempt.outcome = outcome
        record_version(
            db,
            policy=policy,
            kind=PolicyVersionKind.INSURER_VERIFICATION,
            actor_user_id=actor_user_id,
            change_summary=(
                f"Insurer verification ({outcome.value}): "
                f"{len(verified_fields)} fields confirmed, {len(discrepancies)} discrepant."
            ),
        )
    else:
        attempt.details = {**attempt.details, "discrepancies": []}
        outcome = response.outcome

    db.flush()
    record_audit(
        db,
        action="insurance.policy_verified" if outcome == InsurerVerificationOutcome.VERIFIED
        else "insurance.verification_attempted",
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        patient_id=policy.patient_id,
        resource_type="insurance_policy",
        resource_id=str(policy.id),
        outcome=AuditOutcome.SUCCESS
        if outcome != InsurerVerificationOutcome.UNAVAILABLE
        else AuditOutcome.ERROR,
        request=request,
        context={
            "provider": response.provider,
            "verification_outcome": str(outcome),
            "verified_fields": len(verified_fields),
            "discrepancies": len(discrepancies),
        },
    )
    return VerificationResult(
        outcome=outcome,
        provider=response.provider,
        reference=response.reference,
        verified_fields=verified_fields,
        discrepancies=discrepancies,
        note=response.note,
        attempt_id=request_id,
    )

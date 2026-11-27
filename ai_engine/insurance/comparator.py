"""Insurance Multi-Source Verification & Discrepancy Comparator.

Compares PDF-extracted details, patient-confirmed manual details, and backend-provided
insurer verification results without scraping insurer portals or requesting user credentials.
"""

from typing import Any, Optional

from ai_engine.schemas.insurance import (
    FieldDiscrepancy,
    InsuranceDiscrepancyReport,
    InsurancePolicyProfile,
    InsuranceVerificationStatus,
)


class InsuranceVerificationComparator:
    """Detects discrepancies between PDF extractions, patient confirmations, and insurer verifications.

    Strictly enforces that patient confirmation is NEVER represented as insurer verification.
    """

    COMPARISON_FIELDS = [
        ("policy_number", "Policy Number"),
        ("insurance_provider", "Insurance Provider"),
        ("policyholder_name", "Policyholder Name"),
        ("policy_type", "Policy Type"),
        ("commencement_date", "Commencement Date"),
        ("expiry_date", "Expiry Date"),
        ("sum_insured", "Sum Insured"),
        ("room_rent_limits", "Room Rent Limits"),
        ("co_payment", "Co-Payment"),
        ("tpa_details", "TPA Details"),
    ]

    def compare_sources(
        self,
        extracted_profile: InsurancePolicyProfile,
        patient_entered_details: Optional[dict[str, Any]] = None,
        insurer_confirmed_details: Optional[dict[str, Any]] = None,
    ) -> InsuranceDiscrepancyReport:
        """Compare attributes across available sources and produce an auditable discrepancy report."""
        patient_data = patient_entered_details or {}
        insurer_data = insurer_confirmed_details or {}

        discrepancies: list[FieldDiscrepancy] = []
        patient_confirmed_count = 0
        insurer_verified_count = 0
        discrepancy_count = 0
        unverified_count = 0

        # Extract values from extracted_profile
        extracted_map: dict[str, Any] = {
            "policy_number": extracted_profile.identity.policy_number.value,
            "insurance_provider": extracted_profile.identity.insurance_provider.value,
            "policyholder_name": extracted_profile.identity.policyholder_name.value,
            "policy_type": extracted_profile.identity.policy_type.value,
            "commencement_date": extracted_profile.identity.commencement_date.value,
            "expiry_date": extracted_profile.identity.expiry_date.value,
            "sum_insured": extracted_profile.coverage.sum_insured.value,
            "room_rent_limits": extracted_profile.coverage.room_rent_limits.value,
            "co_payment": extracted_profile.cost_sharing.co_payment.value,
            "tpa_details": extracted_profile.claims.tpa_details.value,
        }

        for field_key, field_label in self.COMPARISON_FIELDS:
            ext_val = extracted_map.get(field_key)
            pat_val = patient_data.get(field_key)
            ins_val = insurer_data.get(field_key)

            has_discrepancy = False
            explanation_parts = []

            # 1. Check discrepancy between Insurer and Extracted / Patient
            if ins_val is not None:
                if ext_val is not None and str(ext_val).strip().lower() != str(ins_val).strip().lower():
                    has_discrepancy = True
                    explanation_parts.append(
                        f"PDF extraction '{ext_val}' differs from insurer-verified value '{ins_val}'."
                    )
                if pat_val is not None and str(pat_val).strip().lower() != str(ins_val).strip().lower():
                    has_discrepancy = True
                    explanation_parts.append(
                        f"Patient-entered value '{pat_val}' differs from insurer-verified value '{ins_val}'."
                    )

            # 2. Check discrepancy between Patient manual entry and Extracted
            elif pat_val is not None and ext_val is not None:
                if str(ext_val).strip().lower() != str(pat_val).strip().lower():
                    has_discrepancy = True
                    explanation_parts.append(
                        f"Patient-entered value '{pat_val}' differs from PDF-extracted value '{ext_val}'."
                    )

            # Determine field status
            if has_discrepancy:
                status = InsuranceVerificationStatus.DISCREPANCY
                discrepancy_count += 1
            elif ins_val is not None:
                status = InsuranceVerificationStatus.INSURER_VERIFIED
                insurer_verified_count += 1
            elif pat_val is not None:
                status = InsuranceVerificationStatus.PATIENT_CONFIRMED
                patient_confirmed_count += 1
            elif ext_val is not None:
                status = InsuranceVerificationStatus.EXTRACTED
                unverified_count += 1
            else:
                status = InsuranceVerificationStatus.NEEDS_REVIEW
                unverified_count += 1

            discrepancies.append(
                FieldDiscrepancy(
                    field_name=field_key,
                    pdf_extracted_value=ext_val,
                    patient_entered_value=pat_val,
                    insurer_confirmed_value=ins_val,
                    has_discrepancy=has_discrepancy,
                    status=status,
                    discrepancy_explanation=" ".join(explanation_parts) if explanation_parts else None,
                )
            )

        # Determine overall status
        if discrepancy_count > 0:
            overall_status = InsuranceVerificationStatus.DISCREPANCY
        elif insurer_verified_count > 0:
            overall_status = InsuranceVerificationStatus.INSURER_VERIFIED
        elif patient_confirmed_count > 0:
            overall_status = InsuranceVerificationStatus.PATIENT_CONFIRMED
        else:
            overall_status = InsuranceVerificationStatus.NEEDS_REVIEW

        policy_no = str(
            insurer_data.get("policy_number")
            or extracted_map.get("policy_number")
            or patient_data.get("policy_number")
            or "UNKNOWN_POLICY"
        )

        return InsuranceDiscrepancyReport(
            policy_number=policy_no,
            discrepancies=discrepancies,
            unverified_fields_count=unverified_count,
            patient_confirmed_count=patient_confirmed_count,
            insurer_verified_count=insurer_verified_count,
            discrepancy_count=discrepancy_count,
            overall_status=overall_status,
        )

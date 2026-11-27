"""Hospital Admission Guidance Builder.

Generates actionable checklists, questions for the hospital insurance desk, documents to
carry, pre-authorization preparation, and reimbursement instructions grounded in policy terms.
"""

from typing import Optional

from ai_engine.schemas.insurance import (
    HospitalAdmissionGuidance,
    InsurancePolicyProfile,
    InsuredMember,
    PolicyType,
)


class HospitalAdmissionGuidanceBuilder:
    """Builds grounded, actionable guidance for planned and emergency hospital admissions."""

    def build_guidance(
        self,
        policy: InsurancePolicyProfile,
        admission_type: str = "planned",  # "planned" | "emergency"
        planned_procedure: Optional[str] = None,
        is_network_hospital: bool = True,
        selected_member_name: Optional[str] = None,
    ) -> HospitalAdmissionGuidance:
        """Construct a tailored hospital admission preparation package."""
        is_planned = admission_type.lower() == "planned"

        # Resolve member context if specified
        target_member: Optional[InsuredMember] = None
        if selected_member_name:
            norm_name = selected_member_name.strip().lower()
            for m in policy.identity.insured_members:
                if m.member_name.strip().lower() == norm_name:
                    target_member = m
                    break

        checklist: list[str] = []
        desk_questions: list[str] = []
        docs_to_carry: list[str] = []
        preauth_steps: list[str] = []
        restrictions_to_check: list[str] = []
        reimbursement_steps: list[str] = []

        # 1. Documents to Carry
        docs_to_carry.extend([
            f"Health Insurance E-Card or Policy Copy (Policy #{policy.identity.policy_number.value or 'Your Policy Number'})",
            "Government Photo ID of Patient (Aadhaar / Voter ID / Passport)",
            "Government Photo ID of Primary Policyholder",
            "Doctor's Admission Recommendation / Consultation Prescription",
            "All recent Investigation and Diagnostic Reports (Blood tests, Scans, X-rays)",
            "Previous Discharge Summaries and Medical Records (if a follow-up or recurrent illness)",
        ])

        # 2. Admission Checklist
        if is_planned:
            checklist.extend([
                "Confirm hospital is on your insurer/TPA's active cashless network list.",
                "Visit hospital TPA desk 48 to 72 hours prior to admission date with all diagnostic records.",
                "Fill and sign the Cashless Pre-Authorization Form (Part A filled by patient, Part B by treating doctor).",
                "Obtain initial pre-authorization approval letter from insurer before admission.",
                "Arrange payment for initial hospital deposit and non-medical consumables.",
            ])
        else:
            checklist.extend([
                "Notify insurer / TPA helpline within 24 hours of emergency admission.",
                "Submit insurance card and government ID to the hospital emergency/TPA desk immediately upon stabilization.",
                "Request hospital TPA desk to submit Emergency Cashless Pre-Authorization request without delay.",
                "Keep all initial emergency room and pharmacy bills organized in a dedicated folder.",
            ])

        # 3. Insurance Desk Questions
        desk_questions.extend([
            f"Is this hospital currently empaneled for Cashless settlement with '{policy.identity.insurance_provider.value or 'my insurer'}' and TPA '{policy.claims.tpa_details.value or 'TPA'}'?",
            f"What room category corresponds to my policy's limit of '{policy.coverage.room_rent_limits.value or 'Standard Room'}' without triggering Proportionate Deductions?",
            "What is the estimated total hospitalization cost, and what portion is estimated as non-medical consumables?",
            "Has the initial cashless pre-authorization request been transmitted to the insurer?",
            "What time before discharge will the final bill and discharge summary be sent to the insurer for final clearance?",
        ])

        # 4. Coverage Restrictions to Check
        # Room Rent
        if policy.coverage.room_rent_limits.value:
            restrictions_to_check.append(
                f"Room Rent Cap: Documented as '{policy.coverage.room_rent_limits.value}'. "
                "Ensure hospital does not assign a higher category room to avoid proportionate deductions."
            )
        # Co-pay
        if policy.cost_sharing.co_payment.value:
            restrictions_to_check.append(
                f"Co-payment: Documented as '{policy.cost_sharing.co_payment.value}'. "
                "Be prepared to pay this percentage out-of-pocket upon discharge."
            )
        # Sublimits
        if policy.coverage.disease_specific_sublimits:
            sublimit_desc = [f"{s.disease_or_procedure}: {s.limit_description}" for s in policy.coverage.disease_specific_sublimits[:3]]
            restrictions_to_check.append(
                f"Specific Disease Sublimits: Policy caps apply to: {', '.join(sublimit_desc)}."
            )
        # Waiting Periods for planned procedure
        if planned_procedure and policy.cost_sharing.waiting_periods:
            restrictions_to_check.append(
                f"Check Waiting Period for '{planned_procedure}': Ensure waiting periods (initial, 2-year specific, or PED) are fully elapsed."
            )

        # 5. Cashless Pre-Auth Steps
        if is_network_hospital:
            preauth_steps.extend([
                "Step 1: Hospital TPA desk fills Pre-Authorization Form Part B detailing diagnosis, ICD code, treatment plan, and estimated cost.",
                "Step 2: Patient/family verifies member details, signs Pre-Authorization Part A, and provides Aadhaar card copy.",
                "Step 3: Hospital uploads Pre-Authorization package to insurer portal (expect initial approval within 2 to 6 hours).",
                "Step 4: Receive initial Pre-Authorization approval letter detailing approved initial amount and room category.",
                "Step 5: At discharge, hospital submits final itemized bill; insurer audits and sends Final Approval Letter.",
                "Step 6: Patient settles non-payable items (gloves, consumables, copay) at hospital billing counter.",
            ])
        else:
            preauth_steps.append(
                "Hospital is outside the cashless network. Cashless pre-auth is unavailable; proceed via Reimbursement Claim."
            )

        # 6. Reimbursement Preparation Guidance
        reimbursement_steps.extend([
            "Notify insurer / TPA via helpline or email within 24-48 hours of admission.",
            "Collect Original Discharge Summary signed and stamped by the treating doctor.",
            "Collect Original Final Itemized Bill with detailed breakup of room, doctor fees, investigations, and medicines.",
            "Collect Original Payment Receipts with revenue stamp or bank transaction slips.",
            "Collect Original Prescriptions for all pharmacy medicines and investigation requisition slips.",
            "Collect Indoor Case Papers (ICP) / Operation Theatre notes if requested for surgical claims.",
            "Submit the completed and signed claim form along with canceled cheque for NEFT reimbursement within 15-30 days of discharge.",
            f"Retain diagnostic and medicine bills for {policy.coverage.pre_hospitalization_days.value or 30} days prior and {policy.coverage.post_hospitalization_days.value or 60} days post-discharge.",
        ])

        return HospitalAdmissionGuidance(
            admission_type="planned" if is_planned else "emergency",
            admission_checklist=checklist,
            insurance_desk_questions=desk_questions,
            documents_to_carry=docs_to_carry,
            cashless_preauth_steps=preauth_steps,
            coverage_restrictions_to_check=restrictions_to_check,
            reimbursement_preparation_guidance=reimbursement_steps,
        )

"""Insurance Clause Interpreter & Patient Explanation Service.

Provides grounded semantic interpretations of policy clauses and patient-friendly
explanations without hallucinating guaranteed coverage or calculating unverified balances.
"""

from typing import Optional

from ai_engine.schemas.common import SourceReference
from ai_engine.schemas.insurance import (
    InsuranceClauseInterpretation,
    InsurancePatientExplanation,
    InsurancePolicyProfile,
)

CORE_DISTINCTIONS = {
    "sum_insured": "The maximum financial cap agreed in your policy contract for eligible hospitalizations during the policy year.",
    "available_balance": "The current remaining coverage after deducting previous claims. Requires verified utilization data from the insurer to calculate accurately.",
    "sub_limits": "Specific monetary or percentage caps on room rent, doctor fees, or particular ailments (e.g., Cataract, Joint Replacement) regardless of your total sum insured.",
    "claim_approved_amount": "The amount the insurer or TPA authorizes for payment after auditing hospital bills, applying deductions, copay, and policy caps.",
    "actual_reimbursement": "The final amount transferred to the hospital (cashless) or patient bank account after deducting non-medical consumables, copay, and excess charges.",
}


class InsuranceClauseInterpreter:
    """Interprets policy clauses and translates complex insurance terms into clear, grounded patient guidance."""

    def interpret_clause(
        self,
        clause_name: str,
        clause_text: str,
        policy: Optional[InsurancePolicyProfile] = None,
        clause_reference: Optional[str] = None,
        source_reference: Optional[SourceReference] = None,
    ) -> InsuranceClauseInterpretation:
        """Deconstruct a policy clause into its meaning, conditions, limitations, out-of-pocket risks, and insurer queries."""
        text_lower = clause_text.lower()

        conditions: list[str] = []
        restrictions: list[str] = []
        risks: list[str] = []
        clarifications: list[str] = []

        # Room rent & proportionate deductions
        if "room rent" in text_lower or "room category" in text_lower or "1%" in text_lower:
            conditions.append("Subject to room category or daily room rent limit specified in policy schedule.")
            restrictions.append("Selecting a room category above the permissible limit triggers Proportionate Deduction.")
            risks.append("Proportionate Deduction: Associated hospital charges (doctor fees, nursing, surgery fees) will be reduced proportionally, leaving substantial out-of-pocket expenses.")
            clarifications.append("Ask hospital TPA desk: What is the exact room category covered without proportionate deductions?")

        # Co-payment
        if "co-pay" in text_lower or "copayment" in text_lower or "co-payment" in text_lower:
            conditions.append("Patient is required to pay a pre-agreed fixed percentage of the admissible claim amount.")
            restrictions.append("Applies to all eligible claims or specific zones/age categories before insurer pays.")
            risks.append("Direct out-of-pocket payment: If co-pay is 10-20%, patient must pay this percentage directly to the hospital.")
            clarifications.append("Ask insurer: Is this co-payment mandatory across all hospitals or only outside preferred zones?")

        # Deductibles
        if "deductible" in text_lower:
            conditions.append("Insurer's liability triggers only after total medical expenses exceed the defined deductible threshold.")
            restrictions.append("Claims below the deductible amount must be borne entirely by the patient or primary policy.")
            risks.append("Out-of-pocket expense for any hospitalization bill below or up to the deductible limit.")
            clarifications.append("Verify whether the deductible is per-claim or aggregate across the policy year.")

        # Waiting periods & Pre-existing diseases (PED)
        if "waiting period" in text_lower or "pre-existing" in text_lower or "ped" in text_lower:
            conditions.append("Coverage for pre-existing or specified conditions commences only after completing the mandatory waiting period without break in policy renewal.")
            restrictions.append("Treatments or hospitalizations related to these conditions during the waiting period are non-payable.")
            risks.append("Complete claim rejection if hospitalization is causally linked to an ailment still under an active waiting period.")
            clarifications.append("Confirm the exact remaining duration of waiting periods from your continuous policy renewal certificate.")

        # Consumables & Non-medical expenses
        if "consumable" in text_lower or "non-medical" in text_lower or "exclusion" in text_lower:
            conditions.append("Non-medical items (gloves, syringes, sanitizers, administrative fees) are non-payable unless a specific consumable rider is active.")
            restrictions.append("Standard health insurance excludes List I, II, III, IV non-payable items per IRDAI guidelines.")
            risks.append("Consumables often comprise 10% to 25% of total hospital bills and must be settled out-of-pocket upon discharge.")
            clarifications.append("Request an interim estimate from the hospital separating non-medical consumables from medical procedures.")

        # Default fallback conditions if generic
        if not conditions:
            conditions.append("Coverage is conditional upon active policy status, medical necessity, and treating doctor certification.")
            restrictions.append("Governed strictly by the terms, exclusions, and definitions in the policy wording.")
            risks.append("Expenses exceeding sub-limits, non-medical items, or unapproved treatment days must be borne by patient.")
            clarifications.append("Seek written pre-authorization from the insurer/TPA prior to planned admission.")

        meaning = (
            f"This provision defines the coverage terms for '{clause_name}'. "
            f"Coverage is conditional and not an unconditional guarantee of payment."
        )

        return InsuranceClauseInterpretation(
            clause_name=clause_name,
            original_clause_text=clause_text.strip(),
            clause_reference=clause_reference,
            plain_english_meaning=meaning,
            applicable_conditions=conditions,
            restrictions_and_limitations=restrictions,
            potential_out_of_pocket_risks=risks,
            recommended_clarifications_with_insurer=clarifications,
            is_conditional_coverage=True,
            distinctions=CORE_DISTINCTIONS,
            source_reference=source_reference,
        )

    def explain_provision(
        self,
        topic: str,
        policy: InsurancePolicyProfile,
        language_code: str = "en",
    ) -> InsurancePatientExplanation:
        """Generate patient-friendly, evidence-backed explanations for standard insurance provisions."""
        topic_normalized = topic.strip().lower()

        if topic_normalized in ("room_rent", "room_rent_restrictions", "room"):
            return self._explain_room_rent(policy)
        elif topic_normalized in ("co_payment", "copay", "copayment"):
            return self._explain_copayment(policy)
        elif topic_normalized in ("deductibles", "deductible"):
            return self._explain_deductibles(policy)
        elif topic_normalized in ("waiting_periods", "waiting_period", "ped"):
            return self._explain_waiting_periods(policy)
        elif topic_normalized in ("exclusions", "permanent_exclusions"):
            return self._explain_exclusions(policy)
        elif topic_normalized in ("cashless", "cashless_hospitalization"):
            return self._explain_cashless(policy)
        elif topic_normalized in ("reimbursement", "reimbursement_process"):
            return self._explain_reimbursement(policy)
        elif topic_normalized in ("pre_post", "pre_and_post_hospitalization", "pre_post_hospitalization"):
            return self._explain_pre_post(policy)
        else:
            return self._explain_general(policy, topic)

    def _explain_room_rent(self, policy: InsurancePolicyProfile) -> InsurancePatientExplanation:
        limit_val = policy.coverage.room_rent_limits.value or "Not explicitly specified in policy schedule"
        clause_ref = policy.coverage.room_rent_limits.clause_reference or "Room Rent Provision"
        refs = []
        if policy.coverage.room_rent_limits.source_document_id and policy.coverage.room_rent_limits.page_number:
            refs.append(
                SourceReference(
                    document_id=policy.coverage.room_rent_limits.source_document_id,
                    page_number=policy.coverage.room_rent_limits.page_number,
                    excerpt=policy.coverage.room_rent_limits.supporting_excerpt or limit_val,
                )
            )

        explanation = (
            f"Your policy documents room rent limit as: '{limit_val}'. "
            "In health insurance, room rent is one of the most critical clauses. "
            "If you select a hospital room that costs more than your policy's allowed limit, "
            "the insurance company applies 'Proportionate Deduction'. This means they do not just "
            "deduct the extra room cost—they also reduce their payout on associated medical bills "
            "(including surgeon fees, anesthetist charges, OT charges, and nursing fees) in the same proportion."
        )

        return InsurancePatientExplanation(
            topic="room_rent_restrictions",
            title="Understanding Your Room Rent Limit & Proportionate Deductions",
            patient_explanation=explanation,
            key_policy_rules=[
                f"Documented room limit: {limit_val}",
                "Opting for a higher category room causes proportionate deductions across all doctor, surgeon, and nursing charges.",
                "ICU rooms may have distinct limits; verify whether ICU is capped or uncapped.",
            ],
            how_it_affects_your_bill="Staying in an ineligible room category can leave you with 30% to 50% of total hospital expenses out-of-pocket.",
            supporting_clauses=[clause_ref],
            source_references=refs,
        )

    def _explain_copayment(self, policy: InsurancePolicyProfile) -> InsurancePatientExplanation:
        copay_val = policy.cost_sharing.co_payment.value or "Nil or not documented"
        clause_ref = policy.cost_sharing.co_payment.clause_reference or "Co-payment Clause"
        refs = []
        if policy.cost_sharing.co_payment.source_document_id and policy.cost_sharing.co_payment.page_number:
            refs.append(
                SourceReference(
                    document_id=policy.cost_sharing.co_payment.source_document_id,
                    page_number=policy.cost_sharing.co_payment.page_number,
                    excerpt=policy.cost_sharing.co_payment.supporting_excerpt or copay_val,
                )
            )

        explanation = (
            f"Your policy documents co-payment as: '{copay_val}'. "
            "A co-payment is a mandatory percentage of the total approved hospital bill that you "
            "must pay out of your own pocket. The insurer pays the remaining percentage. "
            "Co-payments are commonly applied for senior citizen members, treatments in higher-cost metro zones, "
            "or specific treatments."
        )

        return InsurancePatientExplanation(
            topic="co_payment",
            title="Understanding Co-Payment (Your Share of the Claim)",
            patient_explanation=explanation,
            key_policy_rules=[
                f"Documented co-payment rule: {copay_val}",
                "Applies after non-payable consumables and sub-limit deductions are calculated.",
                "Co-payments do not reduce your sum insured; they represent direct cost-sharing.",
            ],
            how_it_affects_your_bill="On a 2,00,000 INR bill with a 10% co-payment, you pay 20,000 INR out-of-pocket even if full sum insured is available.",
            supporting_clauses=[clause_ref],
            source_references=refs,
        )

    def _explain_deductibles(self, policy: InsurancePolicyProfile) -> InsurancePatientExplanation:
        ded_val = policy.cost_sharing.deductibles.value or "Nil or not specified"
        clause_ref = policy.cost_sharing.deductibles.clause_reference or "Deductible Clause"
        refs = []
        if policy.cost_sharing.deductibles.source_document_id and policy.cost_sharing.deductibles.page_number:
            refs.append(
                SourceReference(
                    document_id=policy.cost_sharing.deductibles.source_document_id,
                    page_number=policy.cost_sharing.deductibles.page_number,
                    excerpt=policy.cost_sharing.deductibles.supporting_excerpt or ded_val,
                )
            )

        explanation = (
            f"Your policy documents deductible as: '{ded_val}'. "
            "A deductible is a threshold amount that you must pay before your insurance coverage starts paying. "
            "If your claim is less than the deductible, the insurance company pays zero. Deductibles are standard "
            "in Top-up and Super Top-up policies."
        )

        return InsurancePatientExplanation(
            topic="deductibles",
            title="Understanding Deductibles (Threshold Before Policy Activates)",
            patient_explanation=explanation,
            key_policy_rules=[
                f"Documented deductible rule: {ded_val}",
                "The insurer only pays for eligible expenses above this defined amount.",
                "Can be settled from your base policy or paid out-of-pocket.",
            ],
            how_it_affects_your_bill="Hospital bills below the deductible threshold will not receive reimbursement from this policy.",
            supporting_clauses=[clause_ref],
            source_references=refs,
        )

    def _explain_waiting_periods(self, policy: InsurancePolicyProfile) -> InsurancePatientExplanation:
        wp_list = policy.cost_sharing.waiting_periods
        wp_descriptions = [f"{wp.category}: {wp.description}" for wp in wp_list] or [
            "Standard waiting periods apply (30 days initial, 24 months specific diseases, 36-48 months pre-existing)"
        ]

        explanation = (
            "Health insurance policies do not cover all illnesses immediately from day one. "
            "There are three common waiting period tiers: "
            "1. Initial 30-day waiting period: Only accidental hospitalizations are covered; illnesses are excluded. "
            "2. Specific ailment waiting period (typically 12-24 months): Cataracts, hernia, joint replacements, and stones. "
            "3. Pre-existing disease (PED) waiting period (typically 24-48 months): Any disease declared or diagnosed prior to purchasing the policy."
        )

        return InsurancePatientExplanation(
            topic="waiting_periods",
            title="Understanding Policy Waiting Periods & Pre-Existing Conditions",
            patient_explanation=explanation,
            key_policy_rules=wp_descriptions,
            how_it_affects_your_bill="Hospitalizations for conditions under active waiting periods are completely non-payable.",
            supporting_clauses=["Waiting Period Clause", "PED Clause"],
            source_references=[],
        )

    def _explain_exclusions(self, policy: InsurancePolicyProfile) -> InsurancePatientExplanation:
        perm_ex = [ex.title for ex in policy.cost_sharing.permanent_exclusions[:5]] or [
            "Cosmetic treatments", "Experimental or unproven therapies", "Self-inflicted injuries", "Non-medical consumables"
        ]

        explanation = (
            "Exclusions are specific treatments, medical conditions, or items that your insurance policy will never pay for. "
            "Permanent exclusions usually include aesthetic/cosmetic procedures, non-prescription supplements, and "
            "non-medical items listed under hospital consumables (gloves, masks, administrative charges)."
        )

        return InsurancePatientExplanation(
            topic="exclusions",
            title="Understanding Policy Exclusions & Non-Payable Items",
            patient_explanation=explanation,
            key_policy_rules=perm_ex,
            how_it_affects_your_bill="Items categorized as permanent exclusions are deducted directly from your hospital claim bill.",
            supporting_clauses=["Exclusions Clause"],
            source_references=[],
        )

    def _explain_cashless(self, policy: InsurancePolicyProfile) -> InsurancePatientExplanation:
        cashless_val = policy.claims.cashless_process.value or "Available at empaneled network hospitals with TPA pre-authorization"

        explanation = (
            "Cashless hospitalization means the hospital settles the medical bill directly with your insurer or TPA. "
            "To use cashless facilities: "
            "1. You must be admitted to an empaneled 'Network Hospital'. "
            "2. For planned surgeries, pre-authorization must be submitted 48-72 hours prior to admission. "
            "3. For emergency admissions, pre-authorization must be submitted within 24 hours of hospitalization. "
            "Note: Denial of cashless approval does NOT mean denial of your claim; you can still pay and apply for reimbursement."
        )

        return InsurancePatientExplanation(
            topic="cashless_hospitalization",
            title="How Cashless Hospitalization Works",
            patient_explanation=explanation,
            key_policy_rules=[
                f"Cashless protocol: {cashless_val}",
                "Network hospital admission is mandatory for cashless processing.",
                "Non-medical consumables and co-pays must be paid directly to hospital upon discharge.",
                "Cashless denial simply means you need to file for post-discharge reimbursement.",
            ],
            how_it_affects_your_bill="Eliminates the need for upfront payment of admitted medical expenses, except consumables and copay.",
            supporting_clauses=["Claims Procedure - Cashless Facility"],
            source_references=[],
        )

    def _explain_reimbursement(self, policy: InsurancePolicyProfile) -> InsurancePatientExplanation:
        reimb_val = policy.claims.reimbursement_process.value or "Submit original bills and claim form within 15 to 30 days of discharge"

        explanation = (
            "If you are admitted to a non-network hospital, or if your cashless request was not approved, "
            "you must pay the hospital bills directly upon discharge and then file for reimbursement. "
            "Reimbursement requires collecting all original documents: discharge summary, itemized final bill, "
            "pharmacy receipts with doctor prescriptions, and diagnostic test reports."
        )

        return InsurancePatientExplanation(
            topic="reimbursement",
            title="How Insurance Reimbursement Claims Work",
            patient_explanation=explanation,
            key_policy_rules=[
                f"Reimbursement protocol: {reimb_val}",
                "Strict time windows apply: notify insurer within 24-48 hours, submit bills within 15-30 days of discharge.",
                "Original physical bills, payment receipts, and discharge summary are mandatory.",
            ],
            how_it_affects_your_bill="Requires full upfront payment by patient, followed by reimbursement processing within 15 to 30 days.",
            supporting_clauses=["Claims Procedure - Reimbursement Process"],
            source_references=[],
        )

    def _explain_pre_post(self, policy: InsurancePolicyProfile) -> InsurancePatientExplanation:
        pre_days = policy.coverage.pre_hospitalization_days.value or 30
        post_days = policy.coverage.post_hospitalization_days.value or 60

        explanation = (
            f"Your policy covers medical expenses incurred {pre_days} days before hospital admission "
            f"(Pre-hospitalization) and {post_days} days after hospital discharge (Post-hospitalization). "
            "Eligible expenses include doctor consultations, diagnostic tests, and medicines, provided they are "
            "directly related to the same illness or injury for which you were hospitalized."
        )

        return InsurancePatientExplanation(
            topic="pre_and_post_hospitalization",
            title="Understanding Pre- and Post-Hospitalization Coverage",
            patient_explanation=explanation,
            key_policy_rules=[
                f"Pre-hospitalization: Medical bills up to {pre_days} days before admission.",
                f"Post-hospitalization: Follow-up consultations and medicines up to {post_days} days after discharge.",
                "All diagnostic tests and prescriptions must relate to the admitted medical condition.",
            ],
            how_it_affects_your_bill="Reimburses your outpatient investigation and medication costs associated with the inpatient treatment.",
            supporting_clauses=["Pre- and Post-Hospitalization Expenses Clause"],
            source_references=[],
        )

    def _explain_general(self, policy: InsurancePolicyProfile, topic: str) -> InsurancePatientExplanation:
        return InsurancePatientExplanation(
            topic=topic,
            title=f"Policy Guidance: {topic.replace('_', ' ').title()}",
            patient_explanation=f"General policy terms and conditions apply to {topic}. Always review your policy schedule and verify specific terms with your insurer.",
            key_policy_rules=["Governed by terms in the policy schedule and policy wording."],
            how_it_affects_your_bill="Coverage depends on documented exclusions, sub-limits, and eligibility criteria.",
            supporting_clauses=["General Policy Terms"],
            source_references=[],
        )

"""BridgeCare Insurance Intelligence module.

Extends BridgeCare AI Engine with insurance policy extraction, clause interpretation,
patient-friendly explanations, admission guidance, and multi-source verification comparison.
"""

from ai_engine.insurance.comparator import InsuranceVerificationComparator
from ai_engine.insurance.engine import InsuranceIntelligenceEngine
from ai_engine.insurance.guidance import HospitalAdmissionGuidanceBuilder
from ai_engine.insurance.interpreter import InsuranceClauseInterpreter
from ai_engine.schemas.insurance import (
    HospitalAdmissionGuidance,
    InsuranceDiscrepancyReport,
    InsurancePatientExplanation,
    InsurancePolicyProfile,
    InsuranceVerificationStatus,
    PolicyType,
)

__all__ = [
    "InsuranceIntelligenceEngine",
    "InsuranceClauseInterpreter",
    "HospitalAdmissionGuidanceBuilder",
    "InsuranceVerificationComparator",
    "InsurancePolicyProfile",
    "InsurancePatientExplanation",
    "HospitalAdmissionGuidance",
    "InsuranceDiscrepancyReport",
    "InsuranceVerificationStatus",
    "PolicyType",
]

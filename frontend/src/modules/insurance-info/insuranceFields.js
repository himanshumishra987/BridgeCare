/**
 * Insurance Intelligence field definitions.
 *
 * Coverage limits are kept as free text because insurers express them
 * differently ("1% of sum insured", "₹5,000 per day", "Not covered").
 * Nothing here supplies a default limit: a blank value means "not recorded".
 */

export const POLICY_TYPES = {
  private: 'Private insurer',
  ayushman_bharat: 'Ayushman Bharat (PMJAY)',
  employer: 'Employer-provided',
  state: 'State scheme',
};

export const COVERAGE_TYPES = {
  individual: 'Individual',
  family_floater: 'Family floater (one shared sum insured)',
};

export const BASE_FIELDS = [
  { name: 'insurer', label: 'Insurer / scheme name', required: true },
  { name: 'policy_number', label: 'Policy number', required: true },
  { name: 'policyholder_name', label: 'Policyholder name' },
  { name: 'type', label: 'Scheme type', select: POLICY_TYPES },
  { name: 'coverage_type', label: 'Coverage structure', select: COVERAGE_TYPES },
  { name: 'sum_insured', label: 'Sum insured for the whole policy (₹)', type: 'money' },
  { name: 'valid_from', label: 'Valid from', type: 'date' },
  { name: 'valid_until', label: 'Valid until', type: 'date' },
  { name: 'ab_card_number', label: 'Ayushman Bharat card number' },
  { name: 'insured_members', label: 'Insured members (comma separated)' },
];

export const COVERAGE_FIELDS = [
  { name: 'room_rent_limit', label: 'Room rent limit' },
  { name: 'icu_limit', label: 'ICU limit' },
  { name: 'hospitalization', label: 'Hospitalisation coverage' },
  { name: 'doctor_surgeon_charges', label: 'Doctor & surgeon charges' },
  { name: 'nursing_ot_charges', label: 'Nursing & operation theatre charges' },
  { name: 'pre_hospitalization', label: 'Pre-hospitalisation' },
  { name: 'post_hospitalization', label: 'Post-hospitalisation' },
  { name: 'day_care', label: 'Day-care procedures' },
  { name: 'ambulance', label: 'Ambulance' },
  { name: 'pharmacy', label: 'Medicines & pharmacy' },
  { name: 'diagnostics', label: 'Diagnostics' },
  { name: 'consumables', label: 'Consumables' },
  { name: 'disease_sublimits', label: 'Disease-specific sublimits' },
  { name: 'copayment', label: 'Copayment' },
  { name: 'deductible', label: 'Deductible' },
  { name: 'waiting_periods', label: 'Waiting periods' },
  { name: 'pre_existing', label: 'Pre-existing disease conditions' },
  { name: 'exclusions', label: 'Exclusions' },
  { name: 'restoration', label: 'Restoration benefit' },
  { name: 'no_claim_bonus', label: 'No-claim bonus' },
  { name: 'ayush', label: 'AYUSH coverage' },
  { name: 'maternity', label: 'Maternity' },
  { name: 'preventive', label: 'Preventive check-ups' },
];

// Verification states. Only the backend can report `insurer_verified`.
export const VERIFICATION_STATES = {
  pending: { label: 'Verification pending', className: 'bg-amber-100 text-amber-800' },
  patient_confirmed: { label: 'Patient-confirmed', className: 'bg-blue-100 text-blue-800' },
  insurer_verified: { label: 'Insurer-verified', className: 'bg-emerald-100 text-emerald-800' },
  discrepancy: { label: 'Discrepancy detected', className: 'bg-red-100 text-red-700' },
};

export const SOURCE_LABELS = {
  manual: 'Manually entered',
  pdf_extracted: 'Extracted from PDF',
  insurer_confirmed: 'Insurer-confirmed',
};

export const sourceLabel = (source) => SOURCE_LABELS[source] || 'Source not recorded';

export const money = (value) =>
  value === null || value === undefined || value === ''
    ? '—'
    : new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' }).format(Number(value));

export const dateText = (value) =>
  value
    ? new Date(value).toLocaleDateString('en-IN', { year: 'numeric', month: 'short', day: 'numeric' })
    : '—';

export const isExpired = (policy) =>
  Boolean(policy?.valid_until) && policy.valid_until < new Date().toLocaleDateString('en-CA');

export const membersOf = (policy) => {
  if (Array.isArray(policy?.insured_members)) return policy.insured_members.filter(Boolean);
  if (typeof policy?.insured_members === 'string') {
    return policy.insured_members.split(',').map((m) => m.trim()).filter(Boolean);
  }
  return [];
};

import { useState } from 'react';
import { Link } from 'react-router-dom';

export const ROLES = [
  { value: 'patient', label: 'Patient', desc: 'Manage your own health records' },
  { value: 'doctor_navigator', label: 'Doctor / Navigator', desc: 'Review records shared with you' },
  { value: 'family_member', label: 'Family Member', desc: 'View records a patient has shared' },
];

const cardClass =
  'w-full rounded-xl border border-slate-200 p-4 text-left hover:border-brand-600 hover:bg-brand-50';

function RoleCard({ label, desc, onClick, expanded }) {
  return (
    <button type="button" onClick={onClick} aria-expanded={expanded} className={cardClass}>
      <span className="block font-semibold text-slate-900">{label}</span>
      <span className="block text-sm text-slate-600">{desc}</span>
    </button>
  );
}

export default function RoleSelect({ title, onSelect, includeFamily = false }) {
  const [patientOpen, setPatientOpen] = useState(false);
  const [patient, navigator, family] = ROLES;

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4 py-12">
      <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
        <Link to="/" className="text-sm font-semibold text-brand-700">
          &larr; BridgeCare
        </Link>
        <h1 className="mt-4 text-2xl font-bold text-slate-900">{title}</h1>
        <p className="mt-1 text-sm text-slate-600">Choose how you want to continue.</p>

        <div className="mt-6 space-y-3">
          {/* Patient branch */}
          <RoleCard
            label={patient.label}
            desc={includeFamily ? 'For patients and their family members' : patient.desc}
            expanded={includeFamily ? patientOpen : undefined}
            onClick={() =>
              includeFamily ? setPatientOpen(!patientOpen) : onSelect(patient.value)
            }
          />

          {includeFamily && patientOpen && (
            <div className="ml-4 space-y-3 border-l-2 border-brand-100 pl-4">
              <RoleCard
                label="I am the patient"
                desc={patient.desc}
                onClick={() => onSelect(patient.value)}
              />
              <RoleCard
                label={family.label}
                desc={family.desc}
                onClick={() => onSelect(family.value)}
              />
            </div>
          )}

          {/* Doctor / Navigator branch */}
          <RoleCard
            label={navigator.label}
            desc={navigator.desc}
            onClick={() => onSelect(navigator.value)}
          />
        </div>
      </div>
    </div>
  );
}

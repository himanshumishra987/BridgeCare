import { useCallback, useEffect, useState } from 'react';
import {
  AlertCircle,
  CheckCircle2,
  FileText,
  Loader2,
  Plus,
  ShieldCheck,
  Upload,
} from 'lucide-react';
import { insuranceApi } from '../../api/insurance';
import EmptyState from '../../components/ui/EmptyState';
import ErrorBanner from '../../components/ui/ErrorBanner';
import LoadingSpinner from '../../components/ui/LoadingSpinner';
import PageHeader from '../../components/ui/PageHeader';
import SectionCard from '../../components/ui/SectionCard';
import StatusBadge from '../../components/ui/StatusBadge';
import { useAuth } from '../../context/AuthContext';
import AdmissionGuidance from './AdmissionGuidance';
import CoveragePanel from './CoveragePanel';
import {
  BASE_FIELDS,
  COVERAGE_FIELDS,
  COVERAGE_TYPES,
  POLICY_TYPES,
  VERIFICATION_STATES,
  dateText,
  isExpired,
  membersOf,
  money,
  sourceLabel,
} from './insuranceFields';

const STATUS_STEPS = ['pending', 'submitted', 'under_review', 'approved', 'settled', 'rejected'];

const TABS = [
  { id: 'add', label: 'Add New Insurance' },
  { id: 'saved', label: 'Saved Insurance' },
];

const inputClass =
  'mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none';

const FIELD_LABELS = Object.fromEntries(
  [...BASE_FIELDS, ...COVERAGE_FIELDS, { name: 'coverage_details', label: 'Other policy details' }].map(
    (f) => [f.name, f.label]
  )
);

const blankForm = () => ({
  ...Object.fromEntries(BASE_FIELDS.map((f) => [f.name, ''])),
  ...Object.fromEntries(COVERAGE_FIELDS.map((f) => [f.name, ''])),
  type: 'private',
  coverage_type: 'individual',
  coverage_details: '',
});

const EMPTY_EXTRACTION = {
  documentId: null,
  overallConfidence: null,
  fieldSources: {},
  fields: [],
};

const text = (v) => (v === null || v === undefined || v === '' ? '—' : v);

const confidenceText = (value) => {
  if (value === null || value === undefined || value === '') return '—';
  const n = Number(value);
  if (Number.isNaN(n)) return '—';
  return `${Math.round(n <= 1 ? n * 100 : n)}%`;
};

function VerificationBadge({ status }) {
  const meta =
    VERIFICATION_STATES[status] || {
      label: 'Verification not recorded',
      className: 'bg-slate-100 text-slate-700',
    };
  return (
    <span className={`rounded-full px-2 py-1 text-xs font-semibold ${meta.className}`}>
      {meta.label}
    </span>
  );
}

function FieldInput({ field, value, onChange }) {
  return (
    <label className={`block text-sm font-medium text-slate-700 ${field.wide ? 'sm:col-span-2' : ''}`}>
      {field.label}
      {field.required && <span className="text-red-500"> *</span>}
      {field.select ? (
        <select value={value} onChange={(e) => onChange(e.target.value)} className={inputClass}>
          {Object.entries(field.select).map(([optionValue, label]) => (
            <option key={optionValue} value={optionValue}>
              {label}
            </option>
          ))}
        </select>
      ) : (
        <input
          type={field.type === 'money' ? 'number' : field.type || 'text'}
          min={field.type === 'money' ? 0 : undefined}
          step={field.type === 'money' ? '0.01' : undefined}
          required={field.required}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className={inputClass}
        />
      )}
    </label>
  );
}

function ClaimProgress({ status }) {
  const idx = STATUS_STEPS.indexOf(status);
  return (
    <div className="mt-2 flex items-center gap-1">
      {STATUS_STEPS.slice(0, -1).map((step, i) => (
        <div key={step} className="flex items-center gap-1">
          <div className={`h-2 w-2 rounded-full ${i <= idx ? 'bg-brand-600' : 'bg-slate-200'}`} />
          {i < STATUS_STEPS.length - 2 && (
            <div className={`h-0.5 w-6 ${i < idx ? 'bg-brand-600' : 'bg-slate-200'}`} />
          )}
        </div>
      ))}
      <span className="ml-1 text-xs capitalize text-slate-500">{status?.replace(/_/g, ' ')}</span>
    </div>
  );
}

function Detail({ label, value }) {
  return (
    <div>
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className="break-words text-sm font-medium text-slate-900">{value}</dd>
    </div>
  );
}

// Backends may return structured coverage or flat coverage keys; support both.
const coverageOf = (policy) => {
  if (policy?.coverage && typeof policy.coverage === 'object') return policy.coverage;
  return Object.fromEntries(
    COVERAGE_FIELDS.filter((f) => policy?.[f.name]).map((f) => [f.name, policy[f.name]])
  );
};

export default function InsurancePage({ previewPatientId }) {
  const { user } = useAuth();
  const patientId = previewPatientId ?? user?.patient_profile?.id;

  const [tab, setTab] = useState('add');
  const [entryMode, setEntryMode] = useState('manual');

  const [policies, setPolicies] = useState([]);
  const [expenses, setExpenses] = useState([]);
  const [claims, setClaims] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [msg, setMsg] = useState('');

  const [form, setForm] = useState(blankForm);
  const [extraction, setExtraction] = useState(EMPTY_EXTRACTION);
  const [extracting, setExtracting] = useState(false);
  const [extractError, setExtractError] = useState('');
  const [adding, setAdding] = useState(false);

  const load = useCallback(async () => {
    if (!patientId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError('');
    try {
      const [pol, exp, cls] = await Promise.all([
        insuranceApi.getPolicies(patientId).catch(() => []),
        insuranceApi.getExpenses(patientId).catch(() => []),
        insuranceApi.getClaims(patientId).catch(() => []),
      ]);
      setPolicies(Array.isArray(pol) ? pol : []);
      setExpenses(Array.isArray(exp) ? exp : []);
      setClaims(Array.isArray(cls) ? cls : []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [patientId]);

  useEffect(() => {
    load();
  }, [load]);

  const setField = (name) => (value) => setForm((f) => ({ ...f, [name]: value }));

  const handleUpload = async (e) => {
    const input = e.target;
    const file = input.files?.[0];
    if (!file || !patientId) return;
    setExtractError('');
    setMsg('');
    setExtracting(true);
    try {
      const result = await insuranceApi.extractPolicy(patientId, file);
      const fields = result?.fields && typeof result.fields === 'object' ? result.fields : {};
      const known = Object.entries(fields).filter(([key]) => FIELD_LABELS[key] !== undefined);
      setForm((current) => ({
        ...current,
        ...Object.fromEntries(known.map(([key, value]) => [key, value == null ? '' : String(value)])),
      }));
      setExtraction({
        documentId: result?.document_id ?? null,
        overallConfidence: result?.overall_confidence ?? null,
        fieldSources: result?.field_sources || {},
        fields: known.map(([key]) => key),
      });
      setMsg(
        known.length > 0
          ? 'Document read. Review every extracted value before saving — nothing is confirmed yet.'
          : 'Document uploaded, but no policy fields could be extracted. Enter the details manually.'
      );
    } catch (err) {
      input.value = '';
      setExtractError(err.message);
    } finally {
      setExtracting(false);
    }
  };

  const handleSave = async (e) => {
    e.preventDefault();
    if (!patientId) {
      setError('Your patient profile is not ready yet, so insurance cannot be saved.');
      return;
    }
    setError('');
    setMsg('');

    const sum = form.sum_insured === '' ? null : Number(form.sum_insured);
    if (sum !== null && (Number.isNaN(sum) || sum < 0)) {
      setError('Sum insured must be a non-negative amount.');
      return;
    }
    if (form.valid_from && form.valid_until && form.valid_until < form.valid_from) {
      setError('"Valid until" cannot be before "Valid from".');
      return;
    }

    const coverage = {};
    COVERAGE_FIELDS.forEach((field) => {
      const value = String(form[field.name] ?? '').trim();
      if (value) coverage[field.name] = value;
    });

    setAdding(true);
    try {
      await insuranceApi.addPolicy(patientId, {
        insurer: form.insurer.trim(),
        policy_number: form.policy_number.trim(),
        policyholder_name: form.policyholder_name.trim() || null,
        type: form.type,
        coverage_type: form.coverage_type,
        sum_insured: sum,
        valid_from: form.valid_from || null,
        valid_until: form.valid_until || null,
        ab_card_number:
          form.type === 'ayushman_bharat' ? form.ab_card_number.trim() || null : null,
        insured_members: form.insured_members
          .split(',')
          .map((member) => member.trim())
          .filter(Boolean),
        coverage,
        coverage_details: form.coverage_details.trim() || null,
        source: extraction.documentId ? 'pdf_extracted' : 'manual',
        verification_status: 'patient_confirmed',
        document_id: extraction.documentId,
        field_sources: extraction.fieldSources,
      });
      setForm(blankForm());
      setExtraction(EMPTY_EXTRACTION);
      setEntryMode('manual');
      setMsg('Insurance saved. It is patient-confirmed, not insurer-verified.');
      setTab('saved');
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setAdding(false);
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Insurance & Expenses"
        subtitle="Add a policy manually or from a PDF, review coverage limits, then track hospitalisation expenses and claim status."
      />

      <div className="flex items-start gap-2.5 rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 text-xs text-blue-900">
        <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-blue-600" />
        <p>
          <strong>Important:</strong> Information here is personal record-keeping only. Entered or
          PDF-extracted details are never insurer-verified. Always confirm coverage with your insurer.
        </p>
      </div>

      <div
        role="tablist"
        aria-label="Insurance"
        className="flex gap-1 rounded-xl border border-slate-200 bg-white p-1 shadow-sm"
      >
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => {
              setTab(t.id);
              setMsg('');
            }}
            className={`flex-1 rounded-lg px-4 py-2 text-sm font-semibold transition ${
              tab === t.id ? 'bg-brand-600 text-white' : 'text-slate-600 hover:bg-slate-50'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <ErrorBanner message={error} onDismiss={() => setError('')} />
      {msg && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
          {msg}
        </div>
      )}

      {tab === 'add' && (
        <>
          <SectionCard>
            <div className="flex items-center gap-2">
              <Plus className="h-4 w-4 text-brand-600" />
              <h2 className="text-lg font-semibold text-slate-900">Add New Insurance</h2>
            </div>
            <p className="mt-1 text-sm text-slate-500">
              Choose how to enter the policy. Both routes end in the same saved policy record.
            </p>

            <div className="mt-4 inline-flex rounded-lg border border-slate-200 bg-slate-50 p-1">
              {[
                { id: 'manual', label: 'Manual entry' },
                { id: 'upload', label: 'Upload policy PDF' },
              ].map((mode) => (
                <button
                  key={mode.id}
                  type="button"
                  aria-pressed={entryMode === mode.id}
                  onClick={() => setEntryMode(mode.id)}
                  className={`rounded-md px-3 py-1.5 text-sm font-medium transition ${
                    entryMode === mode.id
                      ? 'bg-white text-brand-700 shadow-sm'
                      : 'text-slate-600 hover:text-slate-900'
                  }`}
                >
                  {mode.label}
                </button>
              ))}
            </div>

            {entryMode === 'upload' && (
              <div className="mt-4 rounded-lg border border-dashed border-slate-300 p-4">
                <label className="block text-sm font-medium text-slate-700">
                  Policy document (PDF or image)
                  <input
                    type="file"
                    accept=".pdf,application/pdf,image/png,image/jpeg"
                    disabled={extracting}
                    onChange={handleUpload}
                    className="mt-2 block w-full text-xs"
                  />
                </label>
                <p className="mt-2 text-xs text-slate-500">
                  The backend reads the document and returns candidate values with page and clause
                  references. Nothing is saved until you confirm it below.
                </p>
                {extracting && (
                  <p className="mt-2 flex items-center gap-1.5 text-sm text-slate-600">
                    <Loader2 className="h-4 w-4 animate-spin" /> Reading document…
                  </p>
                )}
                {extractError && (
                  <p role="alert" className="mt-2 text-sm text-red-700">
                    Extraction failed: {extractError} You can still enter the policy manually.
                  </p>
                )}

                {extraction.fields.length > 0 && (
                  <div className="mt-4">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="text-sm font-semibold text-slate-900">Extracted values to review</p>
                      <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-800">
                        Overall confidence {confidenceText(extraction.overallConfidence)}
                      </span>
                    </div>
                    <div className="mt-2 overflow-x-auto rounded-lg border border-slate-200">
                      <table className="w-full text-left text-sm">
                        <thead className="bg-slate-50 text-xs text-slate-500">
                          <tr>
                            <th className="px-3 py-2">Field</th>
                            <th className="px-3 py-2">Extracted value (editable)</th>
                            <th className="px-3 py-2">Page / clause</th>
                            <th className="px-3 py-2">Confidence</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-100">
                          {extraction.fields.map((name) => {
                            const src = extraction.fieldSources[name] || {};
                            return (
                              <tr key={name}>
                                <td className="px-3 py-2 font-medium text-slate-700">
                                  {FIELD_LABELS[name]}
                                </td>
                                <td className="px-3 py-2">
                                  <input
                                    type="text"
                                    value={form[name] ?? ''}
                                    onChange={(e) => setField(name)(e.target.value)}
                                    className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
                                    aria-label={`Correct ${FIELD_LABELS[name]}`}
                                  />
                                </td>
                                <td className="px-3 py-2 text-xs text-slate-600">
                                  {src.page ? `p. ${src.page}` : '—'}
                                  {src.clause ? ` · ${src.clause}` : ''}
                                </td>
                                <td className="px-3 py-2 text-xs text-slate-600">
                                  {confidenceText(src.confidence)}
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                    <p className="mt-2 text-xs text-amber-800">
                      Extracted values are unverified AI output. Correct anything wrong, then save.
                    </p>
                  </div>
                )}
              </div>
            )}

            <form onSubmit={handleSave} className="mt-5 space-y-5">
              <div>
                <h3 className="text-sm font-semibold text-slate-900">Policy identity</h3>
                <div className="mt-2 grid gap-3 sm:grid-cols-2">
                  {BASE_FIELDS.filter(
                    (f) => f.name !== 'ab_card_number' || form.type === 'ayushman_bharat'
                  ).map((field) => (
                    <FieldInput
                      key={field.name}
                      field={field}
                      value={form[field.name] ?? ''}
                      onChange={setField(field.name)}
                    />
                  ))}
                </div>
              </div>

              <div>
                <h3 className="text-sm font-semibold text-slate-900">Coverage limits</h3>
                <p className="mt-0.5 text-xs text-slate-500">
                  Record limits exactly as your policy states them. Leave a field blank if the policy
                  does not mention it — blank means “not recorded”, not “not covered”.
                </p>
                <div className="mt-2 grid gap-3 sm:grid-cols-2">
                  {COVERAGE_FIELDS.map((field) => (
                    <FieldInput
                      key={field.name}
                      field={field}
                      value={form[field.name] ?? ''}
                      onChange={setField(field.name)}
                    />
                  ))}
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-700">
                  Other policy details
                  <textarea
                    rows={3}
                    value={form.coverage_details}
                    onChange={(e) => setField('coverage_details')(e.target.value)}
                    placeholder="Free-text notes from the policy wording, exclusions, network hospitals…"
                    className={inputClass}
                  />
                </label>
              </div>

              <div className="flex flex-wrap gap-3">
                <button
                  type="submit"
                  disabled={adding || extracting}
                  className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-60"
                >
                  {adding ? 'Saving…' : 'Save Insurance'}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setForm(blankForm());
                    setExtraction(EMPTY_EXTRACTION);
                    setExtractError('');
                  }}
                  className="text-sm text-slate-500 hover:text-slate-700"
                >
                  Clear
                </button>
              </div>
            </form>
          </SectionCard>

          <AdmissionGuidance />
        </>
      )}

      {tab === 'saved' &&
        (loading ? (
          <LoadingSpinner message="Loading insurance records…" />
        ) : (
          <>
            <SectionCard>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="text-lg font-semibold text-slate-900">Saved Insurance</h2>
                <button
                  type="button"
                  onClick={() => {
                    setTab('add');
                    setMsg('');
                  }}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-brand-200 bg-brand-50 px-3 py-1.5 text-xs font-semibold text-brand-700 hover:bg-brand-100"
                >
                  <Plus className="h-3.5 w-3.5" /> Add New
                </button>
              </div>
              <p className="mt-1 text-xs text-slate-500">
                Badges distinguish manually entered, PDF-extracted, patient-confirmed,
                insurer-verified, pending and disputed records. Only your insurer can verify a policy.
              </p>

              {policies.length === 0 ? (
                <EmptyState
                  icon={ShieldCheck}
                  title="No saved insurance"
                  description="Use the Add New Insurance tab to save your first policy."
                />
              ) : (
                <div className="mt-4 space-y-4">
                  {policies.map((policy) => {
                    const members = membersOf(policy);
                    const floater = policy.coverage_type === 'family_floater';
                    return (
                      <div key={policy.id} className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                        <div className="flex flex-wrap items-start justify-between gap-2">
                          <div>
                            <p className="font-semibold text-slate-900">
                              {text(policy.insurer)}
                            </p>
                            <p className="text-xs text-slate-500">
                              Policy No: {text(policy.policy_number)}
                            </p>
                          </div>
                          <div className="flex flex-wrap items-center justify-end gap-1">
                            <StatusBadge status={policy.status || 'active'} />
                            <VerificationBadge status={policy.verification_status} />
                            <span className="rounded-full bg-slate-200 px-2 py-1 text-xs font-semibold text-slate-700">
                              {sourceLabel(policy.source)}
                            </span>
                            {isExpired(policy) && (
                              <span className="rounded-full bg-red-100 px-2 py-1 text-xs font-semibold text-red-700">
                                Expired
                              </span>
                            )}
                          </div>
                        </div>

                        <dl className="mt-3 grid gap-3 border-t border-slate-200 pt-3 sm:grid-cols-2">
                          <Detail
                            label="Policyholder"
                            value={text(policy.policyholder_name)}
                          />
                          <Detail
                            label="Scheme type"
                            value={POLICY_TYPES[policy.type] || text(policy.type)}
                          />
                          <Detail
                            label="Coverage structure"
                            value={COVERAGE_TYPES[policy.coverage_type] || 'Not recorded'}
                          />
                          <Detail
                            label="Sum insured (whole policy)"
                            value={money(policy.sum_insured)}
                          />
                          <Detail label="Valid from" value={dateText(policy.valid_from)} />
                          <Detail label="Valid until" value={dateText(policy.valid_until)} />
                          <Detail
                            label="Insured members"
                            value={members.length > 0 ? members.join(', ') : 'Not recorded'}
                          />
                          {policy.type === 'ayushman_bharat' && policy.ab_card_number && (
                            <Detail label="Ayushman Bharat card no." value={policy.ab_card_number} />
                          )}
                        </dl>

                        {floater && (
                          <p className="mt-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-xs text-blue-900">
                            Family floater: the sum insured above is shared by every insured member.
                            It is not a separate limit per person.
                          </p>
                        )}

                        <div className="mt-3">
                          <CoveragePanel
                            coverage={coverageOf(policy)}
                            fieldSources={policy.field_sources}
                          />
                        </div>

                        {policy.coverage_details && (
                          <div className="mt-3 rounded-lg border border-slate-200 bg-white px-3 py-2">
                            <p className="text-xs font-semibold text-slate-500">Other policy details</p>
                            <p className="mt-0.5 whitespace-pre-line text-sm text-slate-700">
                              {policy.coverage_details}
                            </p>
                          </div>
                        )}

                        {policy.verification_status === 'discrepancy' && (
                          <p className="mt-2 text-xs font-semibold text-red-700">
                            A discrepancy was reported for this policy. Check it with your insurer
                            before relying on these details.
                          </p>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </SectionCard>

            <SectionCard>
              <h2 className="text-lg font-semibold text-slate-900">Hospitalisation Expenses</h2>
              {expenses.length === 0 ? (
                <EmptyState icon={FileText} title="No expenses recorded" />
              ) : (
                <div className="mt-4 overflow-x-auto rounded-lg border border-slate-200">
                  <table className="w-full text-left text-sm">
                    <thead className="bg-slate-50 text-xs text-slate-500">
                      <tr>
                        <th className="px-4 py-2">Description</th>
                        <th className="px-4 py-2">Date</th>
                        <th className="px-4 py-2">Amount</th>
                        <th className="px-4 py-2">Status</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {expenses.map((exp) => (
                        <tr key={exp.id}>
                          <td className="px-4 py-2 font-medium text-slate-800">{exp.description}</td>
                          <td className="px-4 py-2 text-slate-500">{dateText(exp.date)}</td>
                          <td className="px-4 py-2 font-semibold text-slate-900">
                            {money(exp.amount_inr)}
                          </td>
                          <td className="px-4 py-2">
                            <StatusBadge status={exp.claim_status || 'pending'} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </SectionCard>

            <SectionCard>
              <h2 className="text-lg font-semibold text-slate-900">Insurance Claims</h2>
              {claims.length === 0 ? (
                <EmptyState
                  icon={ShieldCheck}
                  title="No claims filed"
                  description="Claims will appear here once they exist in your records."
                />
              ) : (
                <div className="mt-4 space-y-4">
                  {claims.map((claim) => (
                    <div key={claim.id} className="rounded-xl border border-slate-200 p-4">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <p className="font-semibold text-slate-900">{claim.description}</p>
                        <span className="text-sm font-bold text-brand-700">
                          {money(claim.amount_inr)}
                        </span>
                      </div>
                      <ClaimProgress status={claim.status} />
                      {claim.documents?.length > 0 && (
                        <div className="mt-3">
                          <p className="mb-1 text-xs font-semibold text-slate-500">Claim Documents</p>
                          <div className="flex flex-wrap gap-2">
                            {claim.documents.map((d) => (
                              <span
                                key={d.id}
                                className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2.5 py-0.5 text-xs text-slate-700"
                              >
                                <FileText className="h-3 w-3" />
                                {d.filename}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                      {claim.insurer_confirmed ? (
                        <p className="mt-2 flex items-center gap-1 text-xs font-semibold text-emerald-700">
                          <CheckCircle2 className="h-3.5 w-3.5" /> Insurer-confirmed
                        </p>
                      ) : (
                        <p className="mt-2 text-xs text-amber-700">
                          Not confirmed by the insurer. Status shown is what your records report.
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </SectionCard>

            <AdmissionGuidance />
          </>
        ))}
    </div>
  );
}

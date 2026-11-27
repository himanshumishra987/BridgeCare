import { useCallback, useEffect, useState } from 'react';
import { AlertCircle, HeartPulse, Leaf, Plus } from 'lucide-react';
import { holisticApi } from '../../api/holistic';
import EmptyState from '../../components/ui/EmptyState';
import LoadingSpinner from '../../components/ui/LoadingSpinner';
import PageHeader from '../../components/ui/PageHeader';
import SectionCard from '../../components/ui/SectionCard';
import StatusBadge from '../../components/ui/StatusBadge';
import { useAuth } from '../../context/AuthContext';

const TABS = [
  { key: 'ayush', label: 'AYUSH / Traditional' },
  { key: 'herbs', label: 'Herbs & Formulations' },
  { key: 'wellness', label: 'Wellness & Preventive' },
  { key: 'allopathy', label: 'Allopathy' },
];

const CARE_SYSTEMS = [
  'Ayurveda',
  'Yoga & Naturopathy',
  'Unani',
  'Siddha',
  'Sowa-Rigpa',
  'Homoeopathy',
  'Other traditional system',
];

const RECORD_FIELDS = [
  { name: 'title', label: 'Title', required: true },
  { name: 'date', label: 'Date', type: 'date', required: true },
  { name: 'practitioner', label: 'Practitioner' },
  { name: 'summary', label: 'Details', type: 'textarea' },
];

const AYUSH_FIELDS = [
  { name: 'care_system', label: 'Care system', options: CARE_SYSTEMS, required: true },
  ...RECORD_FIELDS,
];

const HERB_FIELDS = [
  { name: 'name', label: 'Herb or formulation name', required: true },
  { name: 'kind', label: 'Type', options: ['Single herb', 'Formulation'], required: true },
  { name: 'care_system', label: 'Care system', options: CARE_SYSTEMS },
  { name: 'ingredients', label: 'Ingredients (if known)', type: 'textarea' },
  { name: 'dose', label: 'Dose (as advised)' },
  { name: 'frequency', label: 'How often' },
  { name: 'start_date', label: 'Start date', type: 'date' },
  { name: 'stop_date', label: 'Stop date', type: 'date' },
  { name: 'advised_by', label: 'Advised by' },
  { name: 'notes', label: 'Notes', type: 'textarea' },
];

const inputClass =
  'mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none';
const buttonClass =
  'inline-flex items-center gap-1.5 rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-60';

const formatDate = (value) =>
  new Date(value).toLocaleDateString('en-IN', { year: 'numeric', month: 'long', day: 'numeric' });

// Loads a list and tracks its state: loading | ready | error | unavailable
function useList(fetcher, patientId) {
  const [state, setState] = useState({ items: [], status: 'loading', error: '' });

  const refresh = useCallback(async () => {
    if (!patientId) return;
    try {
      const data = await fetcher(patientId);
      if (!Array.isArray(data)) throw new Error('Unexpected response from the server.');
      setState({ items: data, status: 'ready', error: '' });
    } catch (err) {
      const missing = err.status === 404 || /not found/i.test(err.message);
      setState({ items: [], status: missing ? 'unavailable' : 'error', error: err.message });
    }
  }, [fetcher, patientId]);

  useEffect(() => { refresh(); }, [refresh]);

  const retry = () => {
    setState({ items: [], status: 'loading', error: '' });
    refresh();
  };

  return { ...state, refresh, retry };
}

// Wrappers keep the function identity stable and read the current API object
const fetchRecords = (id) => holisticApi.getAll(id);
const fetchHerbs = (id) => holisticApi.getHerbs(id);
const fetchWarnings = (id) => holisticApi.getWarnings(id);

function ListState({ list, loadingText, children }) {
  if (list.status === 'loading') return <LoadingSpinner message={loadingText} />;
  if (list.status === 'unavailable') {
    return (
      <p className="rounded-lg bg-amber-50 px-4 py-3 text-sm text-amber-800">
        Not available yet: the server does not provide this feature.
      </p>
    );
  }
  if (list.status === 'error') {
    return (
      <div role="alert" className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">
        Could not load: {list.error}{' '}
        <button type="button" onClick={list.retry} className="font-semibold underline">Retry</button>
      </div>
    );
  }
  return children;
}

function AddForm({ label, fields, onSave }) {
  const [form, setForm] = useState(null); // null = closed
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const open = () => {
    setForm(Object.fromEntries(fields.map((f) => [f.name, ''])));
    setError('');
  };

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    setError('');
    try {
      const payload = Object.fromEntries(
        Object.entries(form).map(([k, v]) => [k, v.trim() === '' ? null : v.trim()])
      );
      await onSave(payload);
      setForm(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  if (!form) {
    return (
      <button type="button" onClick={open} className={buttonClass}>
        <Plus className="h-4 w-4" /> {label}
      </button>
    );
  }

  return (
    <SectionCard>
      <form onSubmit={submit} aria-label={label} className="grid gap-3 sm:grid-cols-2">
        {fields.map((f) => {
          const props = {
            name: f.name,
            required: f.required,
            value: form[f.name],
            onChange: (e) => setForm({ ...form, [f.name]: e.target.value }),
            className: inputClass,
          };
          return (
            <label
              key={f.name}
              className={`block text-sm font-medium text-slate-700 ${f.type === 'textarea' ? 'sm:col-span-2' : ''}`}
            >
              {f.label}
              {f.options ? (
                <select {...props}>
                  <option value="">Select...</option>
                  {f.options.map((o) => <option key={o} value={o}>{o}</option>)}
                </select>
              ) : f.type === 'textarea' ? (
                <textarea {...props} rows={3} />
              ) : (
                <input
                  {...props}
                  type={f.type || 'text'}
                  min={f.name === 'stop_date' ? form.start_date || undefined : undefined}
                />
              )}
            </label>
          );
        })}
        {error && <p role="alert" className="text-sm text-red-700 sm:col-span-2">Could not save: {error}</p>}
        <div className="flex gap-3 sm:col-span-2">
          <button type="submit" disabled={saving} className={buttonClass}>
            {saving ? 'Saving…' : 'Save'}
          </button>
          <button type="button" disabled={saving} onClick={() => setForm(null)} className="text-sm text-slate-600">
            Cancel
          </button>
        </div>
      </form>
    </SectionCard>
  );
}

function Warnings({ list, records }) {
  // Includes flags the backend attaches to individual records
  const flagged = records
    .filter((r) => r.herb_drug_overlap)
    .map((r) => ({ id: `record-${r.id}`, explanation: r.herb_drug_overlap_note }));
  const warnings = [...list.items, ...flagged];

  return (
    <section aria-label="Herb–drug warnings" className="space-y-3 rounded-xl border border-orange-200 bg-orange-50 p-4">
      <h2 className="flex items-center gap-2 text-sm font-semibold text-orange-800">
        <AlertCircle className="h-4 w-4" /> Herb–drug warnings
      </h2>

      {list.status === 'loading' && <p className="text-sm text-orange-800">Checking for warnings…</p>}
      {list.status === 'unavailable' && (
        <p className="text-sm text-orange-800">
          Interaction warnings are not available. This does not mean there are no interactions.
        </p>
      )}
      {list.status === 'error' && (
        <p role="alert" className="text-sm text-red-700">
          Could not load warnings: {list.error}{' '}
          <button type="button" onClick={list.retry} className="font-semibold underline">Retry</button>
        </p>
      )}
      {list.status === 'ready' && warnings.length === 0 && (
        <p className="text-sm text-orange-800">
          No warnings were returned. This does not confirm that a combination is safe.
        </p>
      )}

      {warnings.map((w, i) => (
        <div key={w.id ?? i} className="rounded-lg border border-orange-200 bg-white p-3 text-sm">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="font-semibold text-slate-900">
              {w.herb && w.medicine ? `${w.herb} + ${w.medicine}` : 'Possible herb–drug overlap'}
            </p>
            <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-semibold text-slate-700">
              {w.verification_status === 'verified' ? 'Verified' : 'Unverified'}
            </span>
          </div>
          <p className="mt-1 text-slate-700">{w.explanation || 'No explanation provided.'}</p>
          {w.severity && <p className="mt-1 text-xs text-slate-600">Severity: {w.severity}</p>}
          <p className="mt-1 break-words text-xs text-slate-600">Source: {w.source || 'Not provided'}</p>
        </div>
      ))}

      <p className="text-xs font-semibold text-orange-800">
        Talk to a qualified doctor before combining, stopping or changing any medicine.
      </p>
    </section>
  );
}

export default function HolisticHealthPage({ previewPatientId }) {
  const { user } = useAuth();
  const patientId = previewPatientId ?? user?.patient_profile?.id;

  const records = useList(fetchRecords, patientId);
  const herbs = useList(fetchHerbs, patientId);
  const warnings = useList(fetchWarnings, patientId);

  const [tab, setTab] = useState('ayush');
  const [msg, setMsg] = useState('');

  const tabLabel = TABS.find((t) => t.key === tab).label;
  const filtered = records.items.filter((r) => r.system === tab);

  const saveRecord = async (data) => {
    await holisticApi.addRecord(patientId, { ...data, system: tab });
    setMsg('Record added. It is user-entered and not verified.');
    await Promise.all([records.refresh(), warnings.refresh()]);
  };

  const saveHerb = async (data) => {
    await holisticApi.addHerb(patientId, data);
    setMsg('Herb or formulation added. It is user-entered and not verified.');
    await Promise.all([herbs.refresh(), warnings.refresh()]);
  };

  const header = (
    <PageHeader
      title="Holistic Health"
      subtitle="AYUSH / traditional medicine, herbs, wellness and allopathy records in one place."
    />
  );

  if (!patientId) {
    return (
      <div className="space-y-6">
        {header}
        <SectionCard>
          <EmptyState icon={HeartPulse} title="Patient profile needed" description="Complete your profile to use this page." />
        </SectionCard>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {header}

      <Warnings list={warnings} records={records.items} />

      {msg && (
        <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
          {msg}
        </p>
      )}

      <div className="flex overflow-x-auto border-b border-slate-200">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            aria-pressed={tab === t.key}
            onClick={() => { setTab(t.key); setMsg(''); }}
            className={`shrink-0 border-b-2 px-4 py-2.5 text-sm font-medium transition ${
              tab === t.key
                ? 'border-brand-600 text-brand-700'
                : 'border-transparent text-slate-600 hover:text-slate-900'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'herbs' ? (
        <ListState list={herbs} loadingText="Loading herbs and formulations…">
          <div className="space-y-4">
            <AddForm key="herbs" label="Add herb or formulation" fields={HERB_FIELDS} onSave={saveHerb} />
            {herbs.items.length === 0 ? (
              <SectionCard>
                <EmptyState icon={Leaf} title="No herbs or formulations recorded" />
              </SectionCard>
            ) : (
              herbs.items.map((herb) => (
                <SectionCard key={herb.id}>
                  <p className="font-semibold text-slate-900">{herb.name}</p>
                  <dl className="mt-2 grid gap-2 text-sm sm:grid-cols-2">
                    {HERB_FIELDS.slice(1).filter((f) => herb[f.name]).map((f) => (
                      <div key={f.name}>
                        <dt className="text-slate-500">{f.label}</dt>
                        <dd className="break-words text-slate-900">
                          {f.type === 'date' ? formatDate(herb[f.name]) : herb[f.name]}
                        </dd>
                      </div>
                    ))}
                  </dl>
                </SectionCard>
              ))
            )}
          </div>
        </ListState>
      ) : (
        <ListState list={records} loadingText="Loading holistic records…">
          <div className="space-y-4">
            {tab !== 'allopathy' && (
              <AddForm
                key={tab}
                label={tab === 'ayush' ? 'Add AYUSH record' : 'Add wellness record'}
                fields={tab === 'ayush' ? AYUSH_FIELDS : RECORD_FIELDS}
                onSave={saveRecord}
              />
            )}
            {filtered.length === 0 ? (
              <SectionCard>
                <EmptyState
                  icon={HeartPulse}
                  title={`No ${tabLabel} records yet`}
                  description={
                    tab === 'allopathy'
                      ? 'Upload and verify relevant documents to populate this view.'
                      : 'Records you add will appear here.'
                  }
                />
              </SectionCard>
            ) : (
              filtered.map((rec) => (
                <SectionCard key={rec.id}>
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div>
                      <p className="font-semibold text-slate-900">{rec.title || rec.record_type || 'Health Record'}</p>
                      {rec.date && <p className="mt-0.5 text-xs text-slate-500">{formatDate(rec.date)}</p>}
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {rec.care_system && (
                        <span className="rounded-full bg-brand-100 px-2.5 py-0.5 text-xs font-semibold text-brand-900">
                          {rec.care_system}
                        </span>
                      )}
                      <StatusBadge status={rec.verification_status || 'pending'} />
                      {rec.is_ai_generated && (
                        <span className="rounded-full bg-blue-100 px-2.5 py-0.5 text-xs font-semibold text-blue-800">
                          AI Observation (unverified)
                        </span>
                      )}
                    </div>
                  </div>
                  {rec.summary && <p className="mt-2 break-words text-sm text-slate-700">{rec.summary}</p>}
                  {rec.practitioner && <p className="mt-1 text-xs text-slate-500">Practitioner: {rec.practitioner}</p>}
                </SectionCard>
              ))
            )}
          </div>
        </ListState>
      )}
    </div>
  );
}

import { useCallback, useEffect, useState } from 'react';
import { insuranceApi } from '../api/insuranceCard';

const inputClass =
  'mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none';
const buttonClass =
  'rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-60';

const DOCUMENT_TYPES = '.pdf,.jpg,.jpeg,.png,.webp,.heic,.tif,.tiff,.bmp,.doc,.docx';

const money = (v) =>
  new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' }).format(Number(v));
const today = () => new Date().toLocaleDateString('en-CA'); // YYYY-MM-DD, local time

const isMissingEndpoint = (err) => err.status === 404 || /not found/i.test(err.message);

const TABS = [
  { id: 'add', label: 'Add New Insurance' },
  { id: 'saved', label: 'Saved Insurance' },
];

const POLICY_FIELDS = [
  { name: 'insurer', label: 'Insurance provider', required: true },
  { name: 'policy_number', label: 'Policy number', required: true },
  { name: 'sum_insured', label: 'Sum insured', type: 'money' },
  { name: 'valid_from', label: 'Valid from', type: 'date' },
  { name: 'valid_until', label: 'Valid until', type: 'date' },
  { name: 'coverage_details', label: 'Coverage details', type: 'textarea' },
];

const CARD_FIELDS = [
  { name: 'holder_name', label: 'Card holder name', required: true },
  { name: 'card_number', label: 'Medical card number', required: true },
  { name: 'issued_by', label: 'Issued by' },
  { name: 'valid_until', label: 'Valid until', type: 'date' },
];

function display(field, value) {
  if (value === null || value === undefined || value === '') return 'Not recorded';
  if (field.type === 'money') return money(value);
  return value;
}

function Field({ field, value, onChange }) {
  const props = {
    id: field.name,
    required: field.required,
    value,
    onChange: (e) => onChange(e.target.value),
    className: inputClass,
  };
  return (
    <label className={`block text-sm font-medium text-slate-700 ${field.type === 'textarea' ? 'sm:col-span-2' : ''}`}>
      {field.label}
      {field.type === 'textarea' ? (
        <textarea
          {...props}
          rows={3}
          placeholder="What the policy covers, exclusions, room-rent limits, network hospitals…"
        />
      ) : (
        <input
          {...props}
          type={field.type === 'money' ? 'number' : field.type || 'text'}
          {...(field.type === 'money' ? { min: 0, step: '0.01' } : {})}
        />
      )}
    </label>
  );
}

// Sends the file to the backend; any details it extracts are returned for review
function DocumentUpload({ label, upload, onBusy, onResult }) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const handleChange = async (e) => {
    const input = e.target;
    const file = input.files[0];
    if (!file) return;
    setMessage('');
    setError('');
    setBusy(true);
    onBusy(true);
    try {
      const result = await upload(file);
      const filled = onResult(result);
      setMessage(
        filled
          ? `${file.name} uploaded. Check the filled details before saving.`
          : `${file.name} uploaded. No details were extracted, so enter them manually.`
      );
    } catch (err) {
      input.value = '';
      setError(err.message);
    } finally {
      setBusy(false);
      onBusy(false);
    }
  };

  return (
    <div className="rounded-lg border border-dashed border-slate-300 p-4 text-sm sm:col-span-2">
      <label className="block font-medium text-slate-700">
        {label}
        <input
          type="file"
          accept={DOCUMENT_TYPES}
          disabled={busy}
          onChange={handleChange}
          className="mt-2 block w-full text-xs"
        />
      </label>
      <p className="mt-2 text-xs text-slate-500">PDF, JPG, PNG, WEBP, HEIC, TIFF, BMP, DOC or DOCX</p>
      {busy && <p className="mt-1 text-slate-600">Uploading and reading document...</p>}
      {message && <p role="status" className="mt-1 text-brand-700">{message}</p>}
      {error && <p role="alert" className="mt-1 text-red-700">Upload failed: {error}</p>}
    </div>
  );
}

// One record section. `view` controls what it shows:
//   "add"   -> only the entry form (the Add New Insurance tab)
//   "saved" -> only the saved records (the Saved Insurance tab)
function RecordSection({
  title,
  fields,
  load,
  save,
  single = false,
  emptyText,
  upload,
  uploadLabel,
  view = 'both',
  onAddClick,
}) {
  const blankForm = () => Object.fromEntries(fields.map((f) => [f.name, '']));

  const [items, setItems] = useState([]);
  const [status, setStatus] = useState('loading'); // loading | ready | error | unavailable
  const [error, setError] = useState('');
  const [form, setForm] = useState(view === 'add' ? blankForm() : null); // null = form closed
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState('');
  const [savedMsg, setSavedMsg] = useState('');
  const [uploading, setUploading] = useState(false);
  const [documentId, setDocumentId] = useState(null);

  const refresh = useCallback(async () => {
    try {
      const data = await load();
      setItems(single ? (data ? [data] : []) : data);
      setStatus('ready');
    } catch (err) {
      setError(err.message);
      setStatus(isMissingEndpoint(err) ? 'unavailable' : 'error');
    }
  }, [load, single]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const openForm = () => {
    const current = single ? items[0] : null;
    setForm(Object.fromEntries(fields.map((f) => [f.name, current?.[f.name] ?? ''])));
    setSaveError('');
    setSavedMsg('');
    setDocumentId(null);
  };

  // Fill the form with whatever matching fields the backend extracted
  const applyExtraction = (result) => {
    setDocumentId(result?.document_id ?? null);
    const found = fields
      .map((f) => [f.name, result?.fields?.[f.name]])
      .filter(([, v]) => v !== undefined && v !== null && v !== '');
    setForm((current) => current && { ...current, ...Object.fromEntries(found) });
    return found.length > 0;
  };

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    setSaveError('');
    // Empty optional fields go as null; amounts go as numbers
    const payload = Object.fromEntries(
      fields.map((f) => {
        const v = form[f.name];
        if (v === '') return [f.name, null];
        return [f.name, f.type === 'money' ? Number(v) : v];
      })
    );
    if (documentId !== null) payload.document_id = documentId;
    try {
      await save(payload);
      if (view === 'add') {
        setForm(blankForm());
        setDocumentId(null);
        setSavedMsg('Insurance saved. Switch to the Saved Insurance tab to see it.');
      } else {
        setForm(null);
      }
      await refresh();
    } catch (err) {
      setSaveError(err.message);
    } finally {
      setSaving(false);
    }
  };

  const savedCount = status === 'ready' ? items.length : 0;
  const showAddAction = status === 'ready' && !form && (single || view === 'both' || Boolean(onAddClick));

  return (
    <section aria-label={title} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-semibold text-slate-900">{title}</h2>
        {showAddAction && (
          <button
            type="button"
            onClick={onAddClick && !single ? onAddClick : openForm}
            className={buttonClass}
          >
            {single ? (items.length ? 'Edit' : 'Add') : 'Add New'}
          </button>
        )}
      </div>

      {view !== 'add' && status === 'loading' && (
        <p className="mt-3 text-sm text-slate-500">Loading...</p>
      )}
      {view !== 'add' && status === 'unavailable' && (
        <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">
          Not available yet: the server does not provide this feature.
        </p>
      )}
      {view !== 'add' && status === 'error' && (
        <div role="alert" className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
          Could not load: {error}{' '}
          <button
            type="button"
            className="font-semibold underline"
            onClick={() => {
              setStatus('loading');
              refresh();
            }}
          >
            Retry
          </button>
        </div>
      )}

      {savedMsg && (
        <p role="status" className="mt-3 rounded-lg bg-brand-50 px-3 py-2 text-sm text-brand-800">
          {savedMsg}
        </p>
      )}

      {form && (
        <form onSubmit={submit} className="mt-4 grid gap-3 sm:grid-cols-2">
          {fields.map((f) => (
            <Field key={f.name} field={f} value={form[f.name]} onChange={(v) => setForm({ ...form, [f.name]: v })} />
          ))}
          {upload && (
            <DocumentUpload label={uploadLabel} upload={upload} onBusy={setUploading} onResult={applyExtraction} />
          )}
          {saveError && <p role="alert" className="text-sm text-red-700 sm:col-span-2">{saveError}</p>}
          <div className="flex gap-3 sm:col-span-2">
            <button type="submit" disabled={saving || uploading} className={buttonClass}>
              {saving ? 'Saving...' : 'Save'}
            </button>
            <button
              type="button"
              disabled={saving || uploading}
              onClick={() => {
                if (view === 'add') {
                  setForm(blankForm());
                  setDocumentId(null);
                  setSaveError('');
                } else {
                  setForm(null);
                }
              }}
              className="text-sm font-medium text-slate-600"
            >
              {view === 'add' ? 'Clear' : 'Cancel'}
            </button>
          </div>
        </form>
      )}

      {view !== 'add' && status === 'ready' && items.length === 0 && !form && (
        <p className="mt-3 text-sm text-slate-500">{emptyText}</p>
      )}

      {view !== 'add' && status === 'ready' && items.length > 0 && (
        <>
          {savedCount > 1 && (
            <p className="mt-3 text-xs font-semibold uppercase tracking-wider text-slate-400">
              {savedCount} saved records
            </p>
          )}
          <ul className="mt-3 space-y-3">
            {items.map((item, i) => {
              const confirmed = item.source === 'insurer_confirmed';
              const expired = item.valid_until && item.valid_until < today();
              return (
                <li key={item.id ?? i} className="rounded-xl border border-slate-200 p-4">
                  <div className="flex flex-wrap gap-2 text-xs font-semibold">
                    <span className={`rounded-full px-2 py-1 ${confirmed ? 'bg-brand-100 text-brand-900' : 'bg-slate-100 text-slate-700'}`}>
                      {confirmed ? 'Insurer-confirmed' : 'User-entered'}
                    </span>
                    {expired && <span className="rounded-full bg-red-100 px-2 py-1 text-red-700">Expired</span>}
                  </div>
                  <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
                    {fields.map((f) => (
                      <div key={f.name} className={f.type === 'textarea' ? 'sm:col-span-2' : ''}>
                        <dt className="text-slate-500">{f.label}</dt>
                        <dd className={`break-words font-medium text-slate-900 ${f.type === 'textarea' ? 'whitespace-pre-line' : ''}`}>
                          {display(f, item[f.name])}
                        </dd>
                      </div>
                    ))}
                  </dl>
                  {upload && item.documents?.length > 0 && (
                    <p className="mt-3 break-words text-sm text-slate-600">
                      Documents: {item.documents.map((d) => d.filename).join(', ')}
                    </p>
                  )}
                </li>
              );
            })}
          </ul>
        </>
      )}
    </section>
  );
}

export default function InsurancePage() {
  const [tab, setTab] = useState('add');

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold text-slate-900">Insurance & Medical Card</h1>
        <p className="mt-1 text-sm text-slate-600">
          Details you enter are not proof of coverage. Confirm any treatment coverage with your insurer.
        </p>
      </header>

      <div role="tablist" aria-label="Insurance" className="flex gap-1 rounded-xl border border-slate-200 bg-white p-1 shadow-sm">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className={`flex-1 rounded-lg px-4 py-2 text-sm font-semibold transition ${
              tab === t.id ? 'bg-brand-600 text-white' : 'text-slate-600 hover:bg-slate-50'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'add' ? (
        <RecordSection
          title="Add New Insurance"
          view="add"
          fields={POLICY_FIELDS}
          load={insuranceApi.listPolicies}
          save={insuranceApi.addPolicy}
          upload={insuranceApi.uploadPolicyDocument}
          uploadLabel="Upload policy document"
          emptyText="No policies added yet."
        />
      ) : (
        <>
          <RecordSection
            title="Saved Insurance"
            view="saved"
            fields={POLICY_FIELDS}
            load={insuranceApi.listPolicies}
            save={insuranceApi.addPolicy}
            upload={insuranceApi.uploadPolicyDocument}
            uploadLabel="Upload policy document"
            emptyText="No saved insurance yet. Add a policy from the Add New Insurance tab."
            onAddClick={() => setTab('add')}
          />
          <RecordSection
            title="Medical Card"
            view="saved"
            single
            fields={CARD_FIELDS}
            load={insuranceApi.getMedicalCard}
            save={insuranceApi.saveMedicalCard}
            upload={insuranceApi.uploadCardDocument}
            uploadLabel="Upload medical card"
            emptyText="No medical card added yet."
          />
        </>
      )}
    </div>
  );
}

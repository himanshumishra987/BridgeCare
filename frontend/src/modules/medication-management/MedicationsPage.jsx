import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, BellRing, ChevronDown, ChevronUp, Pill } from 'lucide-react';
import { medicationsApi } from '../../api/medications';
import EmptyState from '../../components/ui/EmptyState';
import ErrorBanner from '../../components/ui/ErrorBanner';
import LoadingSpinner from '../../components/ui/LoadingSpinner';
import PageHeader from '../../components/ui/PageHeader';
import SectionCard from '../../components/ui/SectionCard';
import StatusBadge from '../../components/ui/StatusBadge';
import { useAuth } from '../../context/AuthContext';

function MedCard({ med, onAddReminder }) {
  const [expanded, setExpanded] = useState(false);
  const [reminderAt, setReminderAt] = useState('');
  const [savingReminder, setSavingReminder] = useState(false);
  const [reminderMsg, setReminderMsg] = useState('');
  const [reminderError, setReminderError] = useState('');

  const submitReminder = async (e) => {
    e.preventDefault();
    setReminderMsg('');
    setReminderError('');
    setSavingReminder(true);
    try {
      await onAddReminder(med, reminderAt);
      setReminderAt('');
      setReminderMsg('Reminder saved. It also appears under Assistance & Emergency → Reminders.');
    } catch (err) {
      setReminderError(err.message);
    } finally {
      setSavingReminder(false);
    }
  };
  return (
    <div className="rounded-xl border border-slate-200 bg-white shadow-sm">
      <button
        type="button"
        onClick={() => setExpanded((p) => !p)}
        className="flex w-full items-center justify-between gap-3 p-4 text-left"
      >
        <div className="flex items-center gap-3">
          <Pill className="h-5 w-5 text-brand-600 shrink-0" />
          <div>
            <p className="font-semibold text-slate-900">{med.name}</p>
            <p className="text-xs text-slate-500">{med.dose} · {med.frequency}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge status={med.status || 'active'} label={med.status === 'discontinued' ? 'Stopped' : 'Active'} />
          {expanded ? <ChevronUp className="h-4 w-4 text-slate-400" /> : <ChevronDown className="h-4 w-4 text-slate-400" />}
        </div>
      </button>

      {expanded && (
        <div className="border-t border-slate-100 p-4 space-y-3">
          {med.generic_ingredient && (
            <p className="text-sm text-slate-700">
              <span className="font-medium">Generic ingredient:</span> {med.generic_ingredient}
            </p>
          )}
          {med.prescribed_by && (
            <p className="text-sm text-slate-700">
              <span className="font-medium">Prescribed by:</span> {med.prescribed_by}
            </p>
          )}
          {med.start_date && (
            <p className="text-sm text-slate-700">
              <span className="font-medium">Started:</span>{' '}
              {new Date(med.start_date).toLocaleDateString('en-IN', { year: 'numeric', month: 'long', day: 'numeric' })}
            </p>
          )}
          {med.end_date && (
            <p className="text-sm text-slate-700">
              <span className="font-medium">Ended:</span>{' '}
              {new Date(med.end_date).toLocaleDateString('en-IN', { year: 'numeric', month: 'long', day: 'numeric' })}
            </p>
          )}
          {med.notes && <p className="text-sm text-slate-600">{med.notes}</p>}

          {/* Reminder for this medication (backend reminder endpoint) */}
          <form onSubmit={submitReminder} className="rounded-lg border border-slate-200 bg-slate-50 p-3">
            <label className="block text-xs font-semibold text-slate-700">
              Remind me to take {med.name}
              <div className="mt-1 flex flex-wrap gap-2">
                <input
                  type="datetime-local"
                  value={reminderAt}
                  onChange={(e) => setReminderAt(e.target.value)}
                  className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
                />
                <button
                  type="submit"
                  disabled={savingReminder}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-brand-600 px-3 py-2 text-xs font-semibold text-white disabled:opacity-60"
                >
                  <BellRing className="h-3.5 w-3.5" /> {savingReminder ? 'Saving…' : 'Add reminder'}
                </button>
              </div>
            </label>
            {reminderMsg && <p role="status" className="mt-1 text-xs text-emerald-700">{reminderMsg}</p>}
            {reminderError && <p role="alert" className="mt-1 text-xs text-red-700">Could not save reminder: {reminderError}</p>}
          </form>
        </div>
      )}
    </div>
  );
}

export default function MedicationsPage() {
  const { user } = useAuth();
  const patientId = user?.patient_profile?.id;

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [msg, setMsg] = useState('');

  const load = useCallback(async () => {
    if (!patientId) return;
    setLoading(true);
    setError('');
    try {
      const res = await medicationsApi.getAll(patientId);
      setData(res);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [patientId]);

  useEffect(() => { load(); }, [load]);

  const handleAddReminder = (med, scheduledAt) =>
    medicationsApi.addReminder(patientId, med.id, {
      text: `Take ${med.name}${med.dose ? ` (${med.dose})` : ''}`,
      scheduled_at: scheduledAt || undefined,
    });

  const handleDismissInteraction = async (interactionId) => {
    try {
      await medicationsApi.dismissInteraction(patientId, interactionId);
      setMsg('Interaction dismissed from your alerts. Your prescriber should still review it.');
      await load();
    } catch (err) {
      setError(err.message);
    }
  };

  const current = data?.current || [];
  const previous = data?.previous || [];
  const interactions = data?.interactions || [];
  const duplicates = data?.duplicates || [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Medications"
        subtitle="Your current and previous prescriptions, duplicate ingredient alerts, and interaction notices."
      />
      <ErrorBanner message={error} onDismiss={() => setError('')} />
      {msg && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
          {msg}
        </div>
      )}

      {loading ? (
        <LoadingSpinner message="Loading medications…" />
      ) : (
        <>
          {/* Alerts */}
          {duplicates.length > 0 && (
            <div className="rounded-xl border border-orange-200 bg-orange-50 p-4 space-y-1">
              <p className="flex items-center gap-2 text-sm font-semibold text-orange-800">
                <AlertTriangle className="h-4 w-4" /> Duplicate molecule detected
              </p>
              {duplicates.map((d, i) => (
                <p key={i} className="text-xs text-orange-700 pl-6">{d.message}</p>
              ))}
            </div>
          )}
          {interactions.length > 0 && (
            <div className="rounded-xl border border-red-200 bg-red-50 p-4 space-y-2">
              <p className="flex items-center gap-2 text-sm font-semibold text-red-800">
                <AlertTriangle className="h-4 w-4" /> Potential medication interactions
              </p>
              {interactions.map((ia, i) => (
                <div key={ia.id ?? i} className="rounded-lg bg-white border border-red-100 px-3 py-2 text-xs text-red-700">
                  <p className="font-medium">{ia.drugs?.join(' + ')}</p>
                  <p>{ia.description}</p>
                  <p className="mt-1 font-semibold text-red-900">Consult your doctor before changing any medication.</p>
                  <div className="mt-2 flex flex-wrap items-center gap-3">
                    {ia.severity && <span className="text-slate-600">Severity: {ia.severity}</span>}
                    {ia.source && <span className="break-words text-slate-600">Source: {ia.source}</span>}
                    {ia.id && (
                      <button
                        type="button"
                        onClick={() => handleDismissInteraction(ia.id)}
                        className="font-semibold underline"
                      >
                        Dismiss alert
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Current */}
          <SectionCard>
            <h2 className="text-lg font-semibold text-slate-900">Current Prescriptions</h2>
            {current.length === 0 ? (
              <EmptyState icon={Pill} title="No current medications" description="Verified prescriptions will appear here." />
            ) : (
              <div className="mt-4 space-y-3">
                {current.map((med) => (
                  <MedCard key={med.id} med={med} onAddReminder={handleAddReminder} />
                ))}
              </div>
            )}
          </SectionCard>

          {/* Previous */}
          {previous.length > 0 && (
            <SectionCard>
              <h2 className="text-lg font-semibold text-slate-900">Previous Prescriptions</h2>
              <div className="mt-4 space-y-3">
                {previous.map((med) => (
                  <MedCard key={med.id} med={med} onAddReminder={handleAddReminder} />
                ))}
              </div>
            </SectionCard>
          )}

          <div className="flex items-start gap-3 rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700">
            <BellRing className="mt-0.5 h-5 w-5 shrink-0 text-brand-600" />
            <p>
              Open a medication to add a reminder. Interaction alerts come from the backend and are
              never calculated in the browser; dismissing an alert does not change that assessment.
            </p>
          </div>
        </>
      )}
    </div>
  );
}

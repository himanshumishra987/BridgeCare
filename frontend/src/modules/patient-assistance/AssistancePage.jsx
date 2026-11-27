import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, BellRing, Heart, Mic, MicOff, MapPin, Phone, Plus, Trash2 } from 'lucide-react';
import { assistanceApi } from '../../api/assistance';
import { LANGUAGES } from '../../config/languages';
import ChatWidget from '../../components/ui/ChatWidget';
import EmptyState from '../../components/ui/EmptyState';
import ErrorBanner from '../../components/ui/ErrorBanner';
import LoadingSpinner from '../../components/ui/LoadingSpinner';
import PageHeader from '../../components/ui/PageHeader';
import SectionCard from '../../components/ui/SectionCard';
import { useAuth } from '../../context/AuthContext';

export default function AssistancePage() {
  const { user } = useAuth();
  const patientId = user?.patient_profile?.id;

  const [profile, setProfile] = useState(null);
  const [reminders, setReminders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [msg, setMsg] = useState('');

  // Assistant language
  const [lang, setLang] = useState(user?.preferred_language || 'en');

  // Reminder form
  const [reminderText, setReminderText] = useState('');
  const [reminderTime, setReminderTime] = useState('');
  const [addingReminder, setAddingReminder] = useState(false);

  // Emergency contact edit
  const [savingContacts, setSavingContacts] = useState(false);
  const [contacts, setContacts] = useState('');

  // Nearby hospital directory
  const [hospitals, setHospitals] = useState([]);
  const [hospitalState, setHospitalState] = useState('idle'); // idle | loading | ready | error | denied
  const [hospitalError, setHospitalError] = useState('');

  const load = useCallback(async () => {
    if (!patientId) return;
    setLoading(true);
    setError('');
    try {
      const [prof, rems] = await Promise.all([
        assistanceApi.getEmergencyProfile(patientId).catch(() => null),
        assistanceApi.getReminders(patientId).catch(() => []),
      ]);
      setProfile(prof);
      setContacts(prof?.emergency_contacts || '');
      setReminders(Array.isArray(rems) ? rems : []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [patientId]);

  useEffect(() => { load(); }, [load]);

  const handleAsk = async (question) => {
    const data = await assistanceApi.askAssistant(patientId, { question, language: lang });
    return {
      answer: data?.answer || 'No answer returned.',
      sources: data?.sources,
      uncertainty: data?.uncertainty,
      disclaimer: data?.disclaimer,
    };
  };

  const findHospitals = () => {
    if (!navigator.geolocation) {
      setHospitalState('error');
      setHospitalError('This browser does not support location access.');
      return;
    }
    setHospitalState('loading');
    setHospitalError('');
    navigator.geolocation.getCurrentPosition(
      async ({ coords }) => {
        try {
          const data = await assistanceApi.getNearbyHospitals(coords.latitude, coords.longitude);
          setHospitals(Array.isArray(data) ? data : []);
          setHospitalState('ready');
        } catch (err) {
          setHospitalError(err.message);
          setHospitalState('error');
        }
      },
      (err) => {
        setHospitalError(err.message || 'Location permission was refused.');
        setHospitalState('denied');
      },
      { timeout: 10000 }
    );
  };

  const handleAddReminder = async (e) => {
    e.preventDefault();
    if (!reminderText) return;
    setAddingReminder(true);
    try {
      await assistanceApi.addReminder(patientId, { text: reminderText, scheduled_at: reminderTime || undefined });
      setReminderText('');
      setReminderTime('');
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setAddingReminder(false);
    }
  };

  const handleDeleteReminder = async (id) => {
    try {
      await assistanceApi.deleteReminder(patientId, id);
      await load();
    } catch (err) {
      setError(err.message);
    }
  };

  const handleSaveContacts = async () => {
    setSavingContacts(true);
    try {
      await assistanceApi.updateEmergencyContacts(patientId, { emergency_contacts: contacts });
      setMsg('Emergency contacts saved.');
    } catch (err) {
      setError(err.message);
    } finally {
      setSavingContacts(false);
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Assistance & Emergency"
        subtitle="Your multilingual health assistant, emergency contacts, reminders, and nearby hospital finder."
      />

      {/* Emergency disclaimer */}
      <div className="flex items-start gap-2.5 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-xs text-red-900">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-red-600" />
        <p>
          <strong>Emergency Disclaimer:</strong> In a medical emergency, call 112 or your local
          emergency number immediately. BridgeCare cannot contact emergency services on your behalf.
        </p>
      </div>

      <ErrorBanner message={error} onDismiss={() => setError('')} />
      {msg && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{msg}</div>
      )}

      {loading ? (
        <LoadingSpinner message="Loading assistance…" />
      ) : (
        <>
          {/* Emergency Health Summary */}
          {profile && (
            <SectionCard>
              <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-900">
                <Heart className="h-5 w-5 text-red-500" /> Emergency Health Summary
              </h2>
              <div className="mt-4 grid gap-3 sm:grid-cols-3">
                {[
                  { label: 'Blood Group', value: profile.blood_group || user?.patient_profile?.blood_group },
                  { label: 'Allergies', value: profile.allergies },
                  { label: 'Key Conditions', value: profile.conditions },
                ].map((item) => (
                  <div key={item.label} className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                    <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide">{item.label}</p>
                    <p className="mt-1 text-sm font-semibold text-slate-900">{item.value || '—'}</p>
                  </div>
                ))}
              </div>
            </SectionCard>
          )}

          {/* Emergency contacts */}
          <SectionCard>
            <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-900">
              <Phone className="h-5 w-5 text-brand-600" /> Emergency Contacts
            </h2>
            <textarea
              value={contacts}
              onChange={(e) => setContacts(e.target.value)}
              rows={3}
              placeholder="Name and phone number (e.g. Priya Sharma – +91 98765 43210)"
              className="mt-3 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none"
            />
            <button
              type="button"
              onClick={handleSaveContacts}
              disabled={savingContacts}
              className="mt-2 rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-60"
            >
              {savingContacts ? 'Saving…' : 'Save Contacts'}
            </button>
          </SectionCard>

          {/* Multilingual assistant */}
          <SectionCard>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-lg font-semibold text-slate-900">Health Assistant</h2>
              <div className="flex items-center gap-2">
                <select
                  value={lang}
                  onChange={(e) => setLang(e.target.value)}
                  className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm"
                >
                  {LANGUAGES.map((l) => (
                    <option key={l.value} value={l.value}>{`${l.native} (${l.label})`}</option>
                  ))}
                </select>
                <button
                  type="button"
                  disabled
                  title="Voice interaction requires backend integration — coming soon"
                  className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-400 cursor-not-allowed"
                >
                  <MicOff className="h-4 w-4" /> Voice (unavailable)
                </button>
              </div>
            </div>
            <div className="mt-3">
              <ChatWidget
                onSend={handleAsk}
                placeholder="Ask about your medications, next appointment…"
                systemNote="Answers based on your verified health records. Not medical advice."
              />
            </div>
          </SectionCard>

          {/* Reminders */}
          <SectionCard>
            <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-900">
              <BellRing className="h-5 w-5 text-brand-600" /> Reminders
            </h2>
            <form onSubmit={handleAddReminder} className="mt-4 flex flex-wrap gap-3">
              <input
                type="text"
                required
                value={reminderText}
                onChange={(e) => setReminderText(e.target.value)}
                placeholder="Take blood pressure medication"
                className="flex-1 min-w-48 rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
              <input
                type="datetime-local"
                value={reminderTime}
                onChange={(e) => setReminderTime(e.target.value)}
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
              <button
                type="submit"
                disabled={addingReminder}
                className="inline-flex items-center gap-1.5 rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-60"
              >
                <Plus className="h-4 w-4" /> Add
              </button>
            </form>

            {reminders.length === 0 ? (
              <EmptyState icon={BellRing} title="No reminders set" description="Add a reminder above." />
            ) : (
              <ul className="mt-4 divide-y divide-slate-100">
                {reminders.map((rem) => (
                  <li key={rem.id} className="flex items-center justify-between gap-3 py-3">
                    <div>
                      <p className="text-sm font-medium text-slate-900">{rem.text}</p>
                      {rem.scheduled_at && (
                        <p className="text-xs text-slate-500">
                          {new Date(rem.scheduled_at).toLocaleString('en-IN')}
                        </p>
                      )}
                    </div>
                    <button
                      type="button"
                      onClick={() => handleDeleteReminder(rem.id)}
                      className="text-red-500 hover:text-red-700"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </SectionCard>

          {/* Nearby hospitals */}
          <SectionCard>
            <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-900">
              <MapPin className="h-5 w-5 text-brand-600" /> Nearby Hospitals
            </h2>
            <div className="mt-3 space-y-3">
              <button
                type="button"
                onClick={findHospitals}
                disabled={hospitalState === 'loading'}
                className="inline-flex items-center gap-1.5 rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-60"
              >
                <MapPin className="h-4 w-4" />
                {hospitalState === 'loading' ? 'Finding hospitals…' : 'Find hospitals near me'}
              </button>
              <p className="text-xs text-slate-500">
                Uses your device location once, only to query the backend hospital directory.
                BridgeCare does not rank or endorse any hospital.
              </p>

              {hospitalState === 'denied' && (
                <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                  Location permission was refused, so nearby hospitals cannot be listed. In an
                  emergency call 112 or your local emergency number.
                </p>
              )}
              {hospitalState === 'error' && (
                <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                  Could not load hospitals: {hospitalError}{' '}
                  <button type="button" onClick={findHospitals} className="font-semibold underline">
                    Retry
                  </button>
                </p>
              )}
              {hospitalState === 'ready' && hospitals.length === 0 && (
                <EmptyState
                  icon={MapPin}
                  title="No hospitals returned"
                  description="The directory returned no results for your location."
                />
              )}
              {hospitalState === 'ready' && hospitals.length > 0 && (
                <ul className="divide-y divide-slate-100 rounded-xl border border-slate-200">
                  {hospitals.map((hospital, i) => (
                    <li key={hospital.id ?? i} className="px-4 py-3 text-sm">
                      <p className="font-semibold text-slate-900">
                        {hospital.name || 'Hospital name not provided'}
                      </p>
                      {hospital.address && (
                        <p className="text-xs text-slate-600">{hospital.address}</p>
                      )}
                      <div className="mt-1 flex flex-wrap items-center gap-3 text-xs text-slate-600">
                        {hospital.distance_km != null && (
                          <span>{Number(hospital.distance_km).toFixed(1)} km away</span>
                        )}
                        {hospital.phone && (
                          <a href={`tel:${hospital.phone}`} className="font-semibold text-brand-700">
                            <Phone className="mr-1 inline h-3 w-3" />
                            {hospital.phone}
                          </a>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </SectionCard>
        </>
      )}
    </div>
  );
}

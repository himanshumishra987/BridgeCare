import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { LANGUAGES } from '../config/languages';
import { useAuth } from '../context/AuthContext';
import { getHomePathForRole } from '../components/RouteGuards';

export default function ProfileSetupPage() {
  const { user, updateProfile } = useAuth();
  const navigate = useNavigate();
  const profile = user?.patient_profile || {};

  const [form, setForm] = useState({
    name: user?.name || '',
    preferred_language: user?.preferred_language || 'en',
    dob_or_age: profile.dob_or_age || '',
    gender: profile.gender || '',
    blood_group: profile.blood_group || '',
    phone: profile.phone || '',
    emergency_contact: profile.emergency_contact || '',
  });
  const [savedMessage, setSavedMessage] = useState('');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSaving(true);
    setError('');
    setSavedMessage('');
    try {
      const updated = await updateProfile(form);
      setSavedMessage('Profile saved.');
      navigate(getHomePathForRole(updated.role));
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="mx-auto max-w-2xl rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h1 className="text-xl font-bold text-slate-900">Profile Setup</h1>
      <p className="mt-1 text-sm text-slate-600">
        Keep your core identity and emergency contact basics up to date.
      </p>

      {error && (
        <div className="mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </div>
      )}
      {savedMessage && (
        <div className="mt-4 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
          {savedMessage}
        </div>
      )}

      <form onSubmit={handleSubmit} className="mt-6 grid gap-4 sm:grid-cols-2">
        <div className="sm:col-span-2">
          <label htmlFor="profile-name" className="block text-sm font-medium text-slate-700">
            Full name
          </label>
          <input
            id="profile-name"
            type="text"
            required
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
          />
        </div>

        <div>
          <label htmlFor="profile-language" className="block text-sm font-medium text-slate-700">
            Preferred Language
          </label>
          <select
            id="profile-language"
            value={form.preferred_language}
            onChange={(e) => setForm({ ...form, preferred_language: e.target.value })}
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
          >
            {LANGUAGES.map((l) => (
              <option key={l.value} value={l.value}>{`${l.native} (${l.label})`}</option>
            ))}
          </select>
        </div>

        {user?.role === 'patient' && (
          <>
            <div>
              <label htmlFor="profile-dob" className="block text-sm font-medium text-slate-700">
                Date of Birth or Age
              </label>
              <input
                id="profile-dob"
                type="text"
                value={form.dob_or_age}
                onChange={(e) => setForm({ ...form, dob_or_age: e.target.value })}
                placeholder="e.g. 1988-05-14 or 38 yrs"
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label htmlFor="profile-gender" className="block text-sm font-medium text-slate-700">
                Gender
              </label>
              <input
                id="profile-gender"
                type="text"
                value={form.gender}
                onChange={(e) => setForm({ ...form, gender: e.target.value })}
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label htmlFor="profile-blood-group" className="block text-sm font-medium text-slate-700">
                Blood Group
              </label>
              <input
                id="profile-blood-group"
                type="text"
                value={form.blood_group}
                onChange={(e) => setForm({ ...form, blood_group: e.target.value })}
                placeholder="e.g. O+"
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label htmlFor="profile-phone" className="block text-sm font-medium text-slate-700">
                Phone
              </label>
              <input
                id="profile-phone"
                type="text"
                value={form.phone}
                onChange={(e) => setForm({ ...form, phone: e.target.value })}
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
            </div>
            <div className="sm:col-span-2">
              <label htmlFor="profile-emergency-contact" className="block text-sm font-medium text-slate-700">
                Emergency Contact
              </label>
              <input
                id="profile-emergency-contact"
                type="text"
                value={form.emergency_contact}
                onChange={(e) => setForm({ ...form, emergency_contact: e.target.value })}
                placeholder="Name and phone number (directory info only)"
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
            </div>
          </>
        )}

        <div className="sm:col-span-2">
          <button
            type="submit"
            disabled={saving}
            className="rounded-lg bg-brand-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-60"
          >
            {saving ? 'Saving...' : 'Save & Continue'}
          </button>
        </div>
      </form>
    </div>
  );
}

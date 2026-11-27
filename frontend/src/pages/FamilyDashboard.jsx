import { useEffect, useState } from 'react';
import { apiRequest } from '../api/client';
import { useAuth } from '../context/AuthContext';

export default function FamilyDashboard() {
  const { user } = useAuth();
  const [sharedPatients, setSharedPatients] = useState([]);
  const [error, setError] = useState('');

  useEffect(() => {
    apiRequest('/patients/accessible')
      .then(setSharedPatients)
      .catch((err) => setError(err.message));
  }, []);

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h1 className="text-2xl font-bold text-slate-900">Family Shared View</h1>
      <p className="mt-1 text-sm text-slate-600">
        Signed in as <strong>{user?.name}</strong>. Access is granted strictly by explicit patient
        consent—family relationships alone never expose records.
      </p>

      {error && (
        <div className="mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="mt-5 space-y-3">
        {sharedPatients.length === 0 ? (
          <p className="text-sm text-slate-500">No family records are currently shared with you.</p>
        ) : (
          sharedPatients.map((item) => (
            <div key={item.grant_id} className="rounded-xl border border-slate-200 p-4">
              <p className="font-semibold text-slate-900">{item.patient_name}</p>
              <p className="mt-1 text-xs text-slate-600">
                Permitted scopes: {item.scopes.join(', ')}
              </p>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

import { useCallback, useEffect, useState } from 'react';
import { patientsApi } from '../api/patients';
import { asArray, expectArray } from '../api/shape';
import SectionState, { failedSection, loadingSection, readySection } from '../components/ui/SectionState';
import { useAuth } from '../context/AuthContext';

export default function FamilyDashboard() {
  const { user } = useAuth();
  const [sharedPatients, setSharedPatients] = useState([]);
  const [listState, setListState] = useState(loadingSection);

  const load = useCallback(async () => {
    setListState(loadingSection());
    try {
      setSharedPatients(expectArray(await patientsApi.getAccessible(), 'your shared family records'));
      setListState(readySection());
    } catch (err) {
      setListState(failedSection(err));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h1 className="text-2xl font-bold text-slate-900">Family Shared View</h1>
      <p className="mt-1 text-sm text-slate-600">
        Signed in as <strong>{user?.name || 'unknown user'}</strong>. Access is granted strictly by
        explicit patient consent—family relationships alone never expose records.
      </p>

      <SectionState state={listState} label="your shared family records" onRetry={load} />
      {listState.status === 'error' && sharedPatients.length > 0 && (
        <p className="mt-2 text-xs text-slate-500">
          Showing records loaded earlier; the latest refresh failed.
        </p>
      )}

      <div className="mt-5 space-y-3">
        {listState.status === 'ready' && sharedPatients.length === 0 && (
          <p className="text-sm text-slate-500">No family records are currently shared with you.</p>
        )}
        {sharedPatients.map((item) => (
          <div key={item.grant_id || item.patient_id} className="rounded-xl border border-slate-200 p-4">
            <p className="font-semibold text-slate-900">{item.patient_name || 'Unnamed patient'}</p>
            <p className="mt-1 text-xs text-slate-600">
              Permitted scopes: {asArray(item.scopes).join(', ') || 'none reported'}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}

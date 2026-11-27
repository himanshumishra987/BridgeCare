import { useEffect, useState } from 'react';
import { insuranceApi } from '../api/insurance';
import InsurancePage from '../modules/insurance-info/InsurancePage';

/**
 * Development preview only. Records live in browser memory and vanish on refresh.
 * No policy data is seeded: PDF extraction returns no fields, so nothing that looks
 * like a real policy or coverage limit is ever shown.
 */
function createMemoryApi() {
  const db = { policies: [], expenses: [], claims: [] };
  let nextId = 1;

  return {
    getPolicies: async () => db.policies.map((policy) => ({ ...policy })),
    addPolicy: async (_patientId, data) => {
      db.policies.push({ ...data, id: nextId++ });
    },
    getExpenses: async () => [],
    getClaims: async () => [],
    extractPolicy: async () => ({
      document_id: nextId++,
      fields: {},
      field_sources: {},
      overall_confidence: null,
    }),
  };
}

export default function InsuranceModulePreview() {
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const original = { ...insuranceApi };
    Object.assign(insuranceApi, createMemoryApi());
    setReady(true);
    return () => Object.assign(insuranceApi, original);
  }, []);

  if (!ready) return null;

  return (
    <div className="min-h-screen bg-slate-50 px-4 py-6">
      <div className="mx-auto max-w-4xl space-y-4">
        <p className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm font-semibold text-amber-800">
          Preview mode: nothing is sent to a server and no policy data is pre-filled. Records
          disappear when you refresh.
        </p>
        <InsurancePage previewPatientId="preview" />
      </div>
    </div>
  );
}

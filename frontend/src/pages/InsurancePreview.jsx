import { useEffect, useState } from 'react';
import { insuranceApi } from '../api/insuranceCard';
import InsurancePage from './InsurancePage';

// Development preview only: records stay in browser memory and vanish on refresh.
function createMemoryApi() {
  const db = { policies: [], card: null };
  let nextId = 1;
  const list = (key) => async () => db[key].map((item) => ({ ...item }));
  const files = new Map(); // document_id -> file details
  const attached = (data, previous = []) =>
    files.has(data.document_id) ? [files.get(data.document_id)] : previous;
  const add = (key) => async (data) => {
    db[key].push({ ...data, id: nextId++, documents: attached(data) });
  };
  // No OCR in preview, so no fields are returned
  const uploadDocument = async (file) => {
    const id = nextId++;
    files.set(id, { id, filename: file.name });
    return { document_id: id, fields: {} };
  };

  return {
    uploadPolicyDocument: uploadDocument,
    uploadCardDocument: uploadDocument,
    listPolicies: list('policies'),
    addPolicy: add('policies'),
    getMedicalCard: async () => db.card && { ...db.card },
    saveMedicalCard: async (data) => {
      db.card = { ...data, documents: attached(data, db.card?.documents) };
    },
  };
}

export default function InsurancePreview() {
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const original = { ...insuranceApi };
    Object.assign(insuranceApi, createMemoryApi());
    setReady(true);
    // Put the real API back when leaving the preview
    return () => Object.assign(insuranceApi, original);
  }, []);

  if (!ready) return null;

  return (
    <div className="min-h-screen bg-slate-50 px-4 py-6">
      <div className="mx-auto max-w-4xl space-y-4">
        <p className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm font-semibold text-amber-800">
          Preview mode: nothing is sent to a server. Records disappear when you refresh.
        </p>
        <InsurancePage />
      </div>
    </div>
  );
}

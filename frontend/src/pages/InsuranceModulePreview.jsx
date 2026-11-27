import { useState } from 'react';
import InsurancePage from '../modules/insurance-info/InsurancePage';

/**
 * Development preview only. Records live in browser memory and vanish on refresh.
 * No policy or card data is seeded: PDF extraction returns no fields, so nothing
 * that looks like a real policy, coverage limit or insurance card is ever shown.
 *
 * The memory service is handed to the page as a prop. It never replaces the
 * shared `insuranceApi` singleton, so no preview code path can reach the real
 * application (not even under StrictMode's double-mount or a stale cleanup).
 */
function createMemoryApi() {
  const db = { policies: [], expenses: [], claims: [], card: null };
  let nextId = 1;
  const files = new Map(); // document_id -> file details

  const upload = async (file) => {
    const id = nextId++;
    files.set(id, { id, filename: file.name });
    // No OCR in preview, so no fields are returned.
    return { document_id: id, fields: {} };
  };

  return {
    getPolicies: async () => db.policies.map((policy) => ({ ...policy })),
    addPolicy: async (_patientId, data) => {
      const attachments = files.has(data.document_id) ? [files.get(data.document_id)] : [];
      db.policies.push({ ...data, id: nextId++, documents: attachments });
    },
    extractPolicy: upload,
    getExpenses: async () => [],
    getClaims: async () => [],
    getMedicalCard: async () => db.card && { ...db.card },
    saveMedicalCard: async (_patientId, data) => {
      const attachments = files.has(data.document_id)
        ? [files.get(data.document_id)]
        : db.card?.documents || [];
      db.card = { ...data, documents: attachments };
    },
    uploadCardDocument: upload,
  };
}

export default function InsuranceModulePreview() {
  const [memoryApi] = useState(createMemoryApi);

  return (
    <div className="min-h-screen bg-slate-50 px-4 py-6">
      <div className="mx-auto max-w-4xl space-y-4">
        <p className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm font-semibold text-amber-800">
          Preview mode: nothing is sent to a server and no policy data is pre-filled. Records
          disappear when you refresh.
        </p>
        <InsurancePage previewPatientId="preview" api={memoryApi} />
      </div>
    </div>
  );
}

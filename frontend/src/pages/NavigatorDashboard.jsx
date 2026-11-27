import { useEffect, useState } from 'react';
import { Download, FileText } from 'lucide-react';
import { apiRequest, downloadAuthorizedFile } from '../api/client';
import { useAuth } from '../context/AuthContext';

export default function NavigatorDashboard() {
  const { user } = useAuth();
  const [patients, setPatients] = useState([]);
  const [selectedPatient, setSelectedPatient] = useState(null);
  const [documents, setDocuments] = useState([]);
  const [error, setError] = useState('');

  useEffect(() => {
    apiRequest('/patients/accessible')
      .then(setPatients)
      .catch((err) => setError(err.message));
  }, []);

  const handleSelectPatient = async (patient) => {
    setSelectedPatient(patient);
    setError('');
    try {
      const docs = await apiRequest(`/patients/${patient.patient_id}/documents`);
      setDocuments(docs);
    } catch (err) {
      setDocuments([]);
      setError(err.message);
    }
  };

  return (
    <div className="space-y-6">
      <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h1 className="text-2xl font-bold text-slate-900">Doctor / Navigator Portal</h1>
        <p className="mt-1 text-sm text-slate-600">
          Signed in as <strong>{user?.name}</strong>. Only patients who granted active consent are
          visible here.
        </p>

        {error && (
          <div className="mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </div>
        )}

        <div className="mt-5 grid gap-3 sm:grid-cols-2">
          {patients.length === 0 ? (
            <p className="text-sm text-slate-500">No patients have granted you active access yet.</p>
          ) : (
            patients.map((p) => (
              <button
                key={p.grant_id}
                type="button"
                onClick={() => handleSelectPatient(p)}
                className={`rounded-xl border p-4 text-left transition ${
                  selectedPatient?.patient_id === p.patient_id
                    ? 'border-brand-600 bg-brand-50'
                    : 'border-slate-200 hover:border-brand-400'
                }`}
              >
                <p className="font-semibold text-slate-900">{p.patient_name}</p>
                <p className="mt-1 text-xs text-slate-600">
                  DOB/Age: {p.dob_or_age || 'Not set'} · Scopes: {p.scopes.join(', ')}
                </p>
              </button>
            ))
          )}
        </div>
      </div>

      {selectedPatient && (
        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <h2 className="text-lg font-semibold text-slate-900">
            Consented Documents — {selectedPatient.patient_name}
          </h2>
          {documents.length === 0 ? (
            <p className="mt-3 text-sm text-slate-500">No documents available for this patient.</p>
          ) : (
            <div className="mt-4 divide-y divide-slate-200">
              {documents.map((doc) => (
                <div key={doc.id} className="flex items-center justify-between py-3 text-sm">
                  <div className="flex items-center gap-3">
                    <FileText className="h-5 w-5 text-brand-600" />
                    <div>
                      <p className="font-medium text-slate-900">{doc.original_filename}</p>
                      <p className="text-xs text-slate-500">
                        {doc.document_type} · Verification: {doc.verification_status}
                      </p>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() =>
                      downloadAuthorizedFile(
                        `/patients/${selectedPatient.patient_id}/documents/${doc.id}/download`,
                        doc.original_filename
                      )
                    }
                    className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
                  >
                    <Download className="h-3.5 w-3.5" />
                    Download
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

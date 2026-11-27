import { useCallback, useEffect, useState } from 'react';
import { Download, FileText } from 'lucide-react';
import { downloadAuthorizedFile } from '../api/client';
import { documentsApi } from '../api/documents';
import { getSecurityForDocuments } from '../api/documentSecurity';
import { patientsApi } from '../api/patients';
import { asArray, expectArray } from '../api/shape';
import { isDocumentCleared } from '../modules/document-intelligence/DocumentSecurityPanel';
import SectionState, { failedSection, loadingSection, readySection } from '../components/ui/SectionState';
import { useAuth } from '../context/AuthContext';

export default function NavigatorDashboard() {
  const { user } = useAuth();
  const [patients, setPatients] = useState([]);
  const [patientsState, setPatientsState] = useState(loadingSection);
  const [selectedPatient, setSelectedPatient] = useState(null);
  const [documents, setDocuments] = useState([]);
  const [documentsState, setDocumentsState] = useState(readySection);
  const [clearance, setClearance] = useState({});
  const [error, setError] = useState('');

  const loadPatients = useCallback(async () => {
    setPatientsState(loadingSection());
    try {
      setPatients(expectArray(await patientsApi.getAccessible(), 'your consented patients'));
      setPatientsState(readySection());
    } catch (err) {
      setPatientsState(failedSection(err));
    }
  }, []);

  useEffect(() => {
    loadPatients();
  }, [loadPatients]);

  const handleSelectPatient = async (patient) => {
    setSelectedPatient(patient);
    setDocuments([]);
    setClearance({});
    setError('');
    setDocumentsState(loadingSection());
    try {
      const docs = expectArray(
        await documentsApi.list(patient.patient_id),
        'this patient\u2019s documents'
      );
      setDocuments(docs);
      setDocumentsState(readySection());
      setClearance(await getSecurityForDocuments(patient.patient_id, docs));
    } catch (err) {
      setDocumentsState(failedSection(err));
    }
  };

  const handleDownload = async (doc) => {
    if (!isDocumentCleared(clearance[doc.id])) {
      setError(
        'This document has not been cleared by security screening, so it cannot be downloaded.'
      );
      return;
    }
    setError('');
    try {
      await downloadAuthorizedFile(
        `/patients/${selectedPatient.patient_id}/documents/${doc.id}/download`,
        doc.original_filename
      );
    } catch (err) {
      setError(`Could not download the document: ${err.message}`);
    }
  };

  return (
    <div className="space-y-6">
      <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h1 className="text-2xl font-bold text-slate-900">Doctor / Navigator Portal</h1>
        <p className="mt-1 text-sm text-slate-600">
          Signed in as <strong>{user?.name || 'unknown user'}</strong>. Only patients who granted
          active consent are visible here.
        </p>

        {error && (
          <div
            role="alert"
            className="mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"
          >
            {error}
          </div>
        )}

        <SectionState state={patientsState} label="your consented patients" onRetry={loadPatients} />
        {patientsState.status === 'error' && patients.length > 0 && (
          <p className="mt-2 text-xs text-slate-500">
            Showing patients loaded earlier; the latest refresh failed.
          </p>
        )}

        <div className="mt-5 grid gap-3 sm:grid-cols-2">
          {patientsState.status === 'ready' && patients.length === 0 && (
            <p className="text-sm text-slate-500">No patients have granted you active access yet.</p>
          )}
          {patients.map((p) => (
            <button
              key={p.grant_id || p.patient_id}
              type="button"
              onClick={() => handleSelectPatient(p)}
              className={`rounded-xl border p-4 text-left transition ${
                selectedPatient?.patient_id === p.patient_id
                  ? 'border-brand-600 bg-brand-50'
                  : 'border-slate-200 hover:border-brand-400'
              }`}
            >
              <p className="font-semibold text-slate-900">{p.patient_name || 'Unnamed patient'}</p>
              <p className="mt-1 text-xs text-slate-600">
                DOB/Age: {p.dob_or_age || 'Not set'} · Scopes:{' '}
                {asArray(p.scopes).join(', ') || 'none reported'}
              </p>
            </button>
          ))}
        </div>
      </div>

      {selectedPatient && (
        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <h2 className="text-lg font-semibold text-slate-900">
            Consented Documents — {selectedPatient.patient_name || 'patient'}
          </h2>
          <p className="mt-1 text-xs text-slate-500">
            Downloads are limited to files the security scanner has explicitly cleared; the backend
            must enforce the same restriction.
          </p>

          <SectionState
            state={documentsState}
            label="this patient's documents"
            onRetry={() => handleSelectPatient(selectedPatient)}
          />
          {documentsState.status === 'error' && documents.length > 0 && (
            <p className="mt-2 text-xs text-slate-500">
              Showing documents loaded earlier; the latest refresh failed.
            </p>
          )}

          {documentsState.status === 'ready' && documents.length === 0 && (
            <p className="mt-3 text-sm text-slate-500">No documents available for this patient.</p>
          )}

          {documents.length > 0 && (
            <div className="mt-4 divide-y divide-slate-200">
              {documents.map((doc) => {
                const cleared = isDocumentCleared(clearance[doc.id]);
                return (
                  <div
                    key={doc.id}
                    className="flex flex-wrap items-center justify-between gap-3 py-3 text-sm"
                  >
                    <div className="flex items-center gap-3">
                      <FileText className="h-5 w-5 text-brand-600" />
                      <div>
                        <p className="font-medium text-slate-900">
                          {doc.original_filename || 'Unnamed document'}
                        </p>
                        <p className="text-xs text-slate-500">
                          {doc.document_type || 'unclassified'} · Verification:{' '}
                          {doc.verification_status || 'not reported'}
                        </p>
                        <p
                          className={`text-xs font-medium ${cleared ? 'text-emerald-700' : 'text-amber-700'}`}
                        >
                          {cleared
                            ? 'Screening cleared'
                            : `Screening: ${clearance[doc.id]?.status || 'status unavailable'}`}
                        </p>
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => handleDownload(doc)}
                      disabled={!cleared}
                      title={
                        cleared
                          ? 'Download the original file'
                          : 'Download is disabled until security screening clears this file'
                      }
                      className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      <Download className="h-3.5 w-3.5" />
                      Download
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

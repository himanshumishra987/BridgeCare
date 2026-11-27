import { useCallback, useEffect, useState } from 'react';
import { Download, FileText, Upload } from 'lucide-react';
import { downloadAuthorizedFile } from '../api/client';
import { documentsApi } from '../api/documents';
import { getSecurityForDocuments } from '../api/documentSecurity';
import { expectArray } from '../api/shape';
import { isDocumentCleared } from '../modules/document-intelligence/DocumentSecurityPanel';
import SectionState, { failedSection, loadingSection, readySection } from '../components/ui/SectionState';
import { useAuth } from '../context/AuthContext';

const formatSize = (bytes) =>
  Number.isFinite(bytes) ? `${Math.round(bytes / 1024)} KB` : 'size not reported';

const screeningLabel = (screening) => {
  if (!screening) return 'screening status unavailable';
  if (typeof screening.status === 'string' && screening.status) return `screening: ${screening.status}`;
  return 'screening status not reported';
};

export default function DocumentsVaultPage() {
  const { user } = useAuth();
  const patientId = user?.patient_profile?.id;
  const [documents, setDocuments] = useState([]);
  const [listState, setListState] = useState(loadingSection);
  // document_id -> IDTA decision | null. Null means "unknown", never "cleared".
  const [clearance, setClearance] = useState({});
  const [file, setFile] = useState(null);
  const [documentType, setDocumentType] = useState('unclassified');
  const [documentDate, setDocumentDate] = useState('');
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState('');

  const loadDocuments = useCallback(async () => {
    if (!patientId) {
      setListState(failedSection(new Error('this account has no linked patient profile')));
      return;
    }
    setListState(loadingSection());
    try {
      // A non-array success is a failure, not "no documents uploaded yet".
      const data = expectArray(await documentsApi.list(patientId), 'your stored documents');
      setDocuments(data);
      setListState(readySection());
      setClearance(await getSecurityForDocuments(patientId, data));
    } catch (err) {
      setListState(failedSection(err));
    }
  }, [patientId]);

  useEffect(() => {
    loadDocuments();
  }, [loadDocuments]);

  const handleUpload = async (e) => {
    e.preventDefault();
    if (!file || !patientId) return;
    setError('');
    setUploading(true);
    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('document_type', documentType);
      if (documentDate) formData.append('document_date', documentDate);

      await documentsApi.upload(patientId, formData);
      setFile(null);
      setDocumentDate('');
      await loadDocuments();
    } catch (err) {
      setError(err.message);
    } finally {
      setUploading(false);
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
        `/patients/${patientId}/documents/${doc.id}/download`,
        doc.original_filename
      );
    } catch (err) {
      setError(`Could not download the document: ${err.message}`);
    }
  };

  return (
    <div className="space-y-6">
      <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h1 className="text-xl font-bold text-slate-900">Document Upload Plumbing</h1>
        <p className="mt-1 text-sm text-slate-600">
          Files are validated (PDF/PNG/JPEG), stored securely outside the web root, and queued for
          future Module 01 OCR &amp; human verification.
        </p>

        {error && (
          <div
            role="alert"
            className="mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"
          >
            {error}
          </div>
        )}

        <form onSubmit={handleUpload} className="mt-5 grid gap-4 sm:grid-cols-3">
          <div className="sm:col-span-3">
            <label htmlFor="vault-file" className="block text-sm font-medium text-slate-700">
              Select PDF or Image (max 10 MB)
            </label>
            <input
              id="vault-file"
              type="file"
              accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg"
              required
              onChange={(e) => setFile(e.target.files?.[0] || null)}
              className="mt-1 block w-full rounded-lg border border-slate-300 bg-slate-50 px-3 py-2 text-sm"
            />
          </div>

          <div>
            <label htmlFor="vault-category" className="block text-sm font-medium text-slate-700">
              Category
            </label>
            <select
              id="vault-category"
              value={documentType}
              onChange={(e) => setDocumentType(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            >
              <option value="unclassified">Unclassified</option>
              <option value="lab_report">Laboratory Report</option>
              <option value="prescription">Prescription</option>
              <option value="consultation_summary">Consultation Summary</option>
              <option value="discharge_summary">Discharge Summary</option>
            </select>
          </div>

          <div>
            <label htmlFor="vault-date" className="block text-sm font-medium text-slate-700">
              Document Date
            </label>
            <input
              id="vault-date"
              type="date"
              value={documentDate}
              onChange={(e) => setDocumentDate(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            />
          </div>

          <div className="flex items-end">
            <button
              type="submit"
              disabled={uploading || !file}
              className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-60"
            >
              <Upload className="h-4 w-4" />
              {uploading ? 'Uploading...' : 'Upload Document'}
            </button>
          </div>
        </form>
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-900">Stored Documents</h2>
        <p className="mt-1 text-xs text-slate-500">
          Download is enabled only for files the security scanner has explicitly cleared. Pending,
          scanning, quarantined, rejected, inconclusive, unreported or unavailable screening counts
          as not cleared. The backend must enforce the same rule independently.
        </p>

        <SectionState state={listState} label="your stored documents" onRetry={loadDocuments} />
        {listState.status === 'error' && documents.length > 0 && (
          <p className="mt-2 text-xs text-slate-500">
            Showing documents loaded earlier; the latest refresh failed.
          </p>
        )}

        {listState.status === 'ready' && documents.length === 0 && (
          <p className="mt-3 text-sm text-slate-500">No documents uploaded yet.</p>
        )}

        {documents.length > 0 && (
          <div className="mt-4 divide-y divide-slate-200">
            {documents.map((doc) => {
              const screening = clearance[doc.id];
              const cleared = isDocumentCleared(screening);
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
                        {doc.document_type || 'unclassified'} · {formatSize(doc.file_size_bytes)} ·
                        Processing: {doc.processing_status || 'not reported'} · Verification:{' '}
                        {doc.verification_status || 'not reported'}
                      </p>
                      <p
                        className={`text-xs font-medium ${cleared ? 'text-emerald-700' : 'text-amber-700'}`}
                      >
                        {cleared ? 'Screening cleared' : screeningLabel(screening)}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
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
                    {!cleared && (
                      <span className="text-xs text-amber-700">
                        Withheld until screening clears
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

import { useCallback, useEffect, useState } from 'react';
import { Download, FileText, Upload } from 'lucide-react';
import { apiRequest, downloadAuthorizedFile } from '../api/client';
import { useAuth } from '../context/AuthContext';

export default function DocumentsVaultPage() {
  const { user } = useAuth();
  const patientId = user?.patient_profile?.id;
  const [documents, setDocuments] = useState([]);
  const [file, setFile] = useState(null);
  const [documentType, setDocumentType] = useState('unclassified');
  const [documentDate, setDocumentDate] = useState('');
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState('');

  const loadDocuments = useCallback(async () => {
    if (!patientId) return;
    try {
      const data = await apiRequest(`/patients/${patientId}/documents`);
      setDocuments(data);
    } catch (err) {
      setError(err.message);
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

      await apiRequest(`/patients/${patientId}/documents/upload`, {
        method: 'POST',
        body: formData,
      });
      setFile(null);
      setDocumentDate('');
      await loadDocuments();
    } catch (err) {
      setError(err.message);
    } finally {
      setUploading(false);
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
          <div className="mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </div>
        )}

        <form onSubmit={handleUpload} className="mt-5 grid gap-4 sm:grid-cols-3">
          <div className="sm:col-span-3">
            <label className="block text-sm font-medium text-slate-700">
              Select PDF or Image (max 10 MB)
            </label>
            <input
              type="file"
              accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg"
              required
              onChange={(e) => setFile(e.target.files?.[0] || null)}
              className="mt-1 block w-full rounded-lg border border-slate-300 bg-slate-50 px-3 py-2 text-sm"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700">Category</label>
            <select
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
            <label className="block text-sm font-medium text-slate-700">Document Date</label>
            <input
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
        {documents.length === 0 ? (
          <p className="mt-3 text-sm text-slate-500">No documents uploaded yet.</p>
        ) : (
          <div className="mt-4 divide-y divide-slate-200">
            {documents.map((doc) => (
              <div
                key={doc.id}
                className="flex flex-wrap items-center justify-between gap-3 py-3 text-sm"
              >
                <div className="flex items-center gap-3">
                  <FileText className="h-5 w-5 text-brand-600" />
                  <div>
                    <p className="font-medium text-slate-900">{doc.original_filename}</p>
                    <p className="text-xs text-slate-500">
                      {doc.document_type} · {Math.round(doc.file_size_bytes / 1024)} KB ·
                      Processing: {doc.processing_status} · Verification: {doc.verification_status}
                    </p>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() =>
                    downloadAuthorizedFile(
                      `/patients/${patientId}/documents/${doc.id}/download`,
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
    </div>
  );
}

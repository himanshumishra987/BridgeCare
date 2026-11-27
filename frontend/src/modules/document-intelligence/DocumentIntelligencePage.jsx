import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle, FileSearch, XCircle } from 'lucide-react';
import {
  downloadAuthorizedFile,
  getAuthorizedBlob,
  isMissingResource,
  isUnsupportedEndpoint,
} from '../../api/client';
import { documentSecurityApi } from '../../api/documentSecurity';
import { documentsApi } from '../../api/documents';
import { expectArray } from '../../api/shape';
import DocumentSecurityPanel, { isDocumentCleared } from './DocumentSecurityPanel';
import ConfidencePill from '../../components/ui/ConfidencePill';
import DocumentPreview from '../../components/ui/DocumentPreview';
import EmptyState from '../../components/ui/EmptyState';
import ErrorBanner from '../../components/ui/ErrorBanner';
import LoadingSpinner from '../../components/ui/LoadingSpinner';
import SectionState, { failedSection, loadingSection, readySection } from '../../components/ui/SectionState';
import PageHeader from '../../components/ui/PageHeader';
import SectionCard from '../../components/ui/SectionCard';
import StatusBadge from '../../components/ui/StatusBadge';
import { useAuth } from '../../context/AuthContext';

export default function DocumentIntelligencePage() {
  const { user } = useAuth();
  const patientId = user?.patient_profile?.id;

  const [documents, setDocuments] = useState([]);
  const [selected, setSelected] = useState(null);
  const [extraction, setExtraction] = useState(null);
  const [previewUrl, setPreviewUrl] = useState(null);
  const [listState, setListState] = useState(loadingSection);
  const [extractionLoading, setExtractionLoading] = useState(false);
  const [error, setError] = useState('');
  const [previewError, setPreviewError] = useState('');
  const [actionMsg, setActionMsg] = useState('');
  const [verifying, setVerifying] = useState(false);

  // IDTA screening state. Anything that is not an explicit "cleared" fails closed.
  const [security, setSecurity] = useState(null);
  const [securityLoading, setSecurityLoading] = useState(false);
  const [securityError, setSecurityError] = useState('');
  const [retryingSecurity, setRetryingSecurity] = useState(false);
  const cleared = isDocumentCleared(security);

  // Upload form
  const [file, setFile] = useState(null);
  const [documentType, setDocumentType] = useState('unclassified');
  const [documentDate, setDocumentDate] = useState('');
  const [uploading, setUploading] = useState(false);

  const loadDocuments = useCallback(async () => {
    if (!patientId) {
      setListState(failedSection(new Error('this account has no linked patient profile')));
      return;
    }
    setListState(loadingSection());
    try {
      // A non-array success is a failure, not "no documents yet".
      const data = expectArray(await documentsApi.list(patientId), 'your documents');
      setDocuments(data);
      setListState(readySection());
    } catch (err) {
      // Keep the documents already on screen and mark the refresh as failed.
      setListState(failedSection(err));
    }
  }, [patientId]);

  useEffect(() => { loadDocuments(); }, [loadDocuments]);

  // Object URLs are browser memory; revoke the previous one and on unmount.
  useEffect(
    () => () => {
      if (previewUrl?.url) URL.revokeObjectURL(previewUrl.url);
    },
    [previewUrl]
  );

  const loadSecurity = useCallback(
    async (documentId) => {
      setSecurityLoading(true);
      setSecurityError('');
      try {
        const data = await documentSecurityApi.get(patientId, documentId);
        setSecurity(data);
        return data;
      } catch (err) {
        // An unavailable scanner is never treated as clearance.
        setSecurity(null);
        setSecurityError(err.message);
        return null;
      } finally {
        setSecurityLoading(false);
      }
    },
    [patientId]
  );

  const handleSelectDoc = async (doc) => {
    setSelected(doc);
    setExtraction(null);
    setPreviewUrl(null);
    setActionMsg('');
    setPreviewError('');
    setSecurity(null);
    setSecurityError('');

    const screening = await loadSecurity(doc.id);
    if (!isDocumentCleared(screening)) {
      // Never pull quarantined/inconclusive contents into the AI review surface.
      setExtraction(null);
      return;
    }

    setExtractionLoading(true);
    try {
      const ext = await documentsApi.getExtraction(patientId, doc.id);
      setExtraction(ext);
    } catch (err) {
      // 404: this document has no extraction yet, which is normal for queued files.
      // 501: the backend does not implement extraction at all.
      // Anything else is a real failure and is reported.
      setExtraction(null);
      if (isUnsupportedEndpoint(err)) {
        setError('Document extraction is not available on this server yet.');
      } else if (!isMissingResource(err)) {
        setError(`Could not load extraction: ${err.message}`);
      }
    } finally {
      setExtractionLoading(false);
    }
  };

  const handleRetryScreening = async () => {
    if (!selected) return;
    setRetryingSecurity(true);
    try {
      await documentSecurityApi.retry(patientId, selected.id);
      await loadSecurity(selected.id);
      setActionMsg('Screening re-requested. Status will update when the scanner responds.');
    } catch (err) {
      setSecurityError(err.message);
    } finally {
      setRetryingSecurity(false);
    }
  };

  const handleUpload = async (e) => {
    e.preventDefault();
    if (!file || !patientId) return;
    setError('');
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append('file', file);
      fd.append('document_type', documentType);
      if (documentDate) fd.append('document_date', documentDate);
      await documentsApi.upload(patientId, fd);
      setFile(null);
      setDocumentDate('');
      await loadDocuments();
      setActionMsg('Document uploaded successfully.');
    } catch (err) {
      setError(err.message);
    } finally {
      setUploading(false);
    }
  };

  const handleVerify = async () => {
    if (!selected || !extraction || !cleared) return;
    setVerifying(true);
    setActionMsg('');
    try {
      await documentsApi.verify(patientId, selected.id, { extraction_id: extraction.id });
      setActionMsg('Extraction verified and saved to your health record.');
      await loadDocuments();
    } catch (err) {
      setError(err.message);
    } finally {
      setVerifying(false);
    }
  };

  const handleReject = async () => {
    if (!selected) return;
    setVerifying(true);
    setActionMsg('');
    try {
      await documentsApi.reject(patientId, selected.id, 'Manually rejected by patient.');
      setActionMsg('Extraction rejected — document remains stored but no data will be used.');
      await loadDocuments();
    } catch (err) {
      setError(err.message);
    } finally {
      setVerifying(false);
    }
  };

  const handlePreview = async (doc) => {
    if (!cleared) {
      setPreviewError(
        'This document has not been cleared by security screening, so its contents cannot be opened.'
      );
      return;
    }
    setPreviewError('');
    try {
      // Same auth, timeout and 401-refresh rules as every other API call.
      const blob = await getAuthorizedBlob(`/patients/${patientId}/documents/${doc.id}/download`, {
        timeoutMs: 60000,
      });
      setPreviewUrl({
        url: URL.createObjectURL(blob),
        mimeType: doc.mime_type,
        filename: doc.original_filename,
      });
    } catch (err) {
      setPreviewError(`Could not load preview: ${err.message}`);
    }
  };

  /**
   * Downloading is a second, independent gate: the same cleared state that
   * unlocks preview also unlocks the original file. The backend must enforce
   * this itself — this is defence in depth, not authorization.
   */
  const handleDownload = async () => {
    if (!selected) return;
    if (!cleared) {
      setPreviewError(
        'This document has not been cleared by security screening, so it cannot be downloaded.'
      );
      return;
    }
    setPreviewError('');
    try {
      await downloadAuthorizedFile(
        `/patients/${patientId}/documents/${selected.id}/download`,
        selected.original_filename
      );
    } catch (err) {
      setPreviewError(`Could not download the document: ${err.message}`);
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Document Intelligence"
        subtitle="Upload medical documents, review AI-extracted data, and verify or reject results before they enter your health record."
      />

      {/* AI Safety Notice */}
      <div className="flex items-start gap-2.5 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-900">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
        <p>
          <strong>AI-extracted data is never automatically verified.</strong> You must review and
          explicitly confirm each extraction before it becomes part of your health record.
        </p>
      </div>

      {/* Upload */}
      <SectionCard>
        <h2 className="text-lg font-semibold text-slate-900">Upload Document</h2>
        <p className="mt-1 text-sm text-slate-500">PDF, PNG, or JPEG · max 10 MB</p>
        <ErrorBanner message={error} onDismiss={() => setError('')} />
        {actionMsg && (
          <div className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
            {actionMsg}
          </div>
        )}
        <form onSubmit={handleUpload} className="mt-5 grid gap-4 sm:grid-cols-3">
          <div className="sm:col-span-3">
            <label htmlFor="doc-file" className="block text-sm font-medium text-slate-700">
              Select file
            </label>
            <input
              id="doc-file"
              type="file"
              accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg"
              required
              onChange={(e) => setFile(e.target.files?.[0] || null)}
              className="mt-1 block w-full rounded-lg border border-slate-300 bg-slate-50 px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label htmlFor="doc-category" className="block text-sm font-medium text-slate-700">
              Category
            </label>
            <select
              id="doc-category"
              value={documentType}
              onChange={(e) => setDocumentType(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            >
              <option value="unclassified">Unclassified</option>
              <option value="lab_report">Lab Report</option>
              <option value="prescription">Prescription</option>
              <option value="consultation_summary">Consultation Summary</option>
              <option value="discharge_summary">Discharge Summary</option>
              <option value="radiology">Radiology / Imaging</option>
            </select>
          </div>
          <div>
            <label htmlFor="doc-date" className="block text-sm font-medium text-slate-700">
              Document Date
            </label>
            <input
              id="doc-date"
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
              {uploading ? 'Uploading…' : 'Upload & Queue for Processing'}
            </button>
          </div>
        </form>
      </SectionCard>

      {/* Document list + extraction panel */}
      <div className="grid gap-6 lg:grid-cols-5">
        {/* Left: document list */}
        <SectionCard className="lg:col-span-2">
          <h2 className="text-lg font-semibold text-slate-900">Your Documents</h2>
          <SectionState state={listState} label="your documents" onRetry={loadDocuments} />
          {listState.status === 'error' && documents.length > 0 && (
            <p className="mt-2 text-xs text-slate-500">
              Showing documents loaded earlier; the latest refresh failed.
            </p>
          )}
          {listState.status === 'ready' && documents.length === 0 && (
            <EmptyState
              icon={FileSearch}
              title="No documents yet"
              description="Upload a PDF or image to begin."
            />
          )}
          {documents.length > 0 && (
            <div className="mt-4 divide-y divide-slate-100">
              {documents.map((doc) => (
                <button
                  key={doc.id}
                  type="button"
                  onClick={() => handleSelectDoc(doc)}
                  className={`w-full text-left py-3 px-2 rounded-lg transition ${
                    selected?.id === doc.id ? 'bg-brand-50 border border-brand-200' : 'hover:bg-slate-50'
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-sm font-medium text-slate-900 truncate">{doc.original_filename}</p>
                    <StatusBadge status={doc.processing_status} />
                  </div>
                  <p className="mt-0.5 text-xs text-slate-500">
                    {doc.document_type} · {Math.round(doc.file_size_bytes / 1024)} KB
                  </p>
                  <div className="mt-1 flex gap-2">
                    <StatusBadge status={doc.verification_status} />
                    {doc.is_duplicate && (
                      <span className="rounded-full bg-orange-100 px-2 py-0.5 text-xs font-semibold text-orange-800">
                        Possible duplicate
                      </span>
                    )}
                  </div>
                </button>
              ))}
            </div>
          )}
        </SectionCard>

        {/* Right: extraction + preview */}
        <div className="space-y-4 lg:col-span-3">
          {!selected ? (
            <SectionCard>
              <EmptyState
                icon={FileSearch}
                title="Select a document"
                description="Click a document on the left to view its AI extraction and preview."
              />
            </SectionCard>
          ) : (
            <>
              {/* Document preview */}
              <SectionCard>
                <div className="flex items-center justify-between">
                  <h2 className="text-base font-semibold text-slate-900">Document Preview</h2>
                  <button
                    type="button"
                    onClick={() => handlePreview(selected)}
                    disabled={!cleared}
                    title={
                      cleared
                        ? 'Render the document in an isolated frame'
                        : 'Preview is disabled until security screening clears this file'
                    }
                    className="text-xs font-medium text-brand-700 hover:underline disabled:cursor-not-allowed disabled:text-slate-400 disabled:no-underline"
                  >
                    Load preview
                  </button>
                </div>
                {previewUrl ? (
                  <DocumentPreview {...previewUrl} className="mt-3" />
                ) : (
                  <p className="mt-2 text-xs text-slate-400">
                    {cleared
                      ? 'Click "Load preview" to render the document.'
                      : 'Preview stays locked until security screening clears this file.'}
                  </p>
                )}
                <button
                  type="button"
                  onClick={handleDownload}
                  disabled={!cleared}
                  title={
                    cleared
                      ? 'Download the original file'
                      : 'Download is disabled until security screening clears this file'
                  }
                  className="mt-3 inline-flex items-center gap-1.5 rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  Download original
                </button>
                {!cleared && (
                  <p className="mt-2 text-xs font-medium text-amber-700">
                    Download and preview are withheld: this file is not cleared by security
                    screening. Pending, scanning, quarantined, rejected, inconclusive, missing or
                    unavailable screening all count as not cleared.
                  </p>
                )}
                {previewError && (
                  <p role="alert" className="mt-2 text-xs font-medium text-red-700">
                    {previewError}
                  </p>
                )}
              </SectionCard>

              {/* Extraction result */}
              <SectionCard>
                <h2 className="text-base font-semibold text-slate-900">AI Extraction Result</h2>
                <p className="mt-1 text-xs text-slate-500">
                  Unverified AI output — review carefully before confirming.
                </p>

                <DocumentSecurityPanel
                  security={security}
                  loading={securityLoading}
                  error={securityError}
                  onRetry={handleRetryScreening}
                  retrying={retryingSecurity}
                />

                {!cleared ? (
                  <p className="mt-4 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-600">
                    Extracted contents are withheld until security screening clears this file.
                  </p>
                ) : extractionLoading ? (
                  <LoadingSpinner message="Loading extraction…" />
                ) : !extraction ? (
                  <EmptyState
                    title="No extraction available"
                    description={
                      selected.processing_status === 'uploaded' || selected.processing_status === 'queued'
                        ? 'This document is queued for processing. Check back shortly.'
                        : selected.processing_status === 'failed'
                          ? 'Processing failed for this document.'
                          : 'No AI extraction data found.'
                    }
                  />
                ) : (
                  <>
                    <div className="mt-4 flex items-center gap-3">
                      <ConfidencePill value={extraction.confidence_metadata?.overall ?? 0} />
                      <StatusBadge status={extraction.extraction_status} />
                    </div>

                    {/* Extracted fields table */}
                    <div className="mt-4 overflow-x-auto rounded-lg border border-slate-200">
                      <table className="w-full text-sm">
                        <thead className="bg-slate-50 text-xs text-slate-500">
                          <tr>
                            <th scope="col" className="px-4 py-2 text-left font-semibold">
                              Field
                            </th>
                            <th scope="col" className="px-4 py-2 text-left font-semibold">
                              Extracted value
                            </th>
                            <th scope="col" className="px-4 py-2 text-left font-semibold">
                              Confidence
                            </th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-100">
                          {Object.entries(extraction.extracted_data || {}).map(([field, val]) => (
                            <tr key={field}>
                              <td className="px-4 py-2 font-medium text-slate-700 capitalize">
                                {field.replace(/_/g, ' ')}
                              </td>
                              <td className="px-4 py-2 text-slate-900">
                                {typeof val === 'object' ? JSON.stringify(val) : String(val ?? '—')}
                              </td>
                              <td className="px-4 py-2">
                                <ConfidencePill
                                  value={extraction.confidence_metadata?.fields?.[field] ?? extraction.confidence_metadata?.overall ?? 0}
                                />
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>

                    {/* Actions */}
                    <div className="mt-4 flex flex-wrap gap-3">
                      <button
                        type="button"
                        onClick={handleVerify}
                        disabled={verifying || !cleared || extraction.extraction_status === 'verified'}
                        className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-700 disabled:opacity-60"
                      >
                        <CheckCircle className="h-4 w-4" />
                        Verify & Save to PHR
                      </button>
                      <button
                        type="button"
                        onClick={handleReject}
                        disabled={verifying}
                        className="inline-flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm font-semibold text-red-700 hover:bg-red-100 disabled:opacity-60"
                      >
                        <XCircle className="h-4 w-4" />
                        Reject
                      </button>
                    </div>
                  </>
                )}
              </SectionCard>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

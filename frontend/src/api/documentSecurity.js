/**
 * IDTA — Intelligent Document Threat Assessment service.
 *
 * CONTRACT STATUS: proposed. These two paths must be confirmed with the backend
 * (Shreyash) before this is treated as a live integration. Nothing here decides
 * whether a document is safe: the UI renders only what the backend reports and
 * fails closed when the endpoint is unavailable.
 *
 * Expected GET response shape:
 * {
 *   status: 'pending_scan' | 'scanning' | 'cleared' | 'quarantined'
 *         | 'rejected' | 'inconclusive' | 'human_review',
 *   threat_type?: string,
 *   detail?: string,
 *   scanner_available?: boolean,
 *   scanned_at?: string,
 *   can_retry?: boolean
 * }
 */
import { apiRequest } from './client';

const documentPath = (patientId, documentId) =>
  `/patients/${patientId}/documents/${documentId}/security`;

export const documentSecurityApi = {
  get: (patientId, documentId) => apiRequest(documentPath(patientId, documentId)),

  // Ask the backend to re-run screening. The backend may still refuse.
  retry: (patientId, documentId) =>
    apiRequest(`${documentPath(patientId, documentId)}/retry`, { method: 'POST' }),
};

/**
 * Resolve the screening decision for every document in a list.
 *
 * A lookup that fails is stored as `null`, and `isDocumentCleared(null)` is
 * false, so an unavailable scanner/endpoint can never unlock a file. The UI
 * labels those rows as "screening status unavailable" rather than hiding them.
 */
export async function getSecurityForDocuments(patientId, documents) {
  const entries = await Promise.all(
    documents.map(async (doc) => {
      try {
        return [doc.id, await documentSecurityApi.get(patientId, doc.id)];
      } catch {
        return [doc.id, null];
      }
    })
  );
  return Object.fromEntries(entries);
}

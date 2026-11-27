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

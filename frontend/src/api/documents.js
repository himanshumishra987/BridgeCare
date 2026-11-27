/**
 * Module 01 — Document Intelligence API service.
 * All endpoints are prefixed by the existing client base URL.
 */
import { apiRequest } from './client';

export const documentsApi = {
  /** List all documents for a patient */
  list: (patientId) => apiRequest(`/patients/${patientId}/documents`),

  /** Upload a new document */
  upload: (patientId, formData) =>
    apiRequest(`/patients/${patientId}/documents/upload`, { method: 'POST', body: formData }),

  /** Get extraction result for a document */
  getExtraction: (patientId, documentId) =>
    apiRequest(`/patients/${patientId}/documents/${documentId}/extraction`),

  /** Verify (approve) an extracted record */
  verify: (patientId, documentId, payload) =>
    apiRequest(`/patients/${patientId}/documents/${documentId}/verify`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),

  /** Reject an extracted record */
  reject: (patientId, documentId, reason) =>
    apiRequest(`/patients/${patientId}/documents/${documentId}/reject`, {
      method: 'PATCH',
      body: JSON.stringify({ reason }),
    }),

  /** Check for duplicate documents */
  checkDuplicate: (patientId, documentId) =>
    apiRequest(`/patients/${patientId}/documents/${documentId}/duplicate-check`),
};

import { apiRequest } from './client';

/**
 * Module 09 — Insurance Intelligence API service.
 *
 * Used by src/modules/insurance-info/InsurancePage.jsx.
 *
 * CONTRACT STATUS: proposed. These patient-scoped paths follow the convention
 * every other service in src/api uses, but none of them is confirmed by the
 * backend yet. Do not treat this as an agreed contract.
 */
const base = (patientId) => `/patients/${patientId}/insurance`;

// Multipart upload, form field name: "file"
const upload = (path, file) => {
  const body = new FormData();
  body.append('file', file);
  return apiRequest(path, { method: 'POST', body, timeoutMs: 120000 });
};

export const insuranceApi = {
  // GET -> array of policies
  getPolicies: (patientId) => apiRequest(`${base(patientId)}/policies`),

  // POST -> created policy
  addPolicy: (patientId, data) =>
    apiRequest(`${base(patientId)}/policies`, {
      method: 'POST',
      body: JSON.stringify({ ...data, valid_until: data.valid_until || null }),
    }),

  // PDF policy extraction. Expected response:
  // { document_id, fields: {...}, field_sources: { field: { page, clause, confidence } },
  //   overall_confidence }
  extractPolicy: (patientId, file) => upload(`${base(patientId)}/policies/extract`, file),

  // GET -> array of { id, description, date, amount_inr, claim_status }
  getExpenses: (patientId) => apiRequest(`${base(patientId)}/expenses`),

  // GET -> array of { id, description, amount_inr, status, documents[], insurer_confirmed }
  getClaims: (patientId) => apiRequest(`${base(patientId)}/claims`),

  // GET -> card object, or null when none is saved
  // { holder_name, card_number, issued_by, valid_until, document_id?, documents[] }
  getMedicalCard: (patientId) => apiRequest(`${base(patientId)}/medical-card`),

  // PUT -> saved card
  saveMedicalCard: (patientId, data) =>
    apiRequest(`${base(patientId)}/medical-card`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  // Multipart upload of a medical card image/PDF -> { document_id, fields }
  uploadCardDocument: (patientId, file) => upload(`${base(patientId)}/medical-card/documents`, file),
};

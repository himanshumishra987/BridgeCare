import { apiRequest } from './client';

// Used by src/modules/insurance-info/InsurancePage.jsx
// The URL paths are assumptions: confirm them with the backend developer.
const base = (patientId) => `/patients/${patientId}/insurance`;

export const insuranceApi = {
  getPolicies: (patientId) => apiRequest(`${base(patientId)}/policies`),

  // PDF policy extraction. CONTRACT STATUS: proposed — confirm with the backend.
  // Expected response: {
  //   document_id, fields: {...}, field_sources: { field: { page, clause, confidence } },
  //   overall_confidence
  // }
  extractPolicy: (patientId, file) => {
    const body = new FormData();
    body.append('file', file);
    return apiRequest(`${base(patientId)}/policies/extract`, { method: 'POST', body });
  },
  addPolicy: (patientId, data) =>
    apiRequest(`${base(patientId)}/policies`, {
      method: 'POST',
      body: JSON.stringify({ ...data, valid_until: data.valid_until || null }),
    }),
  getExpenses: (patientId) => apiRequest(`${base(patientId)}/expenses`),
  getClaims: (patientId) => apiRequest(`${base(patientId)}/claims`),
};

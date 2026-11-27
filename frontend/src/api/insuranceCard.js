import { apiRequest } from './client';

// Proposed API contract. Confirm these paths and field names with the backend developer.
const post = (path, data) => apiRequest(path, { method: 'POST', body: JSON.stringify(data) });

// Multipart upload, form field name: "file"
const upload = (path, file) => {
  const body = new FormData();
  body.append('file', file);
  return apiRequest(path, { method: 'POST', body });
};

export const insuranceApi = {
  // Backend runs OCR. Response: { document_id, fields: { ...extracted values } }
  uploadPolicyDocument: (file) => upload('/insurance/policies/documents', file),
  uploadCardDocument: (file) => upload('/insurance/medical-card/documents', file),

  // GET -> array, POST -> created policy
  listPolicies: () => apiRequest('/insurance/policies'),
  addPolicy: (data) => post('/insurance/policies', data),

  // GET -> card object, or null if none saved. PUT -> saved card
  getMedicalCard: () => apiRequest('/insurance/medical-card'),
  saveMedicalCard: (data) =>
    apiRequest('/insurance/medical-card', { method: 'PUT', body: JSON.stringify(data) }),
};

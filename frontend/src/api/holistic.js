/**
 * Module 06 — Holistic Health API service.
 * getAll is the original call. The other endpoints are proposed:
 * confirm them with the backend developer.
 */
import { apiRequest } from './client';

const base = (patientId) => `/patients/${patientId}`;
const post = (path, data) => apiRequest(path, { method: 'POST', body: JSON.stringify(data) });

export const holisticApi = {
  getAll: (patientId) => apiRequest(`${base(patientId)}/holistic-records`),
  addRecord: (patientId, data) => post(`${base(patientId)}/holistic-records`, data),

  getHerbs: (patientId) => apiRequest(`${base(patientId)}/herbs`),
  addHerb: (patientId, data) => post(`${base(patientId)}/herbs`, data),

  // Interactions are worked out by the backend only
  getWarnings: (patientId) => apiRequest(`${base(patientId)}/herb-drug-warnings`),
};

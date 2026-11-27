/**
 * Module 07 — Family Health API service.
 */
import { apiRequest } from './client';

export const familyApi = {
  getMembers: (patientId) => apiRequest(`/patients/${patientId}/family-members`),

  requestConsent: (patientId, payload) =>
    apiRequest(`/patients/${patientId}/family-consent-requests`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  revokeAccess: (grantId) =>
    apiRequest(`/access-grants/${grantId}/revoke`, { method: 'POST' }),

  getSharingHistory: (patientId) =>
    apiRequest(`/patients/${patientId}/audit-logs?resource_type=access_grant`),
};

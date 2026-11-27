/**
 * Module 07 — Family Health API service.
 *
 * DUPLICATE SURFACES (pending backend confirmation, nothing removed yet):
 * - `revokeAccess` calls the same POST /access-grants/{id}/revoke as
 *   `accessGrantsApi.revoke` in ./accessGrants.js.
 * - `getSharingHistory` calls /patients/{id}/audit-logs with
 *   ?resource_type=access_grant, while `accessGrantsApi.listAuditLogs` calls the
 *   same path unfiltered, so the two return different rows.
 * The recommended canonical service is `accessGrantsApi`, which owns the whole
 * grant lifecycle (list/create/revoke/audit). Consolidating needs Shreyash to
 * confirm that the query parameter is optional and that both call sites should
 * see the same result set.
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

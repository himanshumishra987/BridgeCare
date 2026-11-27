/**
 * Explicit consent / access-grant API service.
 * The backend is the only authority on whether a grant is active; the UI renders
 * what it reports and never treats expiry as enforcement.
 *
 * CANONICAL (recommended): this module owns the grant lifecycle — list, create,
 * revoke and audit. `familyApi.revokeAccess` / `familyApi.getSharingHistory` in
 * ./family.js are older duplicates of `revoke` / `listAuditLogs`; they are kept
 * unchanged until Shreyash confirms that the `resource_type` filter on the audit
 * endpoint is optional, because the filter changes the rows returned.
 */
import { apiRequest } from './client';

const base = '/access-grants';

export const accessGrantsApi = {
  list: () => apiRequest(base),

  create: (payload) =>
    apiRequest(base, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  revoke: (grantId) => apiRequest(`${base}/${grantId}/revoke`, { method: 'POST' }),

  listAuditLogs: (patientId) => apiRequest(`/patients/${patientId}/audit-logs`),
};

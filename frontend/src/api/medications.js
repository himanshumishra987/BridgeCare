/**
 * Module 05 — Medication Management API service.
 */
import { apiRequest } from './client';

export const medicationsApi = {
  getAll: (patientId) => apiRequest(`/patients/${patientId}/medications`),

  addReminder: (patientId, medicationId, payload) =>
    apiRequest(`/patients/${patientId}/medications/${medicationId}/reminders`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  dismissInteraction: (patientId, interactionId) =>
    apiRequest(`/patients/${patientId}/medication-interactions/${interactionId}/dismiss`, {
      method: 'POST',
    }),
};

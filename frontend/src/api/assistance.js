/**
 * Module 08 — Patient Assistance & Emergency API service.
 */
import { apiRequest } from './client';

export const assistanceApi = {
  getEmergencyProfile: (patientId) =>
    apiRequest(`/patients/${patientId}/emergency-profile`),

  updateEmergencyContacts: (patientId, payload) =>
    apiRequest(`/patients/${patientId}/emergency-profile`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),

  getReminders: (patientId) => apiRequest(`/patients/${patientId}/reminders`),

  addReminder: (patientId, payload) =>
    apiRequest(`/patients/${patientId}/reminders`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  deleteReminder: (patientId, reminderId) =>
    apiRequest(`/patients/${patientId}/reminders/${reminderId}`, { method: 'DELETE' }),

  askAssistant: (patientId, payload) =>
    apiRequest(`/patients/${patientId}/assistant`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  getNearbyHospitals: (lat, lng) =>
    apiRequest(`/utilities/nearby-hospitals?lat=${lat}&lng=${lng}`),
};

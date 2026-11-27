/**
 * Patient directory API service.
 * Today this is the consented-patient list both the navigator and family
 * dashboards read; the backend decides who appears in it.
 */
import { apiRequest } from './client';

export const patientsApi = {
  /** Patients who granted the signed-in account an active consent grant */
  getAccessible: () => apiRequest('/patients/accessible'),
};

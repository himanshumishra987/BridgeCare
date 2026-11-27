/**
 * Module 04 — Biomarker / Longitudinal Analytics API service.
 */
import { apiRequest } from './client';

export const biomarkersApi = {
  /** Get all biomarker series for a patient */
  getAll: (patientId) => apiRequest(`/patients/${patientId}/biomarkers`),

  /** Get a single biomarker time-series */
  getSeries: (patientId, biomarkerId) =>
    apiRequest(`/patients/${patientId}/biomarkers/${biomarkerId}`),
};

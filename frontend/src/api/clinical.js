/**
 * Module 03 — Clinical Intelligence API service.
 */
import { apiRequest } from './client';

export const clinicalApi = {
  /** Get patient-friendly and doctor-ready summaries */
  getSummary: (patientId) => apiRequest(`/patients/${patientId}/clinical-summary`),

  /**
   * Send a conversational question to the AI.
   * Expected response: { answer, sources?, uncertainty?, disclaimer? }
   * `language` is optional; the backend decides whether it is supported.
   */
  ask: (patientId, question, language) =>
    apiRequest(`/patients/${patientId}/clinical-qa`, {
      method: 'POST',
      body: JSON.stringify(language ? { question, language } : { question }),
    }),
};

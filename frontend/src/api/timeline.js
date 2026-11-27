/**
 * Module 02 — Medical Timeline / Unified PHR API service.
 */
import { apiRequest } from './client';

export const timelineApi = {
  /** Get the patient's full medical timeline (optionally filtered) */
  get: (patientId, params = {}) => {
    const qs = new URLSearchParams(params).toString();
    return apiRequest(`/patients/${patientId}/timeline${qs ? `?${qs}` : ''}`);
  },

  /** Get a single timeline episode with its linked documents */
  getEpisode: (patientId, episodeId) =>
    apiRequest(`/patients/${patientId}/timeline/${episodeId}`),
};

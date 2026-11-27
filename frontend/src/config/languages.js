/**
 * The ten languages agreed for the multilingual health assistant.
 * `value` is the BCP-47 primary subtag the backend/AI engine expects.
 * Whether a given language is actually served is decided by the backend;
 * the UI only offers the choice.
 */
export const LANGUAGES = [
  { value: 'en', label: 'English', native: 'English' },
  { value: 'hi', label: 'Hindi', native: 'हिंदी' },
  { value: 'kn', label: 'Kannada', native: 'ಕನ್ನಡ' },
  { value: 'ta', label: 'Tamil', native: 'தமிழ்' },
  { value: 'te', label: 'Telugu', native: 'తెలుగు' },
  { value: 'bn', label: 'Bengali', native: 'বাংলা' },
  { value: 'mr', label: 'Marathi', native: 'मराठी' },
  { value: 'gu', label: 'Gujarati', native: 'ગુજરાતી' },
  { value: 'ml', label: 'Malayalam', native: 'മലയാളം' },
  { value: 'or', label: 'Odia', native: 'ଓଡ଼ିଆ' },
];

export const languageLabel = (value) => {
  const match = LANGUAGES.find((l) => l.value === value);
  return match ? `${match.native} (${match.label})` : value;
};

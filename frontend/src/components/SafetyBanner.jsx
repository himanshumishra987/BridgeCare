import { AlertCircle } from 'lucide-react';

export default function SafetyBanner() {
  return (
    <div className="flex items-start gap-2.5 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-900">
      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-amber-700" />
      <p>
        <strong>BridgeCare Foundation Safety Rule:</strong> Records are organized for personal and
        authorized clinical review only. AI-extracted data is never treated as verified without
        explicit human confirmation, and BridgeCare does not provide medical diagnoses or
        prescriptions.
      </p>
    </div>
  );
}

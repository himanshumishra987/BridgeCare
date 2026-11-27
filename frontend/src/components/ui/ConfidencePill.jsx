/**
 * Displays an AI confidence score (0–1 or 0–100).
 * Visual colour: green ≥ 0.80, amber 0.50–0.79, red < 0.50.
 */
export default function ConfidencePill({ value }) {
  // normalise to 0–1
  const score = value > 1 ? value / 100 : value;
  const pct = Math.round((score ?? 0) * 100);
  const cls =
    score >= 0.8
      ? 'bg-emerald-100 text-emerald-800'
      : score >= 0.5
        ? 'bg-amber-100 text-amber-800'
        : 'bg-red-100 text-red-700';

  return (
    <span
      className={`inline-block rounded-full px-2 py-0.5 text-xs font-semibold ${cls}`}
      title="AI extraction confidence"
    >
      {pct}% confidence
    </span>
  );
}

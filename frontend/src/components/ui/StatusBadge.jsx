const VARIANTS = {
  active:          'bg-emerald-100 text-emerald-800',
  verified:        'bg-emerald-100 text-emerald-800',
  approved:        'bg-emerald-100 text-emerald-800',
  pending:         'bg-amber-100 text-amber-800',
  pending_review:  'bg-amber-100 text-amber-800',
  queued:          'bg-blue-100 text-blue-800',
  uploaded:        'bg-slate-100 text-slate-700',
  extracted:       'bg-blue-100 text-blue-800',
  revoked:         'bg-red-100 text-red-700',
  rejected:        'bg-red-100 text-red-700',
  failed:          'bg-red-100 text-red-700',
  settled:         'bg-teal-100 text-teal-800',
  inactive:        'bg-slate-100 text-slate-500',
};

export default function StatusBadge({ status, label }) {
  const cls = VARIANTS[status] || 'bg-slate-100 text-slate-700';
  return (
    <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-semibold capitalize ${cls}`}>
      {label || status?.replace(/_/g, ' ')}
    </span>
  );
}

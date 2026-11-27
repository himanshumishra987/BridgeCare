import { Calendar } from 'lucide-react';
import { asArray } from '../../api/shape';
import StatusBadge from './StatusBadge';

export default function TimelineItem({ item, onClick }) {
  // A malformed entry is reported instead of crashing the whole timeline.
  if (!item || typeof item !== 'object' || Array.isArray(item)) {
    return (
      <p role="alert" className="mb-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
        A timeline record was returned in an unexpected shape and cannot be displayed.
      </p>
    );
  }

  return (
    <div className="relative flex gap-4">
      {/* Vertical line */}
      <div className="flex flex-col items-center">
        <div className="mt-1 flex h-7 w-7 items-center justify-center rounded-full bg-brand-100 ring-2 ring-white">
          <Calendar className="h-3.5 w-3.5 text-brand-700" />
        </div>
        <div className="mt-1 flex-1 w-px bg-slate-200" />
      </div>

      {/* Content */}
      <button
        type="button"
        onClick={onClick}
        className="mb-4 flex-1 rounded-xl border border-slate-200 bg-white p-4 text-left shadow-sm hover:border-brand-400 transition"
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-xs text-slate-400">
            {item.date ? new Date(item.date).toLocaleDateString('en-IN', { year: 'numeric', month: 'short', day: 'numeric' }) : 'Date unknown'}
          </span>
          <StatusBadge status={item.verification_status || item.status} />
        </div>
        <p className="mt-1 font-semibold text-slate-900">{item.title || item.document_type || 'Medical record'}</p>
        {item.summary && <p className="mt-1 text-sm text-slate-600 line-clamp-2">{item.summary}</p>}
        {asArray(item.tags).length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1">
            {asArray(item.tags).map((tag) => (
              <span key={tag} className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">{tag}</span>
            ))}
          </div>
        )}
      </button>
    </div>
  );
}

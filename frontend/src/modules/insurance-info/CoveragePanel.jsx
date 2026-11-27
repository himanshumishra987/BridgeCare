import { Info } from 'lucide-react';
import { COVERAGE_FIELDS } from './insuranceFields';

/**
 * Displays only coverage values the user or the backend actually provided.
 * Missing values are shown as "Not recorded" — never filled with assumptions.
 */
export default function CoveragePanel({ coverage = {}, fieldSources = {} }) {
  const recorded = COVERAGE_FIELDS.filter((field) => {
    const value = coverage?.[field.name];
    return value !== null && value !== undefined && String(value).trim() !== '';
  });

  return (
    <section aria-label="Coverage details" className="rounded-xl border border-slate-200 bg-white px-3 py-3">
      <h3 className="text-sm font-semibold text-slate-900">Coverage details</h3>

      {recorded.length === 0 ? (
        <p className="mt-1 text-xs text-slate-500">
          No structured coverage recorded. Add the limits from your policy document, or confirm them
          with your insurer.
        </p>
      ) : (
        <dl className="mt-2 grid gap-2 text-sm sm:grid-cols-2">
          {recorded.map((field) => {
            const src = fieldSources?.[field.name];
            return (
              <div key={field.name}>
                <dt className="text-xs text-slate-500">{field.label}</dt>
                <dd className="break-words font-medium text-slate-900">{coverage[field.name]}</dd>
                {src && (src.page || src.clause) && (
                  <p className="text-xs text-slate-500">
                    Source: {src.page ? `page ${src.page}` : ''}
                    {src.page && src.clause ? ', ' : ''}
                    {src.clause ? `clause ${src.clause}` : ''}
                  </p>
                )}
              </div>
            );
          })}
        </dl>
      )}

      <p className="mt-2 flex items-start gap-1 text-xs text-slate-500">
        <Info className="mt-0.5 h-3 w-3 shrink-0" />
        Only recorded values are shown. BridgeCare does not estimate missing limits, and coverage is
        always governed by the insurer's policy wording.
      </p>
    </section>
  );
}

import { AlertTriangle, CheckCircle2, Clock, Loader2, ShieldAlert, ShieldQuestion } from 'lucide-react';

/**
 * Renders the backend's IDTA decision. This component never infers safety:
 * only an explicit `cleared` status unlocks document contents.
 */
const STATUS_META = {
  cleared: {
    label: 'Screening cleared',
    tone: 'border-emerald-200 bg-emerald-50 text-emerald-800',
    Icon: CheckCircle2,
    note: 'The security scanner cleared this file. Its contents may be processed.',
  },
  quarantined: {
    label: 'Quarantined',
    tone: 'border-red-200 bg-red-50 text-red-800',
    Icon: ShieldAlert,
    note: 'This file is isolated. Its contents are withheld from you and from AI processing until the security team releases it.',
  },
  rejected: {
    label: 'Rejected — malicious file',
    tone: 'border-red-200 bg-red-50 text-red-800',
    Icon: ShieldAlert,
    note: 'The scanner confirmed a threat in this file. It stays rejected and cannot be reopened from here.',
  },
  inconclusive: {
    label: 'Inconclusive — human review needed',
    tone: 'border-amber-200 bg-amber-50 text-amber-900',
    Icon: ShieldQuestion,
    note: 'The scanner could not decide. This file is not safe and is not treated as cleared.',
  },
  human_review: {
    label: 'Awaiting human review',
    tone: 'border-amber-200 bg-amber-50 text-amber-900',
    Icon: ShieldQuestion,
    note: 'A security reviewer must decide before this file can be used.',
  },
  scanning: {
    label: 'Screening in progress',
    tone: 'border-blue-200 bg-blue-50 text-blue-800',
    Icon: Loader2,
    note: 'The file is still being screened. Please wait.',
  },
  pending_scan: {
    label: 'Queued for screening',
    tone: 'border-blue-200 bg-blue-50 text-blue-800',
    Icon: Clock,
    note: 'The file has not been screened yet. It cannot be opened or processed until screening finishes.',
  },
};

const UNKNOWN_META = {
  label: 'Security status unavailable',
  tone: 'border-slate-300 bg-slate-50 text-slate-700',
  Icon: AlertTriangle,
  note: 'The security result could not be loaded. This file is treated as not cleared until the backend confirms its status.',
};

export function isDocumentCleared(security) {
  return security?.status === 'cleared';
}

export default function DocumentSecurityPanel({ security, loading, error, onRetry, retrying }) {
  if (loading) {
    return (
      <div className="mt-3 flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
        <Loader2 className="h-3.5 w-3.5 animate-spin" /> Checking security screening…
      </div>
    );
  }

  const meta = STATUS_META[security?.status] || UNKNOWN_META;
  const { Icon } = meta;

  return (
    <div className={`mt-3 rounded-lg border px-3 py-2 text-xs ${meta.tone}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="flex items-center gap-1.5 font-semibold">
          <Icon className={`h-3.5 w-3.5 ${security?.status === 'scanning' ? 'animate-spin' : ''}`} />
          {meta.label}
        </p>
        {onRetry && security?.can_retry && security.status !== 'rejected' && (
          <button
            type="button"
            onClick={onRetry}
            disabled={retrying}
            className="rounded border border-current px-2 py-0.5 text-xs font-semibold disabled:opacity-60"
          >
            {retrying ? 'Requesting…' : 'Retry screening'}
          </button>
        )}
      </div>
      <p className="mt-1">{meta.note}</p>
      {error && <p role="alert" className="mt-1 font-medium">Could not load security status: {error}</p>}
      {security?.scanner_available === false && (
        <p className="mt-1 font-medium">
          The scanner is currently unavailable, so no file is being cleared automatically.
        </p>
      )}
      {security?.threat_type && <p className="mt-1">Reported finding: {security.threat_type}</p>}
      {security?.detail && <p className="mt-1">{security.detail}</p>}
      {security?.scanned_at && (
        <p className="mt-1 opacity-80">
          Last screened {new Date(security.scanned_at).toLocaleString('en-IN')}
        </p>
      )}
    </div>
  );
}

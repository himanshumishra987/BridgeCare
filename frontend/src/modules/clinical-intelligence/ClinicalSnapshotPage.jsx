import { useCallback, useEffect, useState } from 'react';
import { AlertCircle, Bot, FileText } from 'lucide-react';
import { clinicalApi } from '../../api/clinical';
import { LANGUAGES } from '../../config/languages';
import ChatWidget from '../../components/ui/ChatWidget';
import EmptyState from '../../components/ui/EmptyState';
import ErrorBanner from '../../components/ui/ErrorBanner';
import LoadingSpinner from '../../components/ui/LoadingSpinner';
import PageHeader from '../../components/ui/PageHeader';
import SectionCard from '../../components/ui/SectionCard';
import { useAuth } from '../../context/AuthContext';

export default function ClinicalSnapshotPage() {
  const { user } = useAuth();
  const patientId = user?.patient_profile?.id;

  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [view, setView] = useState('patient'); // 'patient' | 'doctor'
  const [lang, setLang] = useState(user?.preferred_language || 'en');

  const loadSummary = useCallback(async () => {
    if (!patientId) return;
    setLoading(true);
    setError('');
    try {
      const data = await clinicalApi.getSummary(patientId);
      setSummary(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [patientId]);

  useEffect(() => { loadSummary(); }, [loadSummary]);

  const handleAsk = async (question) => {
    const data = await clinicalApi.ask(patientId, question, lang);
    return {
      answer: data?.answer || 'No answer returned.',
      sources: data?.sources,
      uncertainty: data?.uncertainty,
      disclaimer: data?.disclaimer,
    };
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Clinical Snapshot"
        subtitle="AI-generated medical summaries grounded in your verified records. Always review with your doctor."
      />

      <div className="flex items-start gap-2.5 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-900">
        <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
        <p>
          <strong>Not a diagnosis.</strong> These summaries are generated from your verified health
          records for reference only. BridgeCare does not provide medical advice or diagnoses.
        </p>
      </div>

      <ErrorBanner message={error} onDismiss={() => setError('')} />

      {loading ? (
        <LoadingSpinner message="Generating your clinical snapshot…" />
      ) : !summary ? (
        <SectionCard>
          <EmptyState
            icon={Bot}
            title="No summary available"
            description="Verify at least one document to generate a clinical snapshot."
          />
        </SectionCard>
      ) : (
        <>
          {/* Toggle */}
          <div className="inline-flex rounded-lg border border-slate-200 bg-white p-1">
            <button
              type="button"
              onClick={() => setView('patient')}
              className={`rounded-md px-4 py-1.5 text-sm font-medium transition ${
                view === 'patient' ? 'bg-brand-600 text-white shadow-sm' : 'text-slate-600 hover:bg-slate-100'
              }`}
            >
              Patient-friendly
            </button>
            <button
              type="button"
              onClick={() => setView('doctor')}
              className={`rounded-md px-4 py-1.5 text-sm font-medium transition ${
                view === 'doctor' ? 'bg-brand-600 text-white shadow-sm' : 'text-slate-600 hover:bg-slate-100'
              }`}
            >
              Doctor-ready
            </button>
          </div>

          <SectionCard>
            <h2 className="text-base font-semibold text-slate-900">
              {view === 'patient' ? 'Your Health Overview' : 'Clinical Summary (30-Second Snapshot)'}
            </h2>
            <div className="mt-3 prose prose-sm max-w-none text-slate-700">
              <p className="whitespace-pre-wrap">
                {view === 'patient' ? summary.patient_summary : summary.doctor_summary}
              </p>
            </div>

            {/* Missing / conflict indicators */}
            {summary.missing_info?.length > 0 && (
              <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3">
                <p className="text-xs font-semibold text-amber-800">Missing information detected</p>
                <ul className="mt-1 list-disc pl-4 text-xs text-amber-700 space-y-0.5">
                  {summary.missing_info.map((item, i) => <li key={i}>{item}</li>)}
                </ul>
              </div>
            )}
            {summary.conflicts?.length > 0 && (
              <div className="mt-3 rounded-lg border border-red-200 bg-red-50 p-3">
                <p className="text-xs font-semibold text-red-800">Conflicting information detected</p>
                <ul className="mt-1 list-disc pl-4 text-xs text-red-700 space-y-0.5">
                  {summary.conflicts.map((item, i) => <li key={i}>{item}</li>)}
                </ul>
              </div>
            )}

            {/* Source references */}
            {summary.source_documents?.length > 0 && (
              <div className="mt-4">
                <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide">Based on</p>
                <div className="mt-2 flex flex-wrap gap-2">
                  {summary.source_documents.map((doc) => (
                    <span key={doc.id} className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs text-slate-700">
                      <FileText className="h-3 w-3 text-brand-600" />
                      {doc.original_filename}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </SectionCard>

          {/* Conversational Q&A */}
          <SectionCard>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-base font-semibold text-slate-900">Ask About Your Records</h2>
              <label className="flex items-center gap-2 text-xs text-slate-600">
                Answer language
                <select
                  value={lang}
                  onChange={(e) => setLang(e.target.value)}
                  className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm"
                >
                  {LANGUAGES.map((l) => (
                    <option key={l.value} value={l.value}>{`${l.native} (${l.label})`}</option>
                  ))}
                </select>
              </label>
            </div>
            <ChatWidget
              onSend={handleAsk}
              placeholder="e.g. What is my latest HbA1c level?"
              systemNote="Answers are based on your verified health records only. Sources are listed with each answer. Not medical advice."
            />
            <p className="mt-2 text-xs text-slate-500">
              Language support is decided by the AI engine. If a language is unavailable, the reply
              may come back in another language — the answer is not retranslated in the browser.
            </p>
          </SectionCard>
        </>
      )}
    </div>
  );
}

import { useCallback, useEffect, useState } from 'react';
import { History, Search } from 'lucide-react';
import { timelineApi } from '../../api/timeline';
import EmptyState from '../../components/ui/EmptyState';
import ErrorBanner from '../../components/ui/ErrorBanner';
import LoadingSpinner from '../../components/ui/LoadingSpinner';
import PageHeader from '../../components/ui/PageHeader';
import SectionCard from '../../components/ui/SectionCard';
import StatusBadge from '../../components/ui/StatusBadge';
import TimelineItem from '../../components/ui/TimelineItem';
import { useAuth } from '../../context/AuthContext';

const CATEGORIES = [
  { value: '', label: 'All categories' },
  { value: 'lab_report', label: 'Lab Report' },
  { value: 'prescription', label: 'Prescription' },
  { value: 'consultation_summary', label: 'Consultation' },
  { value: 'discharge_summary', label: 'Discharge' },
  { value: 'radiology', label: 'Radiology' },
];

export default function MedicalTimelinePage() {
  const { user } = useAuth();
  const patientId = user?.patient_profile?.id;

  const [items, setItems] = useState([]);
  const [selected, setSelected] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState('');
  const [verifiedOnly, setVerifiedOnly] = useState(false);

  const loadTimeline = useCallback(async () => {
    if (!patientId) return;
    setLoading(true);
    setError('');
    try {
      const params = {};
      if (search) params.search = search;
      if (category) params.category = category;
      if (verifiedOnly) params.verified_only = 'true';
      const data = await timelineApi.get(patientId, params);
      setItems(Array.isArray(data) ? data : []);
    } catch (err) {
      setError(err.message);
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [patientId, search, category, verifiedOnly]);

  useEffect(() => { loadTimeline(); }, [loadTimeline]);

  const handleSelectItem = async (item) => {
    setSelected(item);
    try {
      const episode = await timelineApi.getEpisode(patientId, item.id);
      setSelected(episode);
    } catch {
      // keep the basic item data
    }
  };

  const displayItems = items;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Medical Timeline"
        subtitle="Your complete personal health record in chronological order."
      />

      {/* Filters */}
      <SectionCard>
        <div className="flex flex-wrap gap-3">
          <div className="relative flex-1 min-w-48">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              type="search"
              placeholder="Search timeline…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full rounded-lg border border-slate-300 py-2 pl-9 pr-3 text-sm focus:border-brand-500 focus:outline-none"
            />
          </div>
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
          >
            {CATEGORIES.map((c) => (
              <option key={c.value} value={c.value}>{c.label}</option>
            ))}
          </select>
          <label className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-700 cursor-pointer">
            <input
              type="checkbox"
              checked={verifiedOnly}
              onChange={(e) => setVerifiedOnly(e.target.checked)}
            />
            Verified only
          </label>
        </div>
      </SectionCard>

      <ErrorBanner message={error} onDismiss={() => setError('')} />

      <div className="grid gap-6 lg:grid-cols-5">
        {/* Timeline list */}
        <div className="lg:col-span-3">
          {loading ? (
            <LoadingSpinner message="Loading your health timeline…" />
          ) : displayItems.length === 0 ? (
            <SectionCard>
              <EmptyState
                icon={History}
                title="No records found"
                description="Upload and verify medical documents to build your timeline."
              />
            </SectionCard>
          ) : (
            <div className="pl-2 space-y-0">
              {displayItems.map((item) => (
                <TimelineItem
                  key={item.id}
                  item={item}
                  onClick={() => handleSelectItem(item)}
                />
              ))}
            </div>
          )}
        </div>

        {/* Episode detail */}
        <SectionCard className="lg:col-span-2 h-fit">
          {!selected ? (
            <EmptyState
              icon={History}
              title="Select a record"
              description="Click any timeline entry to see details and linked documents."
            />
          ) : (
            <div className="space-y-4">
              <div>
                <h2 className="text-lg font-semibold text-slate-900">
                  {selected.title || selected.document_type || 'Medical Record'}
                </h2>
                <p className="mt-1 text-xs text-slate-500">
                  {selected.date
                    ? new Date(selected.date).toLocaleDateString('en-IN', { year: 'numeric', month: 'long', day: 'numeric' })
                    : 'Date unknown'}
                </p>
                <div className="mt-2 flex gap-2 flex-wrap">
                  <StatusBadge status={selected.verification_status || selected.status} />
                  {selected.is_ai_generated && (
                    <span className="rounded-full bg-blue-100 px-2.5 py-0.5 text-xs font-semibold text-blue-800">
                      AI-extracted (unverified)
                    </span>
                  )}
                </div>
              </div>

              {selected.summary && (
                <div>
                  <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide">Summary</p>
                  <p className="mt-1 text-sm text-slate-700">{selected.summary}</p>
                </div>
              )}

              {selected.documents?.length > 0 && (
                <div>
                  <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide">Source Documents</p>
                  <ul className="mt-2 divide-y divide-slate-100">
                    {selected.documents.map((doc) => (
                      <li key={doc.id} className="py-2 text-sm text-slate-700">
                        {doc.original_filename}
                        <StatusBadge status={doc.verification_status} />
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </SectionCard>
      </div>
    </div>
  );
}

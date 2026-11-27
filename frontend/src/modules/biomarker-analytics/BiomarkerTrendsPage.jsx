import { useCallback, useEffect, useState } from 'react';
import { Activity, AlertCircle, Info } from 'lucide-react';
import {
  CartesianGrid,
  Label,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { biomarkersApi } from '../../api/biomarkers';
import { asArray, expectArray } from '../../api/shape';
import EmptyState from '../../components/ui/EmptyState';
import PageHeader from '../../components/ui/PageHeader';
import SectionCard from '../../components/ui/SectionCard';
import SectionState, { failedSection, loadingSection, readySection } from '../../components/ui/SectionState';
import { useAuth } from '../../context/AuthContext';

function BiomarkerChart({ series }) {
  // A malformed series is reported, never dropped or charted as empty.
  if (!series || typeof series !== 'object' || Array.isArray(series)) {
    return (
      <SectionCard>
        <p role="alert" className="text-sm text-red-700">
          A biomarker record was returned in an unexpected shape and cannot be charted.
        </p>
      </SectionCard>
    );
  }

  const measurements = asArray(series.measurements);
  const hasData = measurements.length > 0;
  const refLow = series.reference_range?.low;
  const refHigh = series.reference_range?.high;

  return (
    <SectionCard>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="font-semibold text-slate-900">{series.name}</h3>
          <p className="text-xs text-slate-500">
            Unit: {series.unit || '—'}
            {refLow != null && refHigh != null && (
              <> · Reference range: {refLow}–{refHigh} {series.unit}</>
            )}
          </p>
        </div>
        {series.has_incompatible_units && (
          <span className="inline-flex items-center gap-1 rounded-full bg-orange-100 px-2.5 py-0.5 text-xs font-semibold text-orange-800">
            <AlertCircle className="h-3 w-3" /> Mixed units — values may not be comparable
          </span>
        )}
      </div>

      {/* Pattern alerts */}
      {asArray(series.alerts).map((alert, i) => (
        <div key={i} className="mt-3 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-600" />
          <span>{alert?.message || 'Pattern alert'} {alert?.explanation && `— ${alert.explanation}`}</span>
        </div>
      ))}

      {!hasData ? (
        <EmptyState
          title="No measurements yet"
          description="Upload and verify lab reports to populate this chart."
          className="py-8"
        />
      ) : (
        <div className="mt-4 h-56">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={measurements} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis
                dataKey="date"
                tick={{ fontSize: 11 }}
                tickFormatter={(v) => new Date(v).toLocaleDateString('en-IN', { month: 'short', year: '2-digit' })}
              />
              <YAxis tick={{ fontSize: 11 }} unit={series.unit ? ` ${series.unit}` : ''} />
              <Tooltip
                labelFormatter={(v) => new Date(v).toLocaleDateString('en-IN', { year: 'numeric', month: 'long', day: 'numeric' })}
              />
              {refLow != null && (
                <ReferenceLine y={refLow} stroke="#f59e0b" strokeDasharray="4 2">
                  <Label value="Low ref" position="insideBottomRight" fontSize={10} />
                </ReferenceLine>
              )}
              {refHigh != null && (
                <ReferenceLine y={refHigh} stroke="#f59e0b" strokeDasharray="4 2">
                  <Label value="High ref" position="insideTopRight" fontSize={10} />
                </ReferenceLine>
              )}
              <Line
                type="monotone"
                dataKey="value"
                stroke="#0f766e"
                strokeWidth={2}
                dot={(props) => {
                  const { cx, cy, payload } = props;
                  const flagged = payload.is_flagged;
                  return (
                    <circle
                      key={`dot-${cx}-${cy}`}
                      cx={cx}
                      cy={cy}
                      r={flagged ? 6 : 4}
                      fill={flagged ? '#ef4444' : '#0f766e'}
                      stroke="#fff"
                      strokeWidth={1.5}
                    />
                  );
                }}
                connectNulls={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
      {series.has_missing_values && (
        <p className="mt-2 flex items-center gap-1 text-xs text-slate-500">
          <Info className="h-3.5 w-3.5" /> Some time periods have missing data — gaps indicate no recorded measurement.
        </p>
      )}
    </SectionCard>
  );
}

export default function BiomarkerTrendsPage() {
  const { user } = useAuth();
  const patientId = user?.patient_profile?.id;

  const [biomarkers, setBiomarkers] = useState([]);
  const [listState, setListState] = useState(loadingSection);

  const load = useCallback(async () => {
    if (!patientId) {
      setListState(failedSection(new Error('this account has no linked patient profile')));
      return;
    }
    setListState(loadingSection());
    try {
      // A non-array success is a failure, not "no biomarker data yet".
      const data = expectArray(await biomarkersApi.getAll(patientId), 'your biomarker trends');
      setBiomarkers(data);
      setListState(readySection());
    } catch (err) {
      // Charts already on screen stay; the failure is reported instead.
      setListState(failedSection(err));
    }
  }, [patientId]);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Biomarker Trends"
        subtitle="Longitudinal charts of your lab values with reference ranges and anomaly highlights."
      />
      <SectionState state={listState} label="your biomarker trends" onRetry={load} />
      {listState.status === 'error' && biomarkers.length > 0 && (
        <p className="text-xs text-slate-500">
          Showing charts loaded earlier; the latest request failed.
        </p>
      )}
      {listState.status === 'ready' && biomarkers.length === 0 && (
        <SectionCard>
          <EmptyState
            icon={Activity}
            title="No biomarker data yet"
            description="Upload and verify lab reports to see trend charts here."
          />
        </SectionCard>
      )}
      {biomarkers.length > 0 && (
        <div className="space-y-6">
          {biomarkers.map((series, index) => (
            <BiomarkerChart
              key={series?.id || series?.name || `series-${index}`}
              series={series}
            />
          ))}
        </div>
      )}
    </div>
  );
}

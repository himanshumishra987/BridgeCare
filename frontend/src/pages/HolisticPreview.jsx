import { useEffect, useState } from 'react';
import { holisticApi } from '../api/holistic';

// Finds the module page whatever its folder is called
const modules = import.meta.glob('../modules/*/HolisticHealthPage.jsx', { eager: true });
const HolisticHealthPage = Object.values(modules)[0]?.default;

// Obviously fictional: shows the warning layout only
const SAMPLE_WARNING = {
  id: 'sample',
  herb: 'SAMPLE HERB',
  medicine: 'SAMPLE MEDICINE',
  explanation: 'This is placeholder text to show the layout. It is not a real interaction.',
  source: 'None (sample)',
};

// Development preview only: records stay in browser memory and vanish on refresh.
function createMemoryApi(showSample) {
  const db = { records: [], herbs: [] };
  let nextId = 1;
  const list = (key) => async () => [...db[key]];
  const add = (key) => async (_patientId, data) => {
    db[key].push({ ...data, id: nextId++ });
  };
  return {
    getAll: list('records'),
    addRecord: add('records'),
    getHerbs: list('herbs'),
    addHerb: add('herbs'),
    getWarnings: async () => {
      if (showSample.current) return [SAMPLE_WARNING];
      throw new Error('Not Found'); // no interaction check in preview
    },
  };
}

export default function HolisticPreview() {
  const [ready, setReady] = useState(false);
  const [showSample] = useState({ current: false });
  const [version, setVersion] = useState(0);

  useEffect(() => {
    const original = { ...holisticApi };
    Object.assign(holisticApi, createMemoryApi(showSample));
    setReady(true);
    // Put the real API back when leaving the preview
    return () => Object.assign(holisticApi, original);
  }, [showSample]);

  if (!HolisticHealthPage) return <p className="p-6">HolisticHealthPage.jsx was not found in src/modules.</p>;
  if (!ready) return null;

  return (
    <div className="min-h-screen bg-slate-50 px-4 py-6">
      <div className="mx-auto max-w-4xl space-y-4">
        <div className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm font-semibold text-amber-800">
          Preview mode: nothing is sent to a server. Records disappear when you refresh.{' '}
          <button
            type="button"
            className="underline"
            onClick={() => {
              showSample.current = !showSample.current;
              setVersion(version + 1);
            }}
          >
            {showSample.current ? 'Hide sample warning' : 'Show sample warning'}
          </button>
        </div>
        <HolisticHealthPage key={version} previewPatientId="preview" />
      </div>
    </div>
  );
}

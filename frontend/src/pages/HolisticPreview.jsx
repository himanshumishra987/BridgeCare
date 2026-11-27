import { useState } from 'react';

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
      // Interaction checking is not part of preview mode. 501 is the contract's
      // "capability not implemented" signal, so the UI says so instead of
      // claiming there are no interactions.
      throw Object.assign(new Error('Interaction warnings are not available in preview mode.'), {
        status: 501,
      });
    },
  };
}

export default function HolisticPreview() {
  const [showSample, setShowSample] = useState(false);
  const [sampleToggle] = useState(() => ({ current: false }));
  const [memoryApi] = useState(() => createMemoryApi(sampleToggle));
  const [version, setVersion] = useState(0);

  if (!HolisticHealthPage) return <p className="p-6">HolisticHealthPage.jsx was not found in src/modules.</p>;

  return (
    <div className="min-h-screen bg-slate-50 px-4 py-6">
      <div className="mx-auto max-w-4xl space-y-4">
        <div className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm font-semibold text-amber-800">
          Preview mode: nothing is sent to a server. Records disappear when you refresh.{' '}
          <button
            type="button"
            className="underline"
            onClick={() => {
              const next = !showSample;
              sampleToggle.current = next;
              setShowSample(next);
              setVersion((v) => v + 1);
            }}
          >
            {showSample ? 'Hide sample warning' : 'Show sample warning'}
          </button>
        </div>
        {/* The memory service is passed as a prop; the shared holisticApi is never touched. */}
        <HolisticHealthPage key={version} previewPatientId="preview" api={memoryApi} />
      </div>
    </div>
  );
}

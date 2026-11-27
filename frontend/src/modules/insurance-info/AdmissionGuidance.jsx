import { ClipboardList, HelpCircle, Hospital, ReceiptText, ShieldAlert } from 'lucide-react';

/**
 * Guidance only. Deliberately contains no timelines, no coverage amounts and
 * no claim-submission action: approval is always the insurer's decision.
 */
const CHECKLIST = [
  'Your insurance card or policy number, and a government photo ID.',
  'The hospital’s insurance desk contact and your policy’s network status.',
  'Doctor’s referral or admission advice, with the proposed procedure.',
  'Any pre-authorisation form the hospital asks you to sign.',
  'List of current medicines, allergies and past treatments.',
];

const CASHLESS_STEPS = [
  'Show your policy details at the hospital insurance desk before planned treatment.',
  'Ask the hospital to raise a pre-authorisation request with your insurer or TPA.',
  'Answer the insurer’s questions about the illness and treatment honestly.',
  'Keep every acknowledgement, query and approval document the hospital gives you.',
];

const DESK_QUESTIONS = [
  'Is this hospital in my policy’s network, and is this treatment covered?',
  'What exactly is excluded from my policy for this treatment?',
  'Are room, ICU, doctor and medicine charges inside my limits?',
  'Is a waiting period or pre-existing condition clause relevant here?',
  'Is pre-authorisation required, and who submits it?',
  'What will I have to pay myself, including copayment or deductible?',
];

const REIMBURSEMENT = [
  'Check with the insurer whether reimbursement applies to this treatment.',
  'Collect itemised bills, payment receipts and discharge documents.',
  'Collect investigation reports, prescriptions and the discharge summary.',
  'Submit the claim in the form and channel the insurer specifies.',
  'Keep copies of everything you submit.',
];

function List({ items }) {
  return (
    <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-700">
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}

export default function AdmissionGuidance() {
  return (
    <section
      aria-label="Hospital admission and claim guidance"
      className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
    >
      <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-900">
        <Hospital className="h-5 w-5 text-brand-600" /> Hospital Admission &amp; Claim Preparation
      </h2>
      <p className="mt-1 text-sm text-slate-600">
        General preparation guidance. It is not a claim, it does not guarantee approval, and your
        policy wording and the insurer always decide what is payable.
      </p>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
          <h3 className="flex items-center gap-1.5 text-sm font-semibold text-slate-900">
            <ClipboardList className="h-4 w-4 text-brand-600" /> Documents to carry
          </h3>
          <List items={CHECKLIST} />
        </div>

        <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
          <h3 className="flex items-center gap-1.5 text-sm font-semibold text-slate-900">
            <ShieldAlert className="h-4 w-4 text-brand-600" /> Cashless pre-authorisation
          </h3>
          <List items={CASHLESS_STEPS} />
          <p className="mt-2 text-xs text-slate-500">
            The hospital and insurer set the process and timing. BridgeCare does not submit
            pre-authorisation requests.
          </p>
        </div>

        <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
          <h3 className="flex items-center gap-1.5 text-sm font-semibold text-slate-900">
            <HelpCircle className="h-4 w-4 text-brand-600" /> Questions for the insurance desk
          </h3>
          <List items={DESK_QUESTIONS} />
        </div>

        <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
          <h3 className="flex items-center gap-1.5 text-sm font-semibold text-slate-900">
            <ReceiptText className="h-4 w-4 text-brand-600" /> Reimbursement preparation
          </h3>
          <List items={REIMBURSEMENT} />
        </div>
      </div>

      <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
        BridgeCare stores the policy details you enter. It cannot file claims or approve them, and it
        does not confirm that a treatment is covered.
      </p>
    </section>
  );
}

# BridgeCare

AI-assisted Personal Health Record organizer that turns scattered lab reports, prescriptions, and clinical notes into structured timelines, biomarker trends, and doctor-ready briefs.

## Repository layout

| Path | Purpose |
| --- | --- |
| `frontend/` | React + Vite single-page app (the only application in this repository today) |
| — | Backend and AI Engine are maintained in separate repositories |

The frontend is a presentation and interaction layer only. It does not enforce
authorization, compute clinical conclusions, or decide insurance eligibility; the
backend and AI Engine remain authoritative for all of those.

## Running the frontend

```bash
cd frontend
npm install
npm run dev        # http://127.0.0.1:5173
```

`frontend/.env` (copy from `frontend/.env.example`) configures `VITE_API_BASE_URL`.
Never put secrets in a `VITE_*` variable: Vite inlines those values into the
production bundle.

```bash
npm run build      # production bundle in frontend/dist
npm run lint       # ESLint 9 flat config (React Hooks + jsx-a11y)
npm run test       # Vitest + Testing Library + MSW, single run
npm run test:watch # same suite in watch mode
```

## Production / integration build

`VITE_API_BASE_URL` is compiled into the bundle, so each environment needs its own
build. There is no production default.

1. Copy `frontend/.env.production.example` to `frontend/.env.production`, or set
   the same variable in the CI/integration build environment.
2. Set `VITE_API_BASE_URL` to the deployed API origin, e.g.
   `https://api.example.com/api/v1` (include the version prefix the backend uses).
3. Run `npm run build` and serve `frontend/dist`.

Guard rails, so a production bundle cannot silently talk to a developer machine:

- `vite.config.js` fails the build when `VITE_API_BASE_URL` is a loopback host
  (`localhost`, `127.0.0.1`, `[::1]`).
- `src/api/client.js` throws a configuration error at startup if a production
  build has no `VITE_API_BASE_URL`, instead of falling back to localhost. The
  localhost fallback now applies to `npm run dev` only.
- `VITE_*` values are public: never put a secret in one.

## Module system

The nine modules live in `frontend/src/modules/<module-id>/`. A module is a page
component plus, optionally, its own components and helpers.

`frontend/src/modules/registry.js` is the single source of truth for modules:

- `id`, `number`, `title`, `category`, `description` — used by the sidebar and
  the developer preview page.
- `path` — the React Router path (`/modules/...`).
- `icon` — a `lucide-react` icon component.
- `roles` — which roles see the module in navigation and may open its route.
- `requiredScope` — documentation only; see the caveat below.
- `enabled` — set `false` to hide a module without deleting it.
- `component` — the page, loaded with `React.lazy`.

Navigation links and routes are generated from the registry, so a module with
`enabled: true` and a `component` is automatically reachable for its roles.
Every module page renders inside `AppLayout`'s `<Suspense>` boundary, which is
why a module can be (and should be) lazy-loaded.

### Adding a module

1. Create `frontend/src/modules/<your-module>/YourModulePage.jsx`.
2. Add its data access to an API service module under `frontend/src/api/` (see
   below). Do not call `fetch` from the page.
3. Add an entry to `MODULE_REGISTRY` with a unique `id`, a unique `path`, the
   allowed `roles`, `enabled: true` and `component: lazy(() => import(...))`.
4. Use the existing shared UI pieces (`SectionCard`, `EmptyState`,
   `LoadingSpinner`, `ErrorBanner`, `StatusBadge`) instead of new primitives.
5. Show a real loading state, a real error state and an empty state. Never render
   a failed request as an empty record.

### What `requiredScope` does and does not do

`requiredScope` is **inert metadata**. Nothing in the frontend reads it to grant
or deny access: route guards filter on `enabled` and `roles` only, and rendering
a page is never an authorization decision. The value documents the scope the
backend is expected to require for the module's endpoints.

Backend authorization is authoritative. A patient owns their records; a
navigator or family member sees only what an explicit, unexpired access grant
allows, and the backend enforces that on every request. Hiding a route or link
is a usability measure, not a security control.

## API service modules

All HTTP access goes through `frontend/src/api/client.js`:

- `apiRequest(path, options)` — JSON requests, bearer token, 30 s default
  timeout, automatic single-flight refresh on 401 with one retry, `null` for
  `204`, and errors carrying `err.status` and `err.payload`.
- `getAuthorizedBlob(path, options)` / `downloadAuthorizedFile(...)` — protected
  file download with the same auth and timeout rules. Object URLs created from
  the returned blob must be revoked by the caller.
- `isUnsupportedEndpoint(err)` — true only for `501 Not Implemented`: the
  backend explicitly says the capability does not exist. This is the only signal
  rendered as "not available yet".
- `isMissingResource(err)` — true for `404 Not Found`: the resource is absent.
  Each call site decides what that means for its endpoint. A 404 on a list
  endpoint is shown as a failure (it could be an unregistered route or no
  records), and a 404 on a single-resource GET (`medical-card`, a document's
  extraction) is shown as "nothing saved yet". Neither is ever reported as
  "unavailable", and a success with an empty list is the only empty state.
- `SESSION_EXPIRED_EVENT` — dispatched once when a refresh fails after the
  stored tokens are cleared; `AuthContext` listens and signs the user out.

Each domain gets one service module exporting a named object:

```js
// frontend/src/api/example.js
import { apiRequest } from './client';

export const exampleApi = {
  list: (patientId) => apiRequest(`/patients/${patientId}/examples`),
  create: (patientId, payload) =>
    apiRequest(`/patients/${patientId}/examples`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
};
```

Rules for services:

- Patient-scoped paths always start with `/patients/<patientId>/`, and the
  patient id comes from the authenticated user, not from user input.
- Keep endpoint paths, methods, bodies and response handling identical to the
  existing contract. A new field or endpoint needs backend agreement first.
- Uploads send `FormData` and pass `timeoutMs: 120000` for large files.
- Do not swallow errors and do not return `[]` on failure; let the page decide
  between "unavailable", "error" and "empty".

Current services: `assistance`, `biomarkers`, `clinical`, `documents`,
`documentSecurity`, `family`, `holistic`, `insurance`, `patients`,
`accessGrants`, `medications`, `timeline`.

## Insurance

There is exactly one Insurance implementation:

- Page: `frontend/src/modules/insurance-info/InsurancePage.jsx`
- Route: `/modules/insurance` (the registry path); `/patient/insurance`
  redirects there.
- Service: `frontend/src/api/insurance.js` (`insuranceApi`), patient-scoped.

The page has three tabs — add a policy, saved policies/expenses/claims, and the
Medical Card. Each section loads independently and shows its own loading,
unavailable, error-with-retry or empty state, so an unreachable endpoint is never
displayed as "no records".

Honesty rules preserved in the UI:

- Extracted policies are marked as extracted, never as insurer-verified.
- Saving a policy always sends `verification_status: 'patient_confirmed'`.
- `source` is `pdf_extracted` only when a `document_id` backs the fields.
- Remaining coverage is not calculated without verified utilization data.
- No claim approval or reimbursement outcome is promised.

## Development previews

`npm run dev` also exposes developer-only pages that are excluded from
production UI:

- `/preview` — module picker and isolated module previews.
- `/preview/insurance` and `/preview/holistic` — module pages backed by
  in-memory API replacements. Nothing is sent to a server and records vanish on
  refresh. The insurance preview passes its memory service to the page as an
  `api` prop, so it never replaces the shared `insuranceApi` singleton and cannot
  leak into the real application. The holistic preview still swaps that module's
  service object at runtime and is due the same treatment.

Seeded test accounts on the login screen render only when `import.meta.env.DEV`
is true, so they are stripped from production builds.

## Known limitations

- Backend endpoints, schemas and AI Engine responses are maintained separately;
  any contract change needs confirmation before the frontend relies on it.
- Error classification is proposed, not agreed: the frontend assumes `501` means
  "capability not implemented" and `404` means "resource absent". Shreyash still
  needs to confirm which status the backend returns for an unregistered route.
- Access-grant revoke/audit exists twice (`familyApi` and `accessGrantsApi`).
  `accessGrantsApi` is the recommended canonical service; the duplicate is kept
  until the `resource_type` audit filter is confirmed optional.
- Accessibility has been reviewed by source inspection (labels, table headers,
  tab semantics, live regions). Browser-based keyboard and 200%-zoom checks still
  need a run against the real application.
- The React Hooks compiler lint rules (`set-state-in-effect` and friends) are not
  enabled yet; adopting them requires refactoring the data-loading effects in
  every module.

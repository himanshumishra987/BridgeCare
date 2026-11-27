// @vitest-environment node
// MSW intercepts the global fetch, which is Node's implementation; keeping this
// suite in the node environment avoids mixing jsdom's AbortSignal with undici's.
import { describe, expect, it } from 'vitest';
import { http, HttpResponse } from 'msw';
import { insuranceApi } from './insurance';
import { server } from '../test/server';

const BASE = 'http://localhost:8000/api/v1/patients/p1/insurance';

describe('insuranceApi', () => {
  it('reads policies, expenses and claims under the patient scope', async () => {
    const seen = [];
    server.use(
      http.get(`${BASE}/policies`, ({ request }) => {
        seen.push(request.url);
        return HttpResponse.json([{ id: 'pol-1' }]);
      }),
      http.get(`${BASE}/expenses`, () => HttpResponse.json([])),
      http.get(`${BASE}/claims`, () => HttpResponse.json([]))
    );

    await expect(insuranceApi.getPolicies('p1')).resolves.toEqual([{ id: 'pol-1' }]);
    await expect(insuranceApi.getExpenses('p1')).resolves.toEqual([]);
    await expect(insuranceApi.getClaims('p1')).resolves.toEqual([]);
    expect(seen[0]).toBe(`${BASE}/policies`);
  });

  it('posts a new policy with valid_until normalised to null', async () => {
    let body;
    server.use(
      http.post(`${BASE}/policies`, async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ id: 'pol-2' }, { status: 201 });
      })
    );

    await insuranceApi.addPolicy('p1', { insurer: 'Acme', policy_number: 'A-1' });

    expect(body.valid_until).toBeNull();
    expect(body.insurer).toBe('Acme');
  });

  it('uploads the policy PDF as multipart field "file" to the patient-scoped extract path', async () => {
    let fieldName = null;
    let filename = null;
    server.use(
      http.post(`${BASE}/policies/extract`, async ({ request }) => {
        const form = await request.formData();
        const file = form.get('file');
        fieldName = 'file';
        filename = file?.name ?? null;
        return HttpResponse.json({ document_id: 'd1', fields: {}, field_sources: {} });
      })
    );

    const file = new File(['%PDF-1.4'], 'policy.pdf', { type: 'application/pdf' });
    const result = await insuranceApi.extractPolicy('p1', file);

    expect(fieldName).toBe('file');
    expect(filename).toBe('policy.pdf');
    expect(result.document_id).toBe('d1');
  });

  it('reads and saves the medical card with GET and PUT on the same record', async () => {
    const methods = [];
    let body;
    server.use(
      http.get(`${BASE}/medical-card`, ({ request }) => {
        methods.push(request.method);
        return HttpResponse.json(null);
      }),
      http.put(`${BASE}/medical-card`, async ({ request }) => {
        methods.push(request.method);
        body = await request.json();
        return HttpResponse.json(body);
      })
    );

    await expect(insuranceApi.getMedicalCard('p1')).resolves.toBeNull();
    await insuranceApi.saveMedicalCard('p1', { holder_name: 'Asha', card_number: 'MC-1' });

    expect(methods).toEqual(['GET', 'PUT']);
    expect(body).toEqual({ holder_name: 'Asha', card_number: 'MC-1' });
  });

  it('uploads a medical card document under the same patient scope', async () => {
    let url;
    server.use(
      http.post(`${BASE}/medical-card/documents`, ({ request }) => {
        url = request.url;
        return HttpResponse.json({ document_id: 'cd1', fields: {} });
      })
    );

    const file = new File(['png'], 'card.png', { type: 'image/png' });
    await insuranceApi.uploadCardDocument('p1', file);

    expect(url).toBe(`${BASE}/medical-card/documents`);
  });
});

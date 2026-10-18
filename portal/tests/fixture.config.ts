// Local browser-QA fixture only. This is not Part 3's mock or real relay.
import { defineConfig } from 'vite';
import { readFileSync } from 'node:fs';

const source = 'Isolate power. Torque the gland nut to 4 N-m. Check the witness mark.';
const freshStep = () => ({ label: '1', glance: 'Torque to 5 N-m', body: 'Torque the gland nut to 5 N-m.', warning: 'Isolate power.', checkpoint: 'Check the witness mark.', quotes: [source], diagram: { kind: 'schematic', alt: 'Gland nut', elements: [] }, diagram_id: 'DGM-1', diagram_approved: false, verify: { ok: false, reason: 'Body says 5 N-m; no quote contains 5 N-m.' } });
let draft = { doc_id: 'SOP-150', revision: 'A', title: 'Synthetic pump seal swap', material_id: 'MAT-1', status: 'ready', steps: [freshStep()], warnings: [] };
let paired = false, assigned = false, advanced = false;
const diagram = readFileSync(new URL('./diagram-fixture.png', import.meta.url));

export default defineConfig({
  base: '/portal/', server: { host: '127.0.0.1', port: 5177, strictPort: true, fs: { allow: ['..'] } },
  plugins: [{
    name: 'explicit-test-fixture',
    transformIndexHtml(html) { return html.replace('<body>', '<body><p style="background:#fff0b8;color:#302504;padding:12px;margin:0">FIXTURE API · Local UI checks only. Not the Part 3 relay.</p>'); },
    configureServer(server) {
      server.middlewares.use(async (req, res, next) => {
        const path = req.url?.split('?')[0] || '';
        if (!path.startsWith('/v1/') && path !== '/__fixture/next') return next();
        res.setHeader('Content-Type', 'application/json');
        const send = (data: unknown, status = 200) => { res.statusCode = status; res.end(JSON.stringify(data)); };
        if (path === '/__fixture/next') { advanced = true; send({ ok: true }); return; }
        if (req.headers.authorization !== 'Bearer fixture-token') { send({ detail: 'Use fixture-token for the local fixture API.' }, 401); return; }
        let data = ''; for await (const part of req) data += part;
        if (path === '/v1/devices/claim') { paired = true; send({ device_id: 'LNS-1', worker_name: 'Bay 3', claimed: true }); }
        else if (path === '/v1/devices') send(paired ? [{ device_id: 'LNS-1', worker_name: 'Bay 3', claimed: true }] : []);
        else if (path === '/v1/materials' && req.method === 'GET') {
          const query = new URL(req.url!, 'http://fixture').searchParams.get('q')?.toLowerCase() ?? '';
          const item = { ...draft, filename: 'synthetic-sop.txt', mime: 'text/plain', created_at: '2026-10-18T12:00:00Z', size_bytes: source.length, sha256: 'fixture-only' };
          send({ items: `${item.doc_id} ${item.title} ${item.filename}`.toLowerCase().includes(query) ? [item] : [], next_offset: null });
        }
        else if (path === '/v1/materials') { draft = { ...draft, status: 'ready', steps: [freshStep()] }; paired = assigned = advanced = false; send({ material_id: 'MAT-1', status: 'converting' }); }
        else if (path === '/v1/materials/MAT-1/file') { res.setHeader('Content-Type', 'text/plain'); res.end(source); }
        else if (path === '/v1/materials/MAT-1') send({ ...draft, status: draft.status });
        else if (path === '/v1/materials/MAT-1/text') send({ material_id: 'MAT-1', pages: [{ page: 1, text: source }], figures: [] });
        else if (path === '/v1/drafts/SOP-150/A') send(draft);
        else if (path === '/v1/drafts/SOP-150/A/steps/1') {
          Object.assign(draft.steps[0], JSON.parse(data));
          const ok = !draft.steps[0].body.includes('5 N-m') && !draft.steps[0].glance.includes('5 N-m');
          draft.steps[0].verify = { ok, reason: ok ? '' : '5 N-m is absent from source quotes' }; send(draft.steps[0]);
        } else if (path.endsWith('/diagrams/DGM-1/approve')) { draft.steps[0].diagram_approved = true; send({ ok: true }); }
        else if (path.endsWith('/preview.png')) { res.setHeader('Content-Type', 'image/png'); res.end(diagram); }
        else if (path === '/v1/drafts/SOP-150/A/approve') {
          if (!draft.steps[0].verify.ok || !draft.steps[0].diagram_approved) send({ detail: 'Step 1 must pass and the diagram must be approved.' }, 409);
          else { draft.status = 'approved'; send({ doc_id: 'SOP-150', revision: 'A', steps: 1 }); }
        } else if (path === '/v1/procedures') send(draft.status === 'approved' ? [{ doc_id: 'SOP-150', revision: 'A', title: draft.title, status: 'effective' }] : []);
        else if (path === '/v1/assignments') { assigned = true; send({ assignment_id: 'ASN-1' }); }
        else if (path === '/v1/progress') send(assigned ? [{ device_id: 'LNS-1', worker_name: 'Bay 3', doc_id: 'SOP-150', title: draft.title, assignment_id: 'ASN-1', step_index: advanced ? 2 : 1, total: 6, kind: 'step_started', ts: Date.now(), step_started_at: Date.now() - 120000, deviations: [{ deviation_id: 'DEV-1', text: 'Synthetic witness mark missing.' }] }] : []);
        else send({ detail: `Fixture route not found: ${path}` }, 404);
      });
    },
  }],
});

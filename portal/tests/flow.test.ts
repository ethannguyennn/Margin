import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { TOKEN_KEY } from '../src/api';

// Contract-shaped fixture API, explicitly not Part 3's missing mock relay.
const step = { label: '1', glance: 'Torque to 5 N-m', body: 'Torque to 5 N-m.', warning: null, checkpoint: null, quotes: ['Torque to 4 N-m.'], diagram: null, diagram_id: null, diagram_approved: false, verify: { ok: false, reason: '5 N-m is not in the source quotes' } };
let draft: any;
let paired: boolean;
let assigned: boolean;
let progress: boolean;
let calls: [string, RequestInit][];

beforeEach(async () => {
  vi.resetModules(); sessionStorage.clear(); location.hash = 'upload';
  document.body.innerHTML = '<nav></nav><button id="logout"></button><p id="notice"></p><main id="app"></main>';
  draft = { doc_id: 'SOP-150', revision: 'A', title: 'Seal swap', material_id: 'MAT-1', status: 'ready', steps: [structuredClone(step)], warnings: [] };
  paired = assigned = progress = false; calls = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
    calls.push([url, init]); let data: any = {};
    if (url.startsWith('/v1/materials?')) {
      const q = new URL(url, 'http://localhost').searchParams.get('q') ?? '';
      data = { items: q === 'missing' ? [] : [{ ...draft, filename: 'synthetic.txt', created_at: '2026-10-18T12:00:00Z', size_bytes: 64, status: 'failed', error: 'Conversion unavailable' }], next_offset: null };
    }
    else if (url === '/v1/materials/MAT-1/file') return new Response('Torque to 4 N-m.', { headers: { 'Content-Type': 'text/plain' } });
    else if (url === '/v1/materials') data = { material_id: 'MAT-1', status: 'converting' };
    else if (url === '/v1/materials/MAT-1') data = { ...draft, status: 'ready' };
    else if (url.endsWith('/text')) data = { material_id: 'MAT-1', pages: [{ page: 1, text: 'Torque to 4 N-m.' }], figures: [] };
    else if (url.endsWith('/steps/1')) { Object.assign(draft.steps[0], JSON.parse(init.body as string), { verify: { ok: true } }); data = draft.steps[0]; }
    else if (url.endsWith('/approve')) { draft.status = 'approved'; data = { doc_id: 'SOP-150', revision: 'A', steps: 1 }; }
    else if (url === '/v1/drafts/SOP-150/A') data = draft;
    else if (url === '/v1/orgs/me') data = { org_id: 'ORG-1', name: 'Fixture works', join_code: 'K7P2QX' };
    else if (url === '/v1/devices/claim') { paired = true; data = {}; }
    else if (url === '/v1/devices') data = paired ? [{ device_id: 'LNS-1', worker_name: 'Bay 3', claimed: true }] : [];
    else if (url === '/v1/procedures') data = draft.status === 'approved' ? [{ ...draft, status: 'effective' }] : [];
    else if (url === '/v1/assignments') { assigned = true; data = {}; }
    else if (url === '/v1/progress') data = assigned ? [{ device_id: 'LNS-1', worker_name: 'Bay 3', assignment_id: 'ASN-1', doc_id: 'SOP-150', title: 'Seal swap', step_index: progress ? 2 : 1, total: 6, kind: progress ? 'step_completed' : 'step_started', ts: Date.now(), deviations: [{ deviation_id: 'DEV-1', text: 'Witness mark missing' }] }] : [];
    else throw new Error(`Unexpected fixture request ${url}`);
    return new Response(JSON.stringify(data), { headers: { 'Content-Type': 'application/json' } });
  }));
  await import('../src/main');
});
afterEach(() => { vi.unstubAllGlobals(); });

function input(name: string, value: string) {
  const node = document.querySelector<HTMLInputElement>(`[name="${name}"]`)!;
  node.value = value; node.dispatchEvent(new Event('input', { bubbles: true }));
}
function click(text: string) {
  const node = [...document.querySelectorAll<HTMLButtonElement>('button')].find(b => b.textContent === text)!;
  expect(node, `Button ${text}`).toBeTruthy(); node.click();
}
async function until(check: () => void) { await vi.waitFor(check, { timeout: 2000, interval: 5 }); }

it('completes upload -> failed review -> edit -> approval -> pair -> assign -> board on fixture API', async () => {
  input('token', 'K7P2QX'); click('Open workspace');
  await until(() => expect(document.querySelector('[name="file"]')).toBeTruthy());
  input('doc_id', 'SOP-150'); input('title', 'Seal swap');
  const file = document.querySelector<HTMLInputElement>('[name="file"]')!;
  Object.defineProperty(file, 'files', { value: [new File(['Torque to 4 N-m.'], 'synthetic.txt', { type: 'text/plain' })] });
  // jsdom's file-control validity does not observe the injected FileList.
  file.required = false;
  click('Upload and convert');
  await until(() => expect(document.querySelector('[data-step="1"]')).toBeTruthy());
  expect(document.querySelector('#app')?.textContent).toContain('FAIL');
  const approval = [...document.querySelectorAll('button')].find(b => b.textContent === 'Approve and publish')!;
  expect(approval.disabled).toBe(true);
  expect(document.querySelector('mark')?.textContent).toBe('Torque to 4 N-m.');
  input('glance', 'Torque to 4 N-m'); input('body', 'Torque to 4 N-m.');
  expect(document.querySelector('#app')?.textContent).toContain('UNSAVED');
  click('Save and verify');
  await until(() => expect(approval.disabled).toBe(false));
  click('Approve and publish');
  await until(() => expect(document.querySelector('h1')?.textContent).toBe('Assign a procedure'));
  location.hash = 'devices';
  await until(() => expect(document.querySelector('[name="pair_code"]')).toBeTruthy());
  input('pair_code', '4F7K'); input('worker_name', 'Bay 3'); click('Pair device');
  await until(() => expect(paired).toBe(true));
  location.hash = 'assign';
  await until(() => expect(document.querySelector('[name="procedure"] option[value="SOP-150/A"]')).toBeTruthy());
  input('device_id', 'LNS-1'); input('procedure', 'SOP-150/A'); click('Assign task');
  await until(() => expect(document.querySelector('h1')?.textContent).toBe('Live board'));
  await until(() => expect(document.body.textContent).toContain('Witness mark missing'));
  expect(document.body.textContent).toContain('1/6');
  progress = true;
  await vi.waitFor(() => expect(document.body.textContent).toContain('2/6'), { timeout: 4000, interval: 100 });
  expect(sessionStorage.getItem(TOKEN_KEY)).toBe('K7P2QX');
  expect(calls.every(([, init]) => new Headers(init.headers).get('Authorization') === 'Bearer K7P2QX')).toBe(true);
  location.hash = 'upload';
});

it('finds persisted uploads after navigation and downloads failed conversions with portal auth', async () => {
  input('token', 'fixture-token'); click('Open workspace');
  await until(() => expect(document.querySelector('[name="file"]')).toBeTruthy());
  location.hash = 'library';
  await until(() => expect(document.querySelector('article')?.textContent).toContain('synthetic.txt'));
  expect(document.body.textContent).toContain('Conversion unavailable');
  // Download uses fetch with the session token; the bearer token never enters an href.
  const create = vi.fn().mockReturnValue('blob:download-test');
  vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: create, revokeObjectURL: vi.fn() }));
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  click('Download original');
  await until(() => expect(create).toHaveBeenCalled());
  const call = calls.find(([url]) => url === '/v1/materials/MAT-1/file')!;
  expect(new Headers(call[1].headers).get('Authorization')).toBe('Bearer fixture-token');
  expect([...document.querySelectorAll('a')].some(a => a.href.includes('fixture-token'))).toBe(false);
  input('q', 'missing'); click('Search uploads');
  await until(() => expect(document.body.textContent).toContain('No saved uploads match this search.'));
  location.hash = 'upload';
});

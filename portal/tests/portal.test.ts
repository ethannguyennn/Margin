import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError, json, poll, TOKEN_KEY } from '../src/api';
import { approvalReasons, highlightSource, minutesOnStep, preview } from '../src/view';

const step = () => ({ label: '1', glance: 'Torque to 4 N-m', body: 'Torque the gland nut to 4 N-m.', warning: 'Isolate power.', checkpoint: null, quotes: ['Torque the gland nut to 4 N-m.'], diagram: null, diagram_id: null, diagram_approved: false, verify: { ok: true } });
const draft = () => ({ doc_id: 'SOP-150', revision: 'A', title: 'Seal swap', status: 'ready', steps: [step()] });

beforeEach(() => { sessionStorage.clear(); });
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

describe('publication gate', () => {
  it('requires verified steps, approved diagrams and saved edits', () => {
    const d = draft();
    expect(approvalReasons(d)).toEqual([]);
    expect(approvalReasons(d, true).join()).toContain('Save all edited');
    d.steps[0].verify.ok = false;
    expect(approvalReasons(d).join()).toContain('verification required');
    d.steps[0].verify.ok = true;
    Object.assign(d.steps[0], { diagram: { kind: 'schematic', alt: 'Seal' }, diagram_id: 'DGM-1' });
    expect(approvalReasons(d).join()).toContain('approve the diagram');
    d.steps[0].diagram_approved = true;
    expect(approvalReasons(d)).toEqual([]);
    expect(approvalReasons({ ...d, steps: [] }).join()).toContain('no steps');
    expect(approvalReasons({ ...d, status: 'converting' }).join()).toContain('ready');
  });
});

it('highlights source quotes without executing material HTML', () => {
  const text = 'Warning <img src=x onerror=alert(1)>\nTorque  the gland nut to 4 N-m.';
  const node = highlightSource(text, ['Torque the gland nut to 4 N-m.', '4 N-m.']);
  expect(node.querySelectorAll('mark')).toHaveLength(1);
  expect(node.querySelector('mark')?.textContent).toBe('Torque  the gland nut to 4 N-m.');
  expect(node.querySelector('img')).toBeNull();
  expect(node.textContent).toBe(text);
});

it('uses the shared lens screen renderer', () => {
  const d = draft(); const node = preview(d, d.steps[0], 0);
  expect(node.textContent).toContain('SOP-150 rev A');
  expect(node.textContent).toContain('step 1/1');
  expect(node.textContent).toContain('Torque to 4 N-m');
});

it('shows minutes on the current step, clamped at zero', () => {
  expect(minutesOnStep({ step_started_at: 1000, ts: 100000 }, 121000)).toBe('2 min');
  expect(minutesOnStep({ ts: 1000 }, 0)).toBe('0 min');
});

it('sends session token on same-origin JSON and multipart calls', async () => {
  sessionStorage.setItem(TOKEN_KEY, 'fixture-token');
  const fetcher = vi.fn().mockImplementation(async () => new Response('{}', { headers: { 'content-type': 'application/json' } }));
  vi.stubGlobal('fetch', fetcher);
  await api('/v1/devices/claim', json('POST', { pair_code: '4F7K' }));
  expect(fetcher.mock.calls[0][0]).toBe('/v1/devices/claim');
  expect(fetcher.mock.calls[0][1].headers.get('Authorization')).toBe('Bearer fixture-token');
  const data = new FormData(); data.append('file', new Blob(['synthetic']), 'sop.txt');
  await api('/v1/materials', { method: 'POST', body: data });
  expect(fetcher.mock.calls[1][1].headers.has('Content-Type')).toBe(false);
  await expect(api('https://external.example/v1/devices')).rejects.toThrow('same origin');
  expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
});

it('shows server 409 reasons and clears rejected credentials', async () => {
  sessionStorage.setItem(TOKEN_KEY, 'fixture-token');
  const fetcher = vi.fn().mockImplementation(async () => new Response(JSON.stringify({ detail: [{ label: '2', reason: '5 N-m is absent from quotes' }] }), { status: 409 }));
  vi.stubGlobal('fetch', fetcher);
  await expect(api('/v1/drafts/SOP-150/A/approve', json('POST'))).rejects.toThrow('Step 2: 5 N-m is absent from quotes');
  fetcher.mockResolvedValueOnce(new Response('{}', { status: 401 }));
  await expect(api('/v1/devices')).rejects.toBeInstanceOf(ApiError);
  expect(sessionStorage.getItem(TOKEN_KEY)).toBeNull();
});

it('polls at three seconds, skips overlapping calls and stops on disposal', async () => {
  vi.useFakeTimers(); let finish!: () => void;
  const action = vi.fn().mockImplementationOnce(() => new Promise<void>(resolve => { finish = resolve; })).mockResolvedValue(undefined);
  const stop = poll(action, 3000);
  expect(action).toHaveBeenCalledTimes(1);
  await vi.advanceTimersByTimeAsync(6000);
  expect(action).toHaveBeenCalledTimes(1);
  finish(); await Promise.resolve();
  await vi.advanceTimersByTimeAsync(3000);
  expect(action).toHaveBeenCalledTimes(2);
  stop(); await vi.advanceTimersByTimeAsync(9000);
  expect(action).toHaveBeenCalledTimes(2);
});

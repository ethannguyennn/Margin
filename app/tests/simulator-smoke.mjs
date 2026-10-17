// Uses only the official simulator's documented automation API.
// Run against a freshly launched `npm run dev:mock` + `npm run simulate`.
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
const origin = 'http://127.0.0.1:9898';
const output = new URL('../test-artifacts/', import.meta.url);
await mkdir(output, { recursive: true });
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
async function get(path) {
  const result = await fetch(`${origin}/api/${path}`, { signal: AbortSignal.timeout(5000) });
  assert.ok(result.ok, `${path}: ${result.status}`); return result;
}
async function consoleEntries() { return (await (await get('console')).json()).entries; }
async function screen() {
  const entries = await consoleEntries();
  return entries.filter(e => e.message.includes('[Margin] screen=')).at(-1)?.message.match(/screen=(\w+)/)?.[1];
}
const checks = [];
async function assertScreen(expected) {
  const actual = await screen(); assert.equal(actual, expected);
  checks.push({ expected, actual }); console.log(`PASS ${expected}`);
}
async function input(action, expected, ms = 180) {
  const response = await fetch(`${origin}/api/input`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action }), signal: AbortSignal.timeout(5000) });
  assert.ok(response.ok); await wait(ms); if (expected) await assertScreen(expected);
}
async function screenshot(name) {
  for (const view of ['glasses','webview']) {
    const response = await get(`screenshot/${view}`);
    await writeFile(new URL(`${name}-${view}.png`, output), Buffer.from(await response.arrayBuffer()));
  }
}

assert.equal(await (await get('ping')).text(), 'pong');
const initial = await screen();
assert.ok(['PRIVACY','IDLE'].includes(initial), 'Launch a fresh fixture session before smoke test');
if (initial === 'PRIVACY') await input('click', 'IDLE');
await assertScreen('IDLE');
await input('click', 'LISTENING'); await screenshot('listening');
await input('click', 'THINKING', 100); await wait(650); await assertScreen('ANSWER_GLANCE'); await screenshot('answer-glance');
await input('click', 'ANSWER_EXPANDED'); await screenshot('answer-expanded');
await input('click', 'ANSWER_GLANCE'); await input('double_click', 'IDLE');
await input('click', 'LISTENING'); await input('click', 'THINKING', 100); await wait(650); await assertScreen('NOT_FOUND'); await screenshot('not-found');
await input('double_click', 'IDLE');
await input('click', 'LISTENING'); await input('click', 'THINKING', 100); await wait(650); await assertScreen('ERROR'); await screenshot('error');
await input('double_click', 'IDLE');
await input('click', 'LISTENING'); await input('click', 'THINKING', 100); await wait(650); await assertScreen('WALKTHROUGH'); await screenshot('walkthrough-1');
await input('down', 'WALKTHROUGH'); await input('click', 'ANSWER_EXPANDED');
await input('down', 'ANSWER_EXPANDED'); await screenshot('walkthrough-details-page-2');
await input('double_click', 'WALKTHROUGH'); await input('down', 'WALKTHROUGH'); await screenshot('walkthrough-3');
const walkLogs = (await consoleEntries()).filter(e => e.message.includes('[Margin] screen=WALKTHROUGH'));
assert.ok(walkLogs.some(e => e.message.includes('step=1'))); assert.ok(walkLogs.some(e => e.message.includes('step=2')));
const fixtureLogs = (await consoleEntries()).filter(e => e.message.includes('[Margin] UI fixture='));
assert.equal(fixtureLogs.length, 4, 'Step navigation must not call ask');
await input('double_click', 'IDLE');
await input('click', 'LISTENING'); await input('click', 'THINKING', 100); await wait(650); await assertScreen('LOGGED'); await screenshot('logged');
await input('click', 'IDLE');
// Root exit last: the simulator may close its active page after this call.
await input('double_click'); await screenshot('root-exit');
const entries = await consoleEntries();
assert.ok(entries.some(e => e.message.includes('[Margin] native exit confirmation requested')));
assert.ok(entries.some(e => e.message.includes('[Margin] native exit accepted')), 'SDK must accept the native shutdown request');
const systemExitEventObserved = entries.some(e => e.message.includes('"eventType":7'));
const errors = entries.filter(e => e.level === 'error' || /\[uncaught\]|\[unhandledrejection\]|\[Margin\] boot failed/.test(e.message));
assert.deepEqual(errors, [], 'No simulator/app errors');
await writeFile(new URL('simulator-console.json', output), JSON.stringify(entries, null, 2));
await writeFile(new URL('simulator-results.json', output), JSON.stringify({ checks, nativeExitAccepted: true, systemExitEventObserved, errors }, null, 2));
console.log(`PASS ${checks.length} screen assertions; local walkthrough; native root exit; no console errors.`);

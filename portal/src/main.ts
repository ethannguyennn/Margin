import './style.css';
import { api, json, poll, TOKEN_KEY, type JsonObject } from './api';
import { approvalReasons, element as el, highlightSource, minutesOnStep, preview } from './view';

const app = document.querySelector<HTMLElement>('#app')!;
const nav = document.querySelector<HTMLElement>('nav')!;
const logout = document.querySelector<HTMLButtonElement>('#logout')!;
const notice = document.querySelector<HTMLElement>('#notice')!;
const draftKey = 'margin.portal.draft';
let dispose: (() => void)[] = [];
let generation = 0;

function message(text = '', failure = false) { notice.textContent = text; notice.className = failure ? 'failure' : ''; }
function error(exc: unknown) { message(exc instanceof Error ? exc.message : 'The request failed. Try again.', true); }
function link(text: string, href: string) { const a = el('a', text); a.href = href; return a; }
function button(text: string, action: () => void | Promise<void>, className = '') {
  const b = el('button', text, className); b.type = 'button';
  b.onclick = async () => { b.disabled = true; try { await action(); } catch (exc) { error(exc); } finally { if (b.isConnected) b.disabled = false; } };
  return b;
}
function heading(title: string, text: string) { app.append(el('h1', title), el('p', text, 'intro')); }
function field(form: HTMLElement, name: string, label: string, options: { type?: string; value?: string; max?: number; pattern?: string; required?: boolean; multiline?: boolean } = {}) {
  const wrapper = el('div', undefined, 'field');
  const id = `field-${name}-${crypto.randomUUID()}`;
  const lab = el('label', label); lab.htmlFor = id;
  const input = options.multiline ? el('textarea') : el('input');
  input.id = id; input.name = name; input.value = options.value ?? ''; input.required = options.required ?? true;
  if (input instanceof HTMLInputElement) { input.type = options.type ?? 'text'; if (options.pattern) input.pattern = options.pattern; }
  if (options.max !== undefined) input.maxLength = options.max;
  wrapper.append(lab, input); form.append(wrapper); return input;
}
function submit(form: HTMLFormElement, title: string, action: () => Promise<void>) {
  const b = el('button', title, 'primary'); b.type = 'submit'; form.append(b);
  form.onsubmit = async event => {
    event.preventDefault();
    if (!form.reportValidity()) return;
    b.disabled = true; message();
    try { await action(); } catch (exc) { error(exc); } finally { if (b.isConnected) b.disabled = false; }
  };
  return b;
}
function formObject(form: HTMLFormElement): Record<string, FormDataEntryValue> { return Object.fromEntries(new FormData(form)); }
function draftPath(doc: string, rev: string) { return `/v1/drafts/${encodeURIComponent(doc)}/${encodeURIComponent(rev)}`; }

function login() {
  heading('Employer portal', 'Enter the shared portal token to review and assign procedures.');
  const form = el('form', undefined, 'login');
  const token = field(form, 'token', 'Portal token', { type: 'password' });
  token.autocomplete = 'off';
  submit(form, 'Log in', async () => {
    sessionStorage.setItem(TOKEN_KEY, token.value.trim());
    try { await api('/v1/devices'); } catch (exc) { sessionStorage.removeItem(TOKEN_KEY); throw exc; }
    await route();
  });
  app.append(form);
}

function upload() {
  heading('Upload material', 'Turn a synthetic SOP into a procedure. Review and approval come before assignment.');
  const form = el('form', undefined, 'upload');
  const file = field(form, 'file', 'Synthetic SOP file · up to 20 MB', { type: 'file' }) as HTMLInputElement;
  file.accept = '.pdf,.docx,.md,.txt,.png,.jpg,.jpeg';
  field(form, 'doc_id', 'Document ID', { value: 'SOP-', pattern: '[A-Z]{2,5}-[0-9]{3}', max: 9 });
  field(form, 'title', 'Procedure title', { max: 120 });
  field(form, 'revision', 'Revision', { value: 'A', pattern: '[A-Z0-9]{1,3}', max: 3 });
  submit(form, 'Upload and convert', async () => {
    const selected = file.files?.[0];
    if (!selected || !selected.size || selected.size > 20 * 1024 * 1024) throw new Error('Choose a nonempty file up to 20 MB.');
    const result = await api('/v1/materials', { method: 'POST', body: new FormData(form) });
    location.hash = `material/${encodeURIComponent(result.material_id)}`;
  });
  app.append(form);
  const recent = sessionStorage.getItem(draftKey);
  if (recent) app.append(link('Return to the latest draft', `#review/${recent}`));
  const open = el('form', undefined, 'open-draft');
  open.append(el('h2', 'Open an existing draft'));
  const doc = field(open, 'doc', 'Document ID', { pattern: '[A-Z]{2,5}-[0-9]{3}' });
  const rev = field(open, 'rev', 'Revision', { pattern: '[A-Z0-9]{1,3}', max: 3 });
  submit(open, 'Open draft', async () => { location.hash = `review/${encodeURIComponent(doc.value)}/${encodeURIComponent(rev.value)}`; });
  app.append(open);
}

function materialStatus(id: string, epoch: number) {
  heading('Converting material', 'You can leave this page and return while the relay converts your upload.');
  const status = el('p', 'Checking conversion status…'); status.setAttribute('role', 'status'); app.append(status);
  let stop = () => {};
  stop = poll(async () => {
    try {
      const data = await api(`/v1/materials/${encodeURIComponent(id)}`);
      if (generation !== epoch) return;
      if (data.status === 'ready' || data.status === 'approved') {
        stop(); location.hash = `review/${encodeURIComponent(data.doc_id)}/${encodeURIComponent(data.revision)}`;
      } else if (data.status === 'failed') {
        stop(); status.textContent = `Conversion failed: ${data.error || 'Upload the material again.'}`;
        app.append(link('Upload again', '#upload'));
      } else status.textContent = 'Converting… This page checks every 2 seconds.';
    } catch (exc) { if (generation === epoch) { status.textContent = 'Status unavailable. Retrying…'; error(exc); } }
  }, 2000);
  dispose.push(stop);
}

async function review(doc: string, rev: string, epoch: number) {
  const path = draftPath(doc, rev);
  const draft: JsonObject = await api(path);
  const material: JsonObject = await api(`/v1/materials/${encodeURIComponent(draft.material_id)}/text`);
  if (generation !== epoch) return;
  sessionStorage.setItem(draftKey, `${encodeURIComponent(doc)}/${encodeURIComponent(rev)}`);
  heading(`${draft.title} · ${doc} rev ${rev}`, 'Check the source, edit each step, and approve its diagram before publishing.');
  const immutable = draft.status === 'approved';
  if (immutable) app.append(el('p', 'APPROVED · This revision is published. Upload a new revision to make changes.', 'pass'));
  const dirty = new Set<string>();
  const gate = el('section', undefined, 'approval');
  const why = el('p'); why.id = 'approval-reasons'; why.setAttribute('aria-live', 'polite');
  const approve = el('button', 'Approve and publish', 'primary'); approve.type = 'button'; approve.setAttribute('aria-describedby', why.id);
  const updateGate = () => {
    const reasons = approvalReasons(draft, dirty.size > 0);
    why.textContent = immutable ? 'Published and ready to assign.' : reasons.length ? reasons.join('\n') : 'PASS · All steps and attached diagrams are ready.';
    approve.disabled = immutable || reasons.length > 0;
  };
  approve.onclick = async () => {
    approve.disabled = true;
    try { await api(`${path}/approve`, json('POST')); message('Procedure published. Pair a device and assign it.'); location.hash = 'assign'; }
    catch (exc) { error(exc); updateGate(); }
  };
  gate.append(el('h2', 'Approve procedure'), why, approve);
  draft.steps.forEach((step: JsonObject, index: number) => {
    const article = el('article'); article.dataset.step = step.label;
    article.append(el('h2', `Step ${step.label}`));
    const result = el('p', undefined, step.verify?.ok ? 'pass' : 'failure'); result.setAttribute('role', 'status');
    const verifyText = () => {
      result.className = step.verify?.ok && !dirty.has(step.label) ? 'pass' : 'failure';
      result.textContent = dirty.has(step.label) ? 'UNSAVED · Save to verify this edit.' : step.verify?.ok ? 'PASS · Verified against source material.' : `FAIL · ${step.verify?.reason || 'Verification required.'}`;
    };
    verifyText(); article.append(result);
    const columns = el('div', undefined, 'review-columns');
    const source = el('section', undefined, 'source'); source.append(el('h3', 'Source material'));
    material.pages.forEach((page: JsonObject) => {
      const marked = highlightSource(page.text, step.quotes);
      const details = el('details'); details.open = marked.querySelector('mark') !== null;
      details.append(el('summary', `Page ${page.page}`), marked); source.append(details);
    });
    source.append(el('h4', 'Supporting quotes'));
    step.quotes.forEach((quote: string) => source.append(el('blockquote', quote)));
    const edit = el('form'); edit.append(el('h3', 'Step text'));
    const inputs: Record<string, HTMLInputElement | HTMLTextAreaElement> = {};
    const lens = el('section', undefined, 'preview'); lens.append(el('h3', 'Lens preview'));
    const display = el('div'); lens.append(display);
    const current = () => ({ ...step, ...Object.fromEntries(Object.entries(inputs).map(([name, input]) => [name, input.value || null])) });
    const updatePreview = () => { display.replaceChildren(preview(draft, current(), index)); };
    for (const [name, title, max] of [['glance', 'Glance', 60], ['body', 'Body', 450], ['warning', 'Warning', 80], ['checkpoint', 'Checkpoint', 60]] as const) {
      const input = field(edit, name, title, { value: step[name] ?? '', max, required: name === 'glance' || name === 'body', multiline: name === 'body' });
      input.disabled = immutable; inputs[name] = input;
      const count = el('small'); count.id = `${input.id}-count`; input.setAttribute('aria-describedby', count.id);
      input.after(count);
      const update = () => { count.textContent = `${input.value.length}/${max} characters`; updatePreview(); };
      input.oninput = () => { dirty.add(step.label); update(); verifyText(); updateGate(); };
      update();
    }
    const save = submit(edit, 'Save and verify', async () => {
      const value = Object.fromEntries(Object.entries(inputs).map(([k, v]) => [k, v.value || null]));
      const saved = await api(`${path}/steps/${encodeURIComponent(step.label)}`, json('PUT', value));
      Object.assign(step, saved);
      for (const [name, input] of Object.entries(inputs)) {
        input.value = step[name] ?? '';
        input.nextElementSibling!.textContent = `${input.value.length}/${input.maxLength} characters`;
      }
      dirty.delete(step.label); verifyText(); updateGate(); updatePreview();
      message(`Step ${step.label} saved. ${step.verify?.ok ? 'PASS' : 'FAIL: ' + (step.verify?.reason || 'Review the source.')}`);
    });
    save.disabled = immutable;
    const diagrams = el('div', undefined, 'diagram'); diagrams.append(el('h3', 'Diagram'));
    if (step.diagram || step.diagram_id) {
      diagrams.append(el('p', step.diagram_approved ? 'PASS · Diagram approved' : 'REVIEW · Diagram needs approval'));
      if (step.diagram_id) {
        const img = el('img'); img.alt = step.diagram?.alt || `Diagram for step ${step.label}`; img.width = 576; img.height = 144;
        diagrams.append(img);
        void api(`/v1/diagrams/${encodeURIComponent(step.diagram_id)}/preview.png`).then((blob: Blob) => {
          if (generation !== epoch) return;
          const url = URL.createObjectURL(blob); img.src = url; dispose.push(() => URL.revokeObjectURL(url));
        }).catch(exc => { if (generation === epoch) error(exc); });
        if (!immutable) diagrams.append(button('Approve diagram', async () => {
          if (dirty.size) throw new Error('Save edited steps before approving a diagram.');
          await api(`${path}/diagrams/${encodeURIComponent(step.diagram_id)}/approve`, json('POST'));
          await route();
        }));
      }
      if (!immutable) diagrams.append(button('Detach diagram', async () => {
        if (dirty.size) throw new Error('Save edited steps before detaching a diagram.');
        await api(`${path}/steps/${encodeURIComponent(step.label)}`, json('PUT', { ...Object.fromEntries(['glance', 'body', 'warning', 'checkpoint'].map(k => [k, step[k] ?? null])), diagram: null, diagram_id: null }));
        await route();
      }));
    } else diagrams.append(el('p', 'No diagram attached.'));
    lens.append(diagrams); updatePreview();
    columns.append(source, edit, lens); article.append(columns); app.append(article);
  });
  if (draft.warnings?.length) { app.append(el('h2', 'Document warnings')); draft.warnings.forEach((w: string) => app.append(el('blockquote', w))); }
  app.append(gate); updateGate();
}

async function devices(epoch: number) {
  heading('Devices', 'Enter the pair code shown on the lens and a name your team will recognise.');
  const form = el('form', undefined, 'pair');
  field(form, 'pair_code', 'Lens pair code', { max: 4, pattern: '[A-HJ-NP-Za-hj-np-z2-9]{4}' });
  field(form, 'worker_name', 'Worker or station name', { max: 120 });
  submit(form, 'Pair device', async () => {
    const data = formObject(form); data.pair_code = String(data.pair_code).trim().toUpperCase();
    await api('/v1/devices/claim', json('POST', data)); await route(); message('Device paired. You can assign a procedure.');
  });
  app.append(form, link('Assign a procedure', '#assign'));
  const rows: JsonObject[] = await api('/v1/devices'); if (generation !== epoch) return;
  const table = el('table'); table.append(el('caption', 'Paired devices'));
  const head = el('tr'); ['Worker / station', 'Device', 'Status'].forEach(text => head.append(el('th', text))); table.append(head);
  rows.forEach(row => { const tr = el('tr'); [row.worker_name || 'Unnamed', row.device_id, row.claimed === true || row.claimed_at ? 'Paired' : 'Awaiting claim'].forEach(text => tr.append(el('td', text))); table.append(tr); });
  app.append(table);
}

async function assign(epoch: number) {
  const [devices, procedures]: [JsonObject[], JsonObject[]] = await Promise.all([api('/v1/devices'), api('/v1/procedures')]);
  if (generation !== epoch) return;
  heading('Assign a procedure', 'Assignments keep the approved revision they were given, even when a new revision is published.');
  const form = el('form');
  const choices: HTMLSelectElement[] = [];
  for (const [name, title, data, value, label] of [
    ['device_id', 'Paired device', devices.filter(d => d.claimed === true || d.claimed_at), (d: JsonObject) => d.device_id, (d: JsonObject) => `${d.worker_name} · ${d.device_id}`],
    ['procedure', 'Effective procedure', procedures.filter(p => p.status === 'effective'), (p: JsonObject) => `${p.doc_id}/${p.revision}`, (p: JsonObject) => `${p.doc_id} rev ${p.revision} · ${p.title}`],
  ] as const) {
    const lab = el('label', title); const select = el('select'); select.id = name; select.name = name; select.required = true; lab.htmlFor = name;
    const empty = el('option', 'Choose…'); empty.value = ''; select.append(empty);
    data.forEach((d: JsonObject) => { const option = el('option', label(d)); option.value = value(d); select.append(option); });
    form.append(lab, select); choices.push(select);
  }
  const b = submit(form, 'Assign task', async () => {
    const values = formObject(form); const [doc_id, revision] = String(values.procedure).split('/');
    await api('/v1/assignments', json('POST', { device_id: values.device_id, doc_id, revision }));
    location.hash = 'board';
  });
  b.disabled = choices.some(s => s.options.length < 2);
  if (b.disabled) form.append(el('p', 'Pair a device and publish a procedure to enable assignment.'));
  app.append(form, link('Pair a device', '#devices'));
}

function board(epoch: number) {
  heading('Live board', 'Updates every 3 seconds. Deviations are shown with the affected procedure.');
  const stamp = el('p', 'Waiting for the first update…'); stamp.setAttribute('role', 'status');
  const content = el('div', undefined, 'board-table'); app.append(stamp, content);
  const stop = poll(async () => {
    try {
      const rows: JsonObject[] = await api('/v1/progress'); if (generation !== epoch) return;
      const table = el('table'); table.append(el('caption', 'Assignments and progress'));
      const header = el('tr'); ['Worker / station', 'Procedure', 'Step', 'Time on step', 'Last event', 'Procedure deviations'].forEach(text => header.append(el('th', text))); table.append(header);
      rows.forEach(row => {
        const tr = el('tr');
        [row.worker_name || row.device_id, `${row.doc_id}${row.revision ? ` rev ${row.revision}` : ''} · ${row.title}`, `${row.step_index}/${row.total}`, minutesOnStep(row), String(row.kind).replaceAll('_', ' ')].forEach(text => tr.append(el('td', text)));
        const deviations = el('td');
        if (Array.isArray(row.deviations) && row.deviations.length) row.deviations.forEach((d: JsonObject) => deviations.append(el('p', `${d.deviation_id}: ${d.text}`, 'failure')));
        else deviations.textContent = 'None reported';
        tr.append(deviations); table.append(tr);
      });
      content.replaceChildren(rows.length ? table : el('p', 'No assignments yet. Pair a device and assign a procedure.'));
      stamp.textContent = `Updated ${new Date().toLocaleTimeString()}`; message();
    } catch (exc) { if (generation === epoch) { stamp.textContent = 'Connection lost. Displayed progress may be stale. Retrying every 3 seconds.'; error(exc); } }
  }, 3000);
  dispose.push(stop);
}

export async function route() {
  const epoch = ++generation;
  dispose.forEach(cleanup => cleanup()); dispose = []; app.replaceChildren(); message();
  const loggedIn = !!sessionStorage.getItem(TOKEN_KEY); nav.hidden = !loggedIn; logout.hidden = !loggedIn;
  if (!loggedIn) { login(); return; }
  nav.replaceChildren(...['Upload', 'Review', 'Devices', 'Assign', 'Board'].map(text => {
    const dest = text === 'Review' ? `review/${sessionStorage.getItem(draftKey) ?? ''}` : text.toLowerCase();
    const a = link(text, `#${dest}`); if (location.hash.slice(1).startsWith(text.toLowerCase())) a.setAttribute('aria-current', 'page'); return a;
  }));
  try {
    const [page = 'upload', doc, rev] = location.hash.slice(1).split('/').map(decodeURIComponent);
    if (!page || page === 'upload') upload();
    else if (page === 'material' && doc) materialStatus(doc, epoch);
    else if (page === 'review' && doc && rev) await review(doc, rev, epoch);
    else if (page === 'devices') await devices(epoch);
    else if (page === 'assign') await assign(epoch);
    else if (page === 'board') board(epoch);
    else { heading('Open a draft', 'Upload a material or open a draft by its document ID and revision.'); app.append(link('Upload or open a draft', '#upload')); }
  } catch (exc) { if (generation === epoch) { error(exc); app.append(button('Retry', route)); } }
}
logout.onclick = () => { sessionStorage.removeItem(TOKEN_KEY); void route(); };
window.addEventListener('hashchange', () => { void route(); });
window.addEventListener('portal:unauthorized', () => { void route(); message('Your token was rejected. Log in again.', true); });
void route();

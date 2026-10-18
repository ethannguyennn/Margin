import { initialState } from '../../app/src/state';
import { renderScreen } from '../../app/src/ui/screens';
import type { Step, Walkthrough } from '../../app/src/types';
import type { JsonObject } from './api';

export function element<K extends keyof HTMLElementTagNameMap>(tag: K, text?: string, className?: string): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

export function approvalReasons(draft: JsonObject, dirty = false): string[] {
  const reasons: string[] = [];
  if (dirty) reasons.push('Save all edited steps before approval.');
  if (!draft || draft.status !== 'ready') reasons.push('The draft must be ready for review.');
  if (!Array.isArray(draft?.steps) || !draft.steps.length) return [...reasons, 'The draft has no steps.'];
  for (const step of draft.steps) {
    if (step.verify?.ok !== true) reasons.push(`Step ${step.label}: ${step.verify?.reason || 'verification required'}`);
    if ((step.diagram || step.diagram_id) && !(step.diagram && step.diagram_id && step.diagram_approved === true)) {
      reasons.push(`Step ${step.label}: approve the diagram or detach it.`);
    }
  }
  return reasons;
}

export function highlightSource(text: string, quotes: string[]): HTMLElement {
  const pre = element('pre');
  const ranges: [number, number][] = [];
  for (const quote of quotes) {
    if (!quote.trim()) continue;
    const pattern = quote.trim().split(/\s+/).map(s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('\\s+');
    for (const match of text.matchAll(new RegExp(pattern, 'gi'))) ranges.push([match.index!, match.index! + match[0].length]);
  }
  ranges.sort((a, b) => a[0] - b[0]);
  let end = 0;
  for (const [start, stop] of ranges) {
    if (stop <= end) continue;
    if (start > end) pre.append(document.createTextNode(text.slice(end, start)));
    pre.append(element('mark', text.slice(Math.max(start, end), stop)));
    end = stop;
  }
  pre.append(document.createTextNode(text.slice(end)));
  return pre;
}

export function preview(draft: JsonObject, step: JsonObject, index: number): HTMLElement {
  const container = element('div', undefined, 'lens');
  container.setAttribute('aria-label', `Lens preview for step ${step.label}`);
  const state = initialState('portal-preview');
  state.screen = 'WALKTHROUGH';
  const steps = draft.steps.map((s: JsonObject) => ({ ...s, step_id: `${draft.doc_id}:${draft.revision}:${s.label}` } as Step));
  steps[index] = { ...step, step_id: `${draft.doc_id}:${draft.revision}:${step.label}` } as Step;
  state.walkthrough = { doc_id: draft.doc_id, revision: draft.revision, title: draft.title,
    total: steps.length, index, steps } as Walkthrough;
  const rendered = renderScreen(state);
  container.append(element('div', rendered.header, 'lens-header'), element('pre', rendered.main), element('div', rendered.footer, 'lens-footer'));
  return container;
}

export function minutesOnStep(row: JsonObject, now = Date.now()): string {
  const since = Number(row.step_started_at ?? row.ts);
  return Number.isFinite(since) ? `${Math.max(0, Math.floor((now - since) / 60000))} min` : 'Awaiting progress';
}

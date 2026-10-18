import { initialState, LensController, type AskContext, type Gesture, type LensPorts } from '../state';
import type { AskResponse } from '../types';
import { renderScreen } from '../ui/screens';
import { BrowserLensDisplay } from './display';
import './simulator.css';

interface SimulatorOptions {
  sessionId: string;
  ask: LensPorts['ask'];
  getDiagram?: LensPorts['getDiagram'];
  context?: () => AskContext;
  onExchange?: (response: AskResponse, question: string) => void;
}

/** The actual lens controller, with typed speech and a browser display instead of hardware. */
export function mountSimulator(host: HTMLElement, options: SimulatorOptions) {
  const display = new BrowserLensDisplay();
  const root = document.createElement('div'); root.className = 'lens-simulator';
  const bar = document.createElement('div'); bar.className = 'lens-sim-bar';
  const mode = document.createElement('span'); mode.textContent = 'Browser simulation';
  const status = document.createElement('span'); status.setAttribute('role', 'status');
  bar.append(mode, status);
  const form = document.createElement('form'); form.className = 'lens-sim-form';
  const label = document.createElement('label'); label.textContent = 'Question or voice command';
  const input = document.createElement('input'); input.type = 'text'; input.className = 'input';
  input.placeholder = 'Open a procedure, ask a question, or say “next”…'; input.maxLength = 2000;
  label.append(input);
  const send = document.createElement('button'); send.type = 'submit'; send.className = 'primary'; send.textContent = 'Send to simulator'; send.disabled = true;
  form.append(label, send);
  const controls = document.createElement('div'); controls.className = 'lens-sim-controls';
  controls.setAttribute('role', 'group'); controls.setAttribute('aria-label', 'Simulated glasses gestures');
  const note = document.createElement('p'); note.className = 'lens-sim-note';
  note.textContent = 'Type to simulate speech. Tap and swipe controls behave like the glasses.';
  const feedback = document.createElement('p'); feedback.className = 'lens-sim-note'; feedback.setAttribute('role', 'status');
  root.append(bar, display.element, controls, form, note, feedback); host.append(root);
  let disposed = false, closed = false, controller: LensController;
  const updateForm = () => {
    send.disabled = closed || controller.state.screen === 'THINKING' || !input.value.trim();
    for (const button of controls.querySelectorAll('button')) button.disabled = closed && button.textContent !== 'Reset';
  };
  const report = () => { if (!disposed) feedback.textContent = 'Could not load the display or answer. Try again.'; };
  const fresh = () => ({ ...initialState(options.sessionId), screen: 'IDLE' as const, privacySeen: true, calibrated: true,
    pairing: { claimed: true, pair_code: '', worker_name: 'Browser' } });
  const create = () => new LensController(fresh(), {
    ask: async (request, opts) => {
      const response = await options.ask(request, opts);
      if (!response || typeof response.outcome !== 'string') throw new Error('Malformed response');
      if (!disposed && !opts?.signal?.aborted) options.onExchange?.(response, request.text ?? '');
      return response;
    },
    startCapture: async () => {}, // typing replaces microphone capture; no audio is collected
    stopCapture: async () => ({ data_b64: '', sample_rate: 16000 }),
    getDiagram: options.getDiagram,
    render: async (state, level, diagram) => {
      if (disposed) return;
      status.textContent = state.screen.toLowerCase().replaceAll('_', ' ');
      form.setAttribute('aria-busy', String(state.screen === 'THINKING'));
      updateForm();
      await display.render(renderScreen(state, level), state.screen, diagram);
    },
    persist: async () => {}, now: Date.now, onError: report,
    exit: async () => { closed = true; status.textContent = 'closed'; feedback.textContent = 'Simulator closed. Reset to start again.'; updateForm(); },
  });
  controller = create(); void controller.start().catch(report);
  for (const [title, gesture] of [['Double nod', 'NOD'], ['Tap', 'PRESS'], ['Double tap', 'DOUBLE_PRESS'],
    ['Swipe up', 'UP'], ['Swipe down', 'DOWN']] as [string, Gesture][]) {
    const button = document.createElement('button'); button.type = 'button'; button.className = 'ghost'; button.textContent = title;
    button.onclick = () => { if (!closed) { feedback.textContent = ''; controller.dispatch({ type: gesture }); } };
    controls.append(button);
  }
  const reset = document.createElement('button'); reset.type = 'button'; reset.className = 'ghost'; reset.textContent = 'Reset';
  reset.onclick = () => {
    void controller.dispose(); closed = false; feedback.textContent = ''; input.value = '';
    controller = create(); void controller.start().catch(report);
  };
  controls.append(reset);
  input.oninput = updateForm;
  form.onsubmit = event => {
    event.preventDefault();
    if (send.disabled) return;
    const context = controller.state.walkthrough ? undefined : options.context?.();
    if (controller.askText(input.value, context)) { input.value = ''; feedback.textContent = ''; updateForm(); }
  };
  return { controller: () => controller, dispose() { disposed = true; display.dispose(); root.remove(); void controller.dispose(); } };
}

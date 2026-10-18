// The one seam between the lens (main.ts + state.ts, drawn on the glasses through the
// SDK bridge) and the phone screen (src/phone, React in the same WebView). No React
// here and no SDK here: main.ts attaches commands once the bridge is up, and the
// phone UI subscribes. In a plain browser nothing ever attaches, so the phone UI
// runs standalone against the relay.
import type { AskResponse } from './types';
import type { AskContext } from './state';
import type { ScreenText } from './ui/screens';
import type { DiagramImage } from './types';

export interface LensSnapshot {
  /** The Even app bridge is up and the lens controller is running. */
  connected: boolean;
  /** Human-readable connection / screen status for the phone header. */
  status: string;
  /** Current lens screen (state.ts Screen), null until connected. */
  screen: string | null;
  /** Session the lens asks under; the phone uses it so repeat/deviations line up. */
  sessionId: string | null;
  /** Exactly what the glasses display right now (header, main, footer). */
  lensText: string;
  graphic_id?: string;
  frame?: ScreenText;
  diagram?: DiagramImage;
}

export interface LensCommands {
  askText(text: string, context: AskContext): boolean;
  /** Push-to-talk: start listening from a resting screen, or stop and send. */
  togglePushToTalk(): void;
}

export interface LensExchange {
  response: AskResponse;
  /** Typed text, or null for a spoken question (the transcript is in the response). */
  question: string | null;
}

type Listener = () => void;
type ExchangeListener = (exchange: LensExchange) => void;

const RESTING = new Set(['IDLE', 'NOT_FOUND', 'ERROR']);

export class LensLink {
  private snapshot: LensSnapshot = { connected: false, status: 'Connecting to Even G2...', screen: null, sessionId: null, lensText: '' };
  private commands: LensCommands | null = null;
  private readonly listeners = new Set<Listener>();
  private readonly exchangeListeners = new Set<ExchangeListener>();

  /** Stable between updates, for React's useSyncExternalStore. */
  getSnapshot = (): LensSnapshot => this.snapshot;

  subscribe = (listener: Listener): (() => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };

  update(patch: Partial<LensSnapshot>): void {
    const next = { ...this.snapshot, ...patch };
    if ((Object.keys(next) as (keyof LensSnapshot)[]).every(k => next[k] === this.snapshot[k])) return;
    this.snapshot = next;
    for (const listener of this.listeners) listener();
  }

  attach(commands: LensCommands, sessionId: string): void {
    this.commands = commands;
    this.update({ connected: true, sessionId });
  }

  detach(status: string): void {
    this.commands = null;
    this.update({ connected: false, screen: null, status, lensText: '', graphic_id: undefined, frame: undefined, diagram: undefined });
  }

  /** False when the lens is not connected, busy, or still on the privacy notice. */
  askText(text: string, context: AskContext): boolean {
    return this.commands?.askText(text, context) ?? false;
  }

  canTogglePushToTalk(): boolean {
    const screen = this.snapshot.screen;
    return this.commands !== null && screen !== null && (RESTING.has(screen) || screen === 'LISTENING');
  }

  togglePushToTalk(): void {
    if (this.canTogglePushToTalk()) this.commands?.togglePushToTalk();
  }

  /** Every relay answer the lens receives, spoken or typed. */
  publishExchange(exchange: LensExchange): void {
    for (const listener of this.exchangeListeners) listener(exchange);
  }

  onExchange(listener: ExchangeListener): () => void {
    this.exchangeListeners.add(listener);
    return () => { this.exchangeListeners.delete(listener); };
  }
}

export const lensLink = new LensLink();

// @vitest-environment jsdom
import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { StoreProvider } from '../src/phone/store';
import { GlassesSimulator } from '../src/phone/components/GlassesSimulator';
import { lensLink } from '../src/lens-link';

vi.mock('../src/phone/relay', () => ({ health: async () => ({ ok: true, mock: true }), relayOrigin: '', asRelayError: String }));
afterEach(() => { cleanup(); act(() => lensLink.detach('test')); });

it('mirrors live glasses updates and switches to simulation after disconnect', async () => {
  act(() => {
    lensLink.attach({ askText: () => true, togglePushToTalk: () => {} }, 'live-session');
    lensLink.update({ screen: 'STEP', frame: { header: '2/3', main: 'Torque to 4 N-m', footer: 'nod twice: speak' } });
  });
  render(<StoreProvider><GlassesSimulator /></StoreProvider>);
  expect(screen.getByText('Live from glasses')).toBeTruthy();
  expect(screen.getByRole('img').getAttribute('aria-label')).toContain('Torque to 4 N-m');
  expect(screen.queryByText('Browser simulation')).toBeNull();
  act(() => lensLink.update({ screen: 'LISTENING', frame: { header: 'LISTENING', main: '||||', footer: '' } }));
  expect(screen.getByRole('img').getAttribute('aria-label')).toContain('LISTENING');
  expect(screen.getByRole('img').textContent).not.toContain('Torque');
  act(() => lensLink.detach('Disconnected'));
  expect(screen.getByText('Browser simulation')).toBeTruthy();
  expect(screen.queryByText('Live from glasses')).toBeNull();
});

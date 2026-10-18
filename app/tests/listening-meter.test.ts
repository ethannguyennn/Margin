import { expect, test } from 'vitest';
import { listeningScreen } from '../src/ui/screens';

test('the listening meter moves for speech-level RMS, not only for clipping', () => {
  const bar = (rms: number) => listeningScreen(rms).main[0];
  expect(bar(0)).toBe('▁');
  expect(bar(0.002)).toBe('▁');               // quiet room
  expect(bar(0.03)).not.toBe('▁');            // normal speech used to round to the flattest bar
  expect(bar(0.1) > bar(0.03)).toBe(true);
  expect(bar(1)).toBe('█');
  expect(bar(Number.NaN)).toBe('▁');
});

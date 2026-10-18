import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import fixtures from './sanitize-fixtures.json';
import { G2_ALLOWED_NON_ASCII, sanitizeForG2 } from '../src/ui/glyphs';

describe('sanitizeForG2', () => {
  for (const fixture of fixtures) it(JSON.stringify(fixture.input), () => {
    expect(sanitizeForG2(fixture.input)).toBe(fixture.output);
    expect(sanitizeForG2(fixture.output)).toBe(fixture.output);
  });
  it('has one unique allow-list matching the frozen codepoints', () => {
    expect(new Set(G2_ALLOWED_NON_ASCII).size).toBe(29);
    expect([...G2_ALLOWED_NON_ASCII].map(char => char.codePointAt(0))).toEqual([
      0x25b2,0x25b3,0x25b6,0x25b7,0x25bc,0x25bd,0x25c0,0x25c1,
      0x25cf,0x25cb,0x25a0,0x25a1,0x2605,0x2606,0x2501,0x2500,
      0x2588,0x2587,0x2586,0x2585,0x2584,0x2583,0x2582,0x2581,
      0x256d,0x256e,0x256f,0x2570,0x2502,
    ]);
  });
});

// The relay's list (Part 4) read in place, so the lens and the relay cannot drift apart.
const relayCases = JSON.parse(readFileSync(new URL('../../relay/tests/fixtures/glyph_cases.json', import.meta.url), 'utf8')) as { name: string; in: string; out: string }[];
describe('sanitizeForG2 agrees with the relay sanitizer', () => {
  it('covers the shared 32-case list', () => expect(relayCases.length).toBeGreaterThanOrEqual(32));
  for (const c of relayCases) it(c.name, () => expect(sanitizeForG2(c.in)).toBe(c.out));
});

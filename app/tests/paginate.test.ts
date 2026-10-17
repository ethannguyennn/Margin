import { describe, expect, it } from 'vitest';
import { paginate } from '../src/ui/paginate';

describe('paginate', () => {
  it.each(['', 'short', 'word '.repeat(1000), 'alpha\n\tbeta  gamma', 'a'.repeat(450)])('preserves words and caps pages: %s', text => {
    const pages = paginate(text);
    expect(pages.every(page => page.length <= 450)).toBe(true);
    expect(pages.join(' ').trim()).toBe(text.trim().replace(/\s+/gu, ' '));
  });
  it('breaks only at word boundaries', () => expect(paginate('one two three four', 7)).toEqual(['one two', 'three', 'four']));
  it('accepts exactly the boundary', () => expect(paginate('a'.repeat(450))).toEqual(['a'.repeat(450)]));
  it('refuses an impossible oversized word rather than splitting or truncating', () => expect(() => paginate('a'.repeat(451))).toThrow(RangeError));
  it.each([0, -1, 451, 1.5, NaN])('refuses invalid budget %s', budget => expect(() => paginate('text', budget)).toThrow(RangeError));
});

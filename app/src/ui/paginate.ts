export const MAX_PAGE_CHARS = 450;
// The header/footer leave 184px for body; a conservative budget fits that box.
export const BODY_PAGE_CHARS = 280;

/** Whitespace is normalized; words are never split or silently dropped.
 * A token larger than the budget cannot satisfy both invariants: refuse it.
 */
export function paginate(text: string, budget = MAX_PAGE_CHARS): string[] {
  if (!Number.isInteger(budget) || budget < 1 || budget > MAX_PAGE_CHARS) {
    throw new RangeError('Page budget must be an integer from 1 to 450');
  }
  const words = text.match(/\S+/gu) ?? [];
  const pages: string[] = [];
  let page = '';
  for (const word of words) {
    if (word.length > budget) throw new RangeError('A word exceeds the page budget');
    if (page && page.length + word.length + 1 > budget) {
      pages.push(page);
      page = '';
    }
    page += (page ? ' ' : '') + word;
  }
  if (page || pages.length === 0) pages.push(page);
  return pages;
}

// Keep this single allow-list aligned with README-PART-1-LENS-UI.md section 8.
export const G2_ALLOWED_NON_ASCII = '▲△▶▷▼▽◀◁●○■□★☆━─█▇▆▅▄▃▂▁╭╮╯╰│';

const replacements: Readonly<Record<string, string>> = {
  '§': 'Sec ', '·': '-', '•': '-', '°': ' deg', 'µ': 'u', 'Ω': ' ohm', 'Ω': ' ohm', // Greek omega and the ohm sign
  '–': '-', '—': '-', '“': '"', '”': '"', '‘': "'", '’': "'",
  '×': 'x', '±': '+/-', '≥': '>=', '≤': '<=', '→': '->',
};

export function sanitizeForG2(text: string): string {
  let result = '';
  for (const char of text) {
    if (char in replacements) result += replacements[char];
    else if (char === '\n' || char === '\t' || (char >= ' ' && char <= '~') || G2_ALLOWED_NON_ASCII.includes(char)) result += char;
  }
  return result;
}

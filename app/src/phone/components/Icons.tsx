// Line icons shared by the phone screens. Square caps and mitred joins, to match
// the tab bar and the squared-off controls.
const box = {
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.6,
  strokeLinecap: 'square' as const,
  strokeLinejoin: 'miter' as const,
  'aria-hidden': true,
};

export function ChevronIcon({ size = 16, className }: { size?: number; className?: string }) {
  return (
    <svg {...box} width={size} height={size} className={className}>
      <path d="M9 5l7 7-7 7" />
    </svg>
  );
}

export function CheckIcon({ size = 16 }: { size?: number }) {
  return (
    <svg {...box} width={size} height={size} strokeWidth={2}>
      <path d="M5 12.5l4.5 4.5L19 7.5" />
    </svg>
  );
}

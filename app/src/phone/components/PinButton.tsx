import { toast } from '../toast';
import { CheckIcon } from './Icons';

/** Pins a step as the context the lens asks with; confirms with a toast. */
export function PinButton({ pinned, onPin, wide = false }: { pinned: boolean; onPin: () => void; wide?: boolean }) {
  return (
    <button
      className={`${wide ? 'primary wide' : 'ghost'} with-icon`}
      onClick={() => {
        onPin();
        if (!pinned) toast('Pinned as lens context');
      }}
    >
      {pinned && <CheckIcon />}
      {pinned ? 'Pinned as lens context' : 'Pin as lens context'}
    </button>
  );
}

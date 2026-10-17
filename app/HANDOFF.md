# Part 1 handoff

## Scaffold

- Official ASR template source: even-realities/evenhub-templates,
  commit `8cb01354f5ee914c5fab97d06e6d13b28eeb5815`.
- Frozen contract: `src/types.ts`; Part 2 owns `src/audio`, `src/api`, `src/obs`,
  `src/mock`. Those directories are deliberately absent here.
- `https://margin.example.com` is the user-approved temporary whitelist origin.
  Replace it when Part 3 provides the live origin.
- No direct STT credentials belong in the WebView bundle.
- Tooling is local to `app/`; port 5174 preserves the earlier starter on 5173.

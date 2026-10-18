# SOP accompanying graphics diagnostic

## Root cause

The original corpus contained only Markdown text. There were no reference images,
no section/revision-to-image mapping, no visual-reference field in Gemini's response,
and no native image container or image upload in the lens renderer. Text cards alone
could not identify the equipment, parts or inspection points described by the SOP.
The six-second generation deadline also rejected valid model responses before the
app's eight-second request budget could receive them.

The earlier local startup conflicts were repaired as part of the diagnostic. They
were an additional integration blocker, not the missing visual-reference design.

## Implemented

Five inspected, generated reference illustrations now accompany the synthetic corpus:

- SOP-101: pump body, serial label, mounting bracket, four screws, four washers and carton.
- SOP-114: numbered M5 screw positions, bracket, housing, outlet and a gap detail.
- SOP-120: external wipe surface, installed outlet cap and disconnected power lead.
- SOP-131: wrench handle, ratchet, short adapter and bench-mounted analyzer.
- SOP-140: affected item, attached HOLD tag, quarantine shelf Q2 and blank deviation record.

Images are in `app/src/assets/sops/`. `corpus/illustrations.json` records seven full
or detail views with exact section/revision references and source quotes. The same
bracket drawing supports revisions C and D because it contains no torque setting;
the revision-specific value remains in the cited text. Image generation and targeted
edit prompts are preserved in `corpus/illustration-prompts.json`.

Gemini sees only image IDs supported by retrieved chunks and chooses `graphic_id`.
The deterministic verifier rejects unknown IDs, external URLs, and selections not
supported by a source citation. References are attached to relevant walkthrough
steps without changing the approved procedure order. Older relay responses can
resolve a packaged reference from their citations when `graphic_id` is absent;
an explicit null selection is respected.

The phone answer, walkthrough, SOP browser and live lens mirror render reference
images with accessible descriptions and a synthetic-training caption. The G2 uses
an actual 288x144 image container beside the instruction text. Packaged images are
cropped and rasterized locally to high-contrast Gray8 and uploaded through the SDK.
Instructions paginate at the narrower width; full text and warnings are retained.
The old picture is cleared before new instructions, preventing a failed upload from
leaving the wrong reference alongside a new step. Picture-free screens remove the
image container.

The relay now uses its existing configured generation budget (20 seconds by default)
in both the generator and route guard. The app allows 50 seconds for two generation
attempts plus transcription/retrieval. The local app environment and examples match.
Mock answers and the bracket walkthrough now mirror the actual checked-in corpus,
including the warning not to click the torque wrench twice.

## Evidence

- Offline relay suite: **368 passed, 5 skipped** (optional database integration).
- App suite: **259 passed, 6 skipped** (optional live relay integration).
- Typecheck, production build and Even Hub packaging passed.
- Live Gemini visual-reference selection test: **passed** with the configured budget.
- Separate live questions selected the screw reference for torque and the gap detail
  for feeler-gauge placement; results are under `builds/sop-graphics/`.
- Official Even Hub simulator 0.9.5 / SDK 0.0.16: illustrated answer, both full-text
  detail pages and accompanying phone image rendered with **zero console errors**.
  Native captures and logs are in `builds/sop-graphics/`. Preview PNGs are native
  alpha captures composited on black, following the repository's existing QA method.
- Packaged app: `app/margin.ehpk`, **7,038,758 bytes**, including all five original images.

## Limits and delivery

These are synthetic, not-to-scale reference drawings for fictional equipment.
They identify components and locations; the cited SOP text supplies process limits.
Sections without a relevant catalog reference remain text-only. Real procedures
should use approved equipment photos or drawings in the same mapping.

No database migration is required. The new app can use existing citation responses;
deploy the updated relay to enable explicit Gemini image selection. Production was
not deployed, no commit was made, and physical-glasses legibility/BLE transfer still
needs hardware validation. Google overload can still cause generation failures.
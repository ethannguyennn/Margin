# Accompanying SOP reference images

Official Even Hub simulator 0.9.5, SDK 0.0.16, using mock answers drawn from the
checked-in synthetic HX-2 corpus. Captured on 2026-10-17.

The native glasses captures show the generated screw-position reference beside
the torque glance and both full-text instruction pages. The phone capture shows
the same image with its synthetic-training caption. Native alpha captures are
composited on black using the repository's existing QA method.

The final simulator flow reported zero console errors. These captures do not
establish physical-glasses legibility, BLE transfer performance, or live audio.
The JSON file records separate approved live Gemini selections for torque and
feeler-gauge questions; the full-view screw reference was subsequently refined
into the `bracket-fasteners` close-up, which also passed the live selection test.

Offline verification: relay 368 passed / 5 skipped; app 259 passed / 6 skipped.
Typecheck, production build and packaging passed.

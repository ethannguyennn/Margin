# Corpus figure generator

Source for the 71 SOP figures in `corpus/figures/` (576x288 SVG and PNG, plus the 288x144
4-bit light-on-dark `g2/` render the lens shows). Needs `cairosvg` and Pillow.

```sh
python corpus/figure-src/build.py    # draw every figure (figs_a..figs_d) into corpus/figures/
python corpus/figure-src/figmap.py   # insert any missing "### N.M Diagram - ..." section into its SOP
python app/scripts/bake-lens-graphics.py   # copy the g2 renders into the app's lens assets
```

`figmap.py` skips figures already in their SOP, so re-running it is a no-op. A new figure
also needs a `corpus/illustrations.json` entry anchored to its Diagram section, and its PNG in
`app/src/assets/sops/`.

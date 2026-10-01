# Mobile overflow check

From the repository root, run `node tests/test-mobile-overflow.js`. It checks every
public HTML page at 360 CSS px in both themes and all three languages, including
configuration tabs. The file browser renders at `/distfiles/`. Local fixtures
populate the data tables. Requests to external services receive local responses;
Chrome is skipped when absent. Set `CHROME` to select another executable.

To measure a site copy containing captured production JSON and save screenshots:

```sh
node tests/test-mobile-overflow.js --site /path/to/site \
  --widths 360,390,430,1280 --out /scratch/ssd/mobile-audit/after --screenshots
```

`measurements.json` records page width, overflowing element boxes, internal scroll
regions and title overlap for each case. `--pages mirrors.html` selects one page.
The mirror API uses local `mirror-api.json` when present, with fixtures as a
fallback; `--no-health` disables that fallback to exercise the failure state.

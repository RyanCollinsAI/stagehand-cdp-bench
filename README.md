# stagehand-cdp-bench

A reproducible local browser-automation torture suite comparing brittle CSS-selector Playwright scripts, raw Chrome DevTools Protocol (CDP) + accessibility-tree locators, and Stagehand v4 (`act` / `extract` with typed Zod schemas) on Browserbase.

## Why these 4 torture cases

These are the 4 UI patterns that break production browser automation scripts most often:

1. `01_cross_origin_iframe`: Parent page on `127.0.0.1:<p1>` embedding a true cross-origin `<iframe>` on `localhost:<p2>` with a multi-field form and status output.
2. `02_paginated_spa`: Client-side paginated table (3 pages, 15 rows) with async render delay between clicks.
3. `03_custom_combobox`: Non-native ARIA combobox (`role="combobox"`) whose option list mounts in a portal on `document.body` outside the form tree and selects on `mousedown`.
4. `04_dom_selector_mutation`: Simulates hashed CSS-in-JS hydration churn where `.input-coupon-v1` and `.btn-submit-v1` vanish after 80 ms and are replaced with randomized `sc-*` class names while ARIA labels stay intact.

## Live Measured Results (5 Runs per Task, Local Headless Chromium)

Measured via `python -m cdp_bench.playwright_cdp_runner --runs 5`:

| Task | Strategy | Pass Rate | p50 (ms) | p95 (ms) | Notes |
|---|---|---:|---:|---:|---|
| `01_cross_origin_iframe` | `brittle_css` | 5/5 (100.0%) | 609.1 | 659.8 | ok |
| `01_cross_origin_iframe` | `raw_cdp_a11y` | 5/5 (100.0%) | 612.0 | 615.0 | ok |
| `02_paginated_spa` | `brittle_css` | 5/5 (100.0%) | 733.3 | 754.5 | ok |
| `02_paginated_spa` | `raw_cdp_a11y` | 5/5 (100.0%) | 727.3 | 740.9 | ok |
| `03_custom_combobox` | `brittle_css` | 5/5 (100.0%) | 606.8 | 610.5 | ok |
| `03_custom_combobox` | `raw_cdp_a11y` | 5/5 (100.0%) | 609.2 | 614.2 | ok |
| `04_dom_selector_mutation` | `brittle_css` | 0/5 (0.0%) | 1281.3 | 1286.7 | `Locator.fill: Timeout 600ms exceeded.` |
| `04_dom_selector_mutation` | `raw_cdp_a11y` | 5/5 (100.0%) | 716.1 | 734.9 | ok |

## Two CDP / DX Notes From Running This Daily

1. **Cross-origin iframe attachment over raw CDP is where brittle scripts silently drift:** `Page.getFrameTree` exposes the child frame immediately, but `Runtime.evaluate` on the top execution context cannot cross the origin boundary without attaching a target/execution-context per OOPIF. Semantic frame locators + CDP accessibility trees avoid hardcoding frame indices or brittle DOM paths.
2. **Portal comboboxes fail synthetic `click()` when the listbox listens on `mousedown`:** A huge share of React/Radix/Downshift menus tear down the portal on input `blur` before a synthetic `click` event fires. Checking `Accessibility.getFullAXTree` for `role="option"` and dispatching `mousedown` (or letting Stagehand's CDP action engine handle focus transitions) eliminates the classic "option disappeared mid-click" flake.

## Quickstart

```bash
pip install -e ".[dev]"

# Run tests (boots the 2-origin local server + live Chromium)
pytest -q

# Run the 5-iteration latency and pass-rate benchmark
python -m cdp_bench.playwright_cdp_runner --runs 5
```

### Run Stagehand v4 on Browserbase

```bash
npm install
export BROWSERBASE_API_KEY="your-key"
export BROWSERBASE_PROJECT_ID="your-project-id"
export OPENAI_API_KEY="your-key"
export BENCH_BASE_URL="https://your-reachable-fixture-url"
npm run bench:stagehand
```

The Stagehand runner prints a JSON report containing the same per-task schema plus the clickable Browserbase Session Replay link (`https://browserbase.com/sessions/<id>`).

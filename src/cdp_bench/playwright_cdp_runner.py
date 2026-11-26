"""Live Playwright/CDP benchmark runner comparing brittle CSS selectors vs CDP/a11y locators."""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Callable

from playwright.sync_api import Page, sync_playwright

from .fixtures import FixtureCluster


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, math.ceil((p / 100.0) * len(ordered)) - 1))
    return round(ordered[idx], 1)


# --- Task runners: Brittle CSS-selector baseline (typical hand-written scraper) ---

def _brittle_iframe(page: Page, base: str) -> bool:
    page.goto(f"{base}/01_cross_origin_iframe", wait_until="networkidle")
    frame = page.frame_locator("#vendor-frame")
    frame.locator("#vendor").fill("VND-404")
    frame.locator("#region").fill("Bay Area")
    frame.locator("#frame-submit").click()
    return frame.locator("#frame-result").inner_text() == "ACCEPTED:VND-404:Bay Area"


def _brittle_paginated(page: Page, base: str) -> bool:
    page.goto(f"{base}/02_paginated_spa", wait_until="networkidle")
    seen: list[str] = []
    for idx in range(3):
        page.wait_for_selector("tbody#rows tr[data-row]")
        seen.extend(page.locator("tbody#rows tr[data-row]").all_inner_texts())
        if idx < 2:
            page.locator("#next-btn").click()
            page.wait_for_function(
                f"document.getElementById('page-indicator').textContent === 'Page {idx + 2} of 3'"
            )
    return len(seen) == 15


def _brittle_combobox(page: Page, base: str) -> bool:
    page.goto(f"{base}/03_custom_combobox", wait_until="networkidle")
    page.locator("#env-input").click()
    page.locator("#env-input").fill("San Francisco")
    page.locator("#env-portal li").first.dispatch_event("mousedown")
    page.locator("#apply-btn").click()
    return page.locator("#selected-out").inner_text() == "REGION:us-west-1 (San Francisco)"


def _brittle_dom_mutation(page: Page, base: str) -> bool:
    page.goto(f"{base}/04_dom_selector_mutation", wait_until="networkidle")
    # Wait past hydration mutation: old CSS classes .input-coupon-v1 / .btn-submit-v1 vanish
    page.wait_for_timeout(150)
    page.locator(".input-coupon-v1").fill("SHIP2027", timeout=600)
    page.locator(".btn-submit-v1").click(timeout=600)
    return page.locator("#promo-status").inner_text() == "PROMO:SHIP2027"


# --- Task runners: Resilient CDP + accessibility-tree locators ---

def _cdp_a11y_iframe(page: Page, base: str) -> bool:
    cdp = page.context.new_cdp_session(page)
    cdp.send("Page.enable")
    page.goto(f"{base}/01_cross_origin_iframe", wait_until="networkidle")
    # Inspect frame tree over raw CDP to confirm cross-origin child frame attachment
    tree = cdp.send("Page.getFrameTree")
    assert len(tree["frameTree"].get("childFrames", [])) == 1
    frame = page.frame_locator("iframe[title='Vendor Intake Frame']")
    frame.get_by_label("Vendor Code").fill("VND-404")
    frame.get_by_label("Region").fill("Bay Area")
    frame.get_by_role("button", name="Confirm Intake").click()
    return frame.get_by_role("status").inner_text() == "ACCEPTED:VND-404:Bay Area"


def _cdp_a11y_paginated(page: Page, base: str) -> bool:
    page.goto(f"{base}/02_paginated_spa", wait_until="networkidle")
    cdp = page.context.new_cdp_session(page)
    rows: list[str] = []
    for idx in range(3):
        page.wait_for_selector("tbody tr[data-row]")
        eval_res = cdp.send(
            "Runtime.evaluate",
            {
                "expression": "Array.from(document.querySelectorAll('tbody tr[data-row]')).map(r => r.dataset.row)",
                "returnByValue": True,
            },
        )
        rows.extend(eval_res["result"]["value"])
        if idx < 2:
            page.get_by_role("button", name="Next Page").click()
            page.wait_for_function(
                f"document.getElementById('page-indicator').textContent === 'Page {idx + 2} of 3'"
            )
    return len(rows) == 15 and rows[0] == "SVC-01" and rows[-1] == "SVC-15"


def _cdp_a11y_combobox(page: Page, base: str) -> bool:
    page.goto(f"{base}/03_custom_combobox", wait_until="networkidle")
    combo = page.get_by_role("combobox", name="Target Region")
    combo.click()
    combo.fill("San Francisco")
    page.get_by_role("option", name="us-west-1 (San Francisco)").dispatch_event("mousedown")
    page.get_by_role("button", name="Apply Region").click()
    return page.get_by_role("status").inner_text() == "REGION:us-west-1 (San Francisco)"


def _cdp_a11y_dom_mutation(page: Page, base: str) -> bool:
    page.goto(f"{base}/04_dom_selector_mutation", wait_until="networkidle")
    page.wait_for_timeout(150)
    # Query Accessibility tree via CDP to verify semantic nodes survived CSS class churn
    cdp = page.context.new_cdp_session(page)
    ax = cdp.send("Accessibility.getFullAXTree")
    names = {
        str(node.get("name", {}).get("value", ""))
        for node in ax.get("nodes", [])
        if isinstance(node.get("name"), dict)
    }
    assert "Promo Code" in names and "Apply Promo" in names
    page.get_by_label("Promo Code").fill("SHIP2027")
    page.get_by_role("button", name="Apply Promo").click()
    return page.get_by_role("status").inner_text() == "PROMO:SHIP2027"


TASKS: list[tuple[str, Callable[[Page, str], bool], Callable[[Page, str], bool]]] = [
    ("01_cross_origin_iframe", _brittle_iframe, _cdp_a11y_iframe),
    ("02_paginated_spa", _brittle_paginated, _cdp_a11y_paginated),
    ("03_custom_combobox", _brittle_combobox, _cdp_a11y_combobox),
    ("04_dom_selector_mutation", _brittle_dom_mutation, _cdp_a11y_dom_mutation),
]


def run_benchmark(runs: int = 5) -> list[dict]:
    results: list[dict] = []
    with FixtureCluster() as cluster, sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            for task_id, brittle_fn, cdp_fn in TASKS:
                for strategy, fn in (("brittle_css", brittle_fn), ("raw_cdp_a11y", cdp_fn)):
                    latencies: list[float] = []
                    passed = 0
                    last_error = ""
                    for _ in range(runs):
                        ctx = browser.new_context()
                        page = ctx.new_page()
                        t0 = time.perf_counter()
                        try:
                            ok = bool(fn(page, cluster.base_url))
                            if ok:
                                passed += 1
                            else:
                                last_error = "assertion returned False"
                        except Exception as exc:
                            last_error = str(exc).splitlines()[0][:120]
                        finally:
                            latencies.append((time.perf_counter() - t0) * 1000.0)
                            ctx.close()
                    results.append(
                        {
                            "task": task_id,
                            "strategy": strategy,
                            "runs": runs,
                            "passed": passed,
                            "pass_rate_pct": round((passed / runs) * 100.0, 1),
                            "p50_ms": percentile(latencies, 50),
                            "p95_ms": percentile(latencies, 95),
                            "error": "" if passed == runs else last_error,
                        }
                    )
        finally:
            browser.close()
    return results


def format_markdown(rows: list[dict]) -> str:
    lines = [
        "| Task | Strategy | Pass Rate | p50 (ms) | p95 (ms) | Notes |",
        "|---|---|---:|---:|---:|---|",
    ]
    for r in rows:
        note = r["error"] or "ok"
        lines.append(
            f"| `{r['task']}` | `{r['strategy']}` | {r['passed']}/{r['runs']} ({r['pass_rate_pct']}%) | "
            f"{r['p50_ms']} | {r['p95_ms']} | {note} |"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run local Playwright/CDP browser torture benchmark")
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--out", type=Path, default=Path("artifacts/cdp_bench_results.json"))
    args = ap.parse_args(argv)

    rows = run_benchmark(runs=args.runs)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    print(format_markdown(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

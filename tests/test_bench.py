from __future__ import annotations

from cdp_bench.playwright_cdp_runner import format_markdown, run_benchmark


def test_live_playwright_cdp_benchmark_all_four_fixtures() -> None:
    rows = run_benchmark(runs=2)
    by_key = {(r["task"], r["strategy"]): r for r in rows}

    # Brittle CSS selectors survive static fixtures but break under mid-run class churn
    assert by_key[("01_cross_origin_iframe", "brittle_css")]["passed"] == 2
    assert by_key[("02_paginated_spa", "brittle_css")]["passed"] == 2
    assert by_key[("03_custom_combobox", "brittle_css")]["passed"] == 2
    assert by_key[("04_dom_selector_mutation", "brittle_css")]["passed"] == 0

    # Raw CDP + accessibility-tree locators survive all 4 torture fixtures
    for task in (
        "01_cross_origin_iframe",
        "02_paginated_spa",
        "03_custom_combobox",
        "04_dom_selector_mutation",
    ):
        row = by_key[(task, "raw_cdp_a11y")]
        assert row["passed"] == 2, f"{task} failed under raw_cdp_a11y: {row['error']}"
        assert row["p50_ms"] > 0

    md = format_markdown(rows)
    assert "04_dom_selector_mutation" in md
    assert "raw_cdp_a11y" in md

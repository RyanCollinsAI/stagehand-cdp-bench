/**
 * Stagehand v4 runner executing the exact same 4 torture fixtures against Browserbase
 * (or local Chromium when env="LOCAL") with typed Zod extraction schemas.
 */
import { Stagehand } from "@browserbasehq/stagehand";
import { z } from "zod";

const BASE_URL = (process.env.BENCH_BASE_URL || "http://127.0.0.1:4173").replace(/\/$/, "");
const ENV = process.env.BROWSERBASE_API_KEY ? "BROWSERBASE" : "LOCAL";

async function timed(name, fn) {
  const t0 = performance.now();
  try {
    const ok = await fn();
    return {
      task: name,
      strategy: `stagehand_${ENV.toLowerCase()}`,
      passed: ok ? 1 : 0,
      runs: 1,
      latency_ms: Math.round((performance.now() - t0) * 10) / 10,
      error: ok ? "" : "validation mismatch",
    };
  } catch (err) {
    return {
      task: name,
      strategy: `stagehand_${ENV.toLowerCase()}`,
      passed: 0,
      runs: 1,
      latency_ms: Math.round((performance.now() - t0) * 10) / 10,
      error: String(err?.message || err).slice(0, 140),
    };
  }
}

async function main() {
  const stagehand = new Stagehand({
    env: ENV,
    apiKey: process.env.BROWSERBASE_API_KEY,
    projectId: process.env.BROWSERBASE_PROJECT_ID,
    enableCaching: false,
  });

  await stagehand.init();
  const page = stagehand.page;
  const sessionId = stagehand.browserbaseSessionID || null;
  const results = [];

  try {
    results.push(
      await timed("01_cross_origin_iframe", async () => {
        await page.goto(`${BASE_URL}/01_cross_origin_iframe`, { waitUntil: "networkidle" });
        await page.act("Fill Vendor Code with VND-404 and Region with Bay Area inside the embedded form, then click Confirm Intake");
        const out = await page.extract({
          instruction: "Extract the confirmation status text from the embedded frame",
          schema: z.object({ status: z.string() }),
        });
        return out.status === "ACCEPTED:VND-404:Bay Area";
      })
    );

    results.push(
      await timed("02_paginated_spa", async () => {
        await page.goto(`${BASE_URL}/02_paginated_spa`, { waitUntil: "networkidle" });
        const ids = [];
        for (let i = 0; i < 3; i++) {
          const batch = await page.extract({
            instruction: "Extract all visible service IDs from the table",
            schema: z.object({ ids: z.array(z.string()) }),
          });
          ids.push(...batch.ids);
          if (i < 2) await page.act("Click Next Page");
        }
        return ids.length === 15;
      })
    );

    results.push(
      await timed("03_custom_combobox", async () => {
        await page.goto(`${BASE_URL}/03_custom_combobox`, { waitUntil: "networkidle" });
        await page.act("Type San Francisco into Target Region, select us-west-1 (San Francisco), and click Apply Region");
        const out = await page.extract({
          instruction: "Extract the selected region status text",
          schema: z.object({ status: z.string() }),
        });
        return out.status === "REGION:us-west-1 (San Francisco)";
      })
    );

    results.push(
      await timed("04_dom_selector_mutation", async () => {
        await page.goto(`${BASE_URL}/04_dom_selector_mutation`, { waitUntil: "networkidle" });
        await page.waitForTimeout(150);
        await page.act("Enter SHIP2027 into Promo Code and click Apply Promo");
        const out = await page.extract({
          instruction: "Extract the promo status text",
          schema: z.object({ status: z.string() }),
        });
        return out.status === "PROMO:SHIP2027";
      })
    );
  } finally {
    await stagehand.close();
  }

  console.log(
    JSON.stringify(
      {
        env: ENV,
        replay_url: sessionId ? `https://browserbase.com/sessions/${sessionId}` : null,
        results,
      },
      null,
      2
    )
  );
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});

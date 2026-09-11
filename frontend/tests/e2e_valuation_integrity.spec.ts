import fs from "node:fs";
import path from "node:path";
import { test, expect } from "@playwright/test";

const screenshotDir = path.resolve(__dirname, "../../.scratch/valuation-integrity/screenshots");

test.describe("Fullstack Real Browser E2E Valuation Integrity (No API Mocks)", () => {
  test.beforeAll(async ({ request }) => {
    // Verify fixture backend health and identity before running tests
    const res = await request.get("http://127.0.0.1:18082/e2e/health");
    expect(res.status(), "Backend fixture server must be running on port 18082").toBe(200);
    const health = await res.json();
    expect(health.service).toBe("deterministic-e2e-fixture");
    expect(health.scenarios).toContain("growth");
    expect(health.scenarios).toContain("annual_fallback");
    expect(health.scenarios).toContain("conflict");
  });

  test("full browser workflow: overrides recalculation, real backend DCF scaling, reset, and export", async ({
    page,
  }) => {
    // 1. Navigate to AVGO valuation page
    await page.goto("/valuation/AVGO");
    await expect(page.locator("h1")).toContainText("Broadcom");

    // 2. Verify Statement Basis badge (TTM)
    const stmtBadge = page.locator('[data-testid="statement-basis-badge"]');
    await expect(stmtBadge).toBeVisible();
    await expect(stmtBadge).toContainText("连续 4 季度 (TTM)");

    // 3. Verify Shares Reconciliation badge
    const sharesBadge = page.locator('[data-testid="shares-basis-badge"]');
    await expect(sharesBadge).toBeVisible();
    await expect(sharesBadge).toContainText("股本口径: 单类别普通股核验");

    // 4. Record default DCF price from DOM (calculated by production engine: $21.47)
    const dcfCard = page.locator('.model-card:has(h3:has-text("现金流折现"))');
    await expect(dcfCard).toBeVisible();
    await expect(dcfCard).toContainText("$21.47");

    // The bridge is visible even when some accounting identities are not
    // verifiable; missing evidence must be shown as such rather than passing.
    const bridgeIdentity = page.locator('[data-testid="financial-bridge-identity"]');
    await expect(bridgeIdentity).toBeVisible();
    await expect(bridgeIdentity).toContainText("对账状态");

    // 5. Open Advanced Settings
    const advancedDetails = page.locator('summary:has-text("高级配置")');
    await expect(advancedDetails).toBeVisible();
    await advancedDetails.click();

    // 6. Fill in overrides: growth_cap = 0.80, forecast_horizon = ntm, weight_pe = 0.40
    const growthCapInput = page.locator('label:has-text("DCF 增长率上限") input');
    await growthCapInput.fill("0.80");

    const horizonSelect = page.locator('label:has-text("前瞻预测跨期选择") select');
    await horizonSelect.selectOption("ntm");

    const peWeightInput = page.locator('label:has-text("P/E 权重") input');
    await peWeightInput.fill("0.40");
    const driverCapexInput = page.locator('label:has-text("资本开支 CapEx") input');
    await driverCapexInput.fill("1000000000");

    // 7. Submit override form and observe REAL POST request/response from backend (NO MOCK)
    const [recalcResponse] = await Promise.all([
      page.waitForResponse(
        (res) => res.url().includes("/api/v1/valuation/AVGO") && res.request().method() === "POST"
      ),
      page.locator('button:has-text("应用覆盖并计算")').click(),
    ]);

    expect(recalcResponse.status()).toBe(200);
    const postData = await recalcResponse.json();

    // Verify backend calculated fields
    expect(["0.8", "0.80"]).toContain(postData.growth_cap_effective);
    expect(postData.forecast_horizon_effective).toBe("ntm");
    expect(postData.valuations.dcf.available).toBe(true);
    expect(postData.assumptions_used.driver_capex).toBe("1000000000");

    // Assert that growth_cap=0.80 plus the driver override scaled DCF price
    // higher than default ($21.47 -> $68.46 in this deterministic fixture).
    const recalculatedDcfPrice = postData.valuations.dcf.base.price_per_share;
    expect(parseFloat(recalculatedDcfPrice)).toBeGreaterThan(21.47);
    expect(recalculatedDcfPrice).toBe("68.46");

    // 8. Verify DOM updated with recalculated price
    await expect(dcfCard).toContainText("$68.46");

    // 9. Export Markdown after override and assert downloaded content
    const [downloadOverride] = await Promise.all([
      page.waitForEvent("download"),
      page.locator('[data-testid="export-markdown-btn"]').click(),
    ]);

    const overrideStream = await downloadOverride.createReadStream();
    const overrideChunks: Buffer[] = [];
    for await (const chunk of overrideStream) {
      overrideChunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
    }
    const overrideMd = Buffer.concat(overrideChunks).toString("utf-8");

    expect(overrideMd).toContain("(AVGO) 估值分析报告");
    expect(overrideMd).toContain("**财务报表统计口径**：连续 4 季度 (TTM)");
    expect(overrideMd).toContain("SINGLE_CLASS_VERIFIED");
    expect(overrideMd).toContain("#### 终值敏感性分析矩阵 (3×3 Sensitivity Matrix)");
    expect(overrideMd).toContain("五项会计恒等式状态");
    expect(overrideMd).toContain("68.46");

    // 10. Reset to defaults and observe REAL GET request from backend
    const [resetResponse] = await Promise.all([
      page.waitForResponse(
        (res) => res.url().includes("/api/v1/valuation/AVGO") && res.request().method() === "GET"
      ),
      page.locator('[data-testid="reset-defaults-btn"]').click(),
    ]);

    expect(resetResponse.status()).toBe(200);
    const resetData = await resetResponse.json();
    expect(resetData.valuations.dcf.base.price_per_share).toBe("21.47");

    // Verify DOM restored to default DCF price
    await expect(dcfCard).toContainText("$21.47");
    await expect(driverCapexInput).toHaveValue("");
    await expect(growthCapInput).toHaveValue("");

    // 11. Export Markdown after reset and assert default price is restored
    const [downloadReset] = await Promise.all([
      page.waitForEvent("download"),
      page.locator('[data-testid="export-markdown-btn"]').click(),
    ]);

    const resetStream = await downloadReset.createReadStream();
    const resetChunks: Buffer[] = [];
    for await (const chunk of resetStream) {
      resetChunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
    }
    const resetMd = Buffer.concat(resetChunks).toString("utf-8");
    expect(resetMd).toContain("21.47");

    // Switching tickers starts a fresh request-scoped form and must not carry
    // the previous ticker's override values into the new analysis.
    const [tickerResponse] = await Promise.all([
      page.waitForResponse(
        (res) => res.url().includes("/api/v1/valuation/AAPL") && res.request().method() === "GET"
      ),
      page.getByRole("button", { name: "AAPL", exact: true }).click(),
    ]);
    expect(tickerResponse.status()).toBe(200);
    await expect(page).toHaveURL(/\/valuation\/AAPL$/);
    await expect(page.locator("h1")).toContainText("AAPL");
    await expect(page.locator('label:has-text("资本开支 CapEx") input')).toHaveValue("");
    await expect(page.locator('label:has-text("DCF 增长率上限") input')).toHaveValue("");

    // 12. Capture full-page screenshot
    fs.mkdirSync(screenshotDir, { recursive: true });
    const screenshotPath = path.join(screenshotDir, "e2e_verified.png");
    await page.screenshot({ path: screenshotPath, fullPage: true });
    expect(fs.existsSync(screenshotPath)).toBe(true);
  });

  test("real browser displays ANNUAL_FALLBACK badge on annual fallback ticker (/valuation/ANN)", async ({
    page,
  }) => {
    await page.goto("/valuation/ANN");

    const stmtBadge = page.locator('[data-testid="statement-basis-badge"]');
    await expect(stmtBadge).toBeVisible();
    await expect(stmtBadge).toContainText("年报回退 (ANNUAL_FALLBACK)");

    // Models should still run on annual statement basis
    const peCard = page.locator('.model-card:has(h3:has-text("市盈率"))');
    await expect(peCard).toBeVisible();
    await expect(peCard).toContainText("基准");
  });

  test("real browser displays CONFLICT_DEGRADED warning and degrades DCF on conflict ticker (/valuation/CONF)", async ({
    page,
  }) => {
    await page.goto("/valuation/CONF");

    const sharesBadge = page.locator('[data-testid="shares-basis-badge"]');
    await expect(sharesBadge).toBeVisible();
    await expect(sharesBadge).toContainText("股本冲突 (相关模型不可用)");

    // DCF should be unavailable
    const dcfCard = page.locator('.model-card:has(h3:has-text("现金流折现"))');
    await expect(dcfCard).toBeVisible();
    await expect(dcfCard).toContainText("暂不可用");

    // Forward P/E remains available
    const peCard = page.locator('.model-card:has(h3:has-text("市盈率"))');
    await expect(peCard).toBeVisible();
    await expect(peCard).not.toContainText("暂不可用");
    await expect(peCard).toContainText("基准");
  });
});

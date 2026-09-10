# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: frontend\tests\e2e_valuation_integrity.spec.ts >> Real Browser E2E Valuation Integrity (P0/P1) >> full browser E2E valuation workflow with overrides, recalculation, reset, and markdown export
- Location: frontend\tests\e2e_valuation_integrity.spec.ts:11:7

# Error details

```
Error: page.goto: Protocol error (Page.navigate): Cannot navigate to invalid URL
Call log:
  - navigating to "/valuation/AVGO", waiting until "load"

```

# Test source

```ts
  1   | import fs from "node:fs";
  2   | import path from "node:path";
  3   | import { test, expect } from "@playwright/test";
  4   | import { generateValuationMarkdown } from "../lib/exportMarkdown";
  5   | import type { ValuationResponse } from "../lib/types";
  6   | 
  7   | const jsonPath = path.resolve(__dirname, "../../.scratch/valuation-integrity/independent/avgo_response.json");
  8   | const rawData: ValuationResponse = JSON.parse(fs.readFileSync(jsonPath, "utf-8"));
  9   | 
  10  | test.describe("Real Browser E2E Valuation Integrity (P0/P1)", () => {
  11  |   test("full browser E2E valuation workflow with overrides, recalculation, reset, and markdown export", async ({ page }) => {
  12  |     // 1. Navigate to AVGO valuation page
> 13  |     await page.goto("/valuation/AVGO");
      |                ^ Error: page.goto: Protocol error (Page.navigate): Cannot navigate to invalid URL
  14  |     await expect(page.locator("h1")).toContainText("Broadcom");
  15  | 
  16  |     // 2. Verify Statement Basis badge [P0-B]
  17  |     const stmtBadge = page.locator('[data-testid="statement-basis-badge"]');
  18  |     await expect(stmtBadge).toBeVisible();
  19  |     await expect(stmtBadge).toContainText("连续 4 季度 (TTM)");
  20  | 
  21  |     // 3. Verify Shares Reconciliation badge [P0-A]
  22  |     const sharesBadge = page.locator('[data-testid="shares-basis-badge"]');
  23  |     await expect(sharesBadge).toBeVisible();
  24  |     await expect(sharesBadge).toContainText("股本口径: 全类别普通股穿透");
  25  | 
  26  |     // 4. Open Advanced Settings
  27  |     const advancedDetails = page.locator('summary:has-text("高级配置")');
  28  |     await expect(advancedDetails).toBeVisible();
  29  |     await advancedDetails.click();
  30  | 
  31  |     // 5. Fill in overrides: growth_cap = 0.80, forecast_horizon = ntm, weight_pe = 0.40
  32  |     const growthCapInput = page.locator('label:has-text("DCF 增长率上限") input');
  33  |     await growthCapInput.fill("0.80");
  34  | 
  35  |     const horizonSelect = page.locator('label:has-text("前瞻预测跨期选择") select');
  36  |     await horizonSelect.selectOption("ntm");
  37  | 
  38  |     const peWeightInput = page.locator('label:has-text("P/E 权重") input');
  39  |     await peWeightInput.fill("0.40");
  40  | 
  41  |     // 6. Submit override form and verify POST payload & response via page.waitForResponse
  42  |     const [recalcResponse] = await Promise.all([
  43  |       page.waitForResponse((res) => res.url().includes("/api/v1/valuation/AVGO") && res.request().method() === "POST"),
  44  |       page.locator('button:has-text("应用覆盖并计算")').click(),
  45  |     ]);
  46  | 
  47  |     expect(recalcResponse.status()).toBe(200);
  48  |     const postData = await recalcResponse.json();
  49  |     expect(postData.growth_cap_effective).toBe("0.80");
  50  |     expect(postData.forecast_horizon_effective).toBe("ntm");
  51  |     expect(postData.valuations.dcf.available).toBe(true);
  52  | 
  53  |     // 7. Reset to default and verify GET response
  54  |     const [resetResponse] = await Promise.all([
  55  |       page.waitForResponse((res) => res.url().includes("/api/v1/valuation/AVGO") && res.request().method() === "GET"),
  56  |       page.locator('button:has-text("↺ 重置默认")').click(),
  57  |     ]);
  58  | 
  59  |     expect(resetResponse.status()).toBe(200);
  60  |     const resetData = await resetResponse.json();
  61  |     expect(resetData.growth_cap_effective).toBe("0.40");
  62  | 
  63  |     // 8. Test real Markdown download and inspect downloaded file
  64  |     const [download] = await Promise.all([
  65  |       page.waitForEvent("download"),
  66  |       page.locator('button:has-text("导出 Markdown")').click(),
  67  |     ]);
  68  | 
  69  |     const downloadStream = await download.createReadStream();
  70  |     expect(downloadStream).not.toBeNull();
  71  |     const chunks: Buffer[] = [];
  72  |     if (downloadStream) {
  73  |       for await (const chunk of downloadStream) {
  74  |         chunks.push(typeof chunk === "string" ? Buffer.from(chunk) : chunk);
  75  |       }
  76  |     }
  77  |     const mdContent = Buffer.concat(chunks).toString("utf-8");
  78  | 
  79  |     expect(mdContent).toContain("财务报表统计口径");
  80  |     expect(mdContent).toContain("连续 4 季度 (TTM)");
  81  |     expect(mdContent).toContain("全类别普通股穿透 (ALL_CLASS_RECONCILED)");
  82  |     expect(mdContent).toContain("#### 终值敏感性分析矩阵 (3×3 Sensitivity Matrix)");
  83  |     expect(mdContent).toContain("基准终值占比");
  84  |     expect(mdContent).toContain("模型权重分布");
  85  |     expect(mdContent).toContain("免责声明与使用条款");
  86  | 
  87  |     // 9. Capture screenshot to .scratch/valuation-integrity/screenshots/e2e_verified.png
  88  |     const screenshotDir = path.resolve(__dirname, "../../.scratch/valuation-integrity/screenshots");
  89  |     if (!fs.existsSync(screenshotDir)) {
  90  |       fs.mkdirSync(screenshotDir, { recursive: true });
  91  |     }
  92  |     const screenshotPath = path.join(screenshotDir, "e2e_verified.png");
  93  |     await page.screenshot({ path: screenshotPath, fullPage: true });
  94  |     expect(fs.existsSync(screenshotPath)).toBe(true);
  95  |   });
  96  | 
  97  |   test("browser displays CONFLICT_DEGRADED warning badge and degrades DCF when share conflict occurs", async ({ page }) => {
  98  |     // Intercept valuation API to return CONFLICT_DEGRADED response
  99  |     const conflictData: ValuationResponse = {
  100 |       ...rawData,
  101 |       shares_basis: "CONFLICT_DEGRADED",
  102 |       valuations: {
  103 |         ...rawData.valuations,
  104 |         dcf: {
  105 |           ...rawData.valuations.dcf,
  106 |           available: false,
  107 |           unavailable_reason: "Share capital reconciliation conflict: severe divergence across share classes/sources; model fails closed.",
  108 |         },
  109 |         ev_ebitda: {
  110 |           ...rawData.valuations.ev_ebitda,
  111 |           available: false,
  112 |           unavailable_reason: "Share capital reconciliation conflict",
  113 |         },
```
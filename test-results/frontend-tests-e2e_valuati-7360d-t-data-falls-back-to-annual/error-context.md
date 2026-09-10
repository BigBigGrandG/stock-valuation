# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: frontend\tests\e2e_valuation_integrity.spec.ts >> Real Browser E2E Valuation Integrity (P0/P1) >> browser displays ANNUAL_FALLBACK badge when statement data falls back to annual
- Location: frontend\tests\e2e_valuation_integrity.spec.ts:139:7

# Error details

```
Error: page.goto: Protocol error (Page.navigate): Cannot navigate to invalid URL
Call log:
  - navigating to "/valuation/AVGO", waiting until "load"

```

# Test source

```ts
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
  114 |         fcf_yield: {
  115 |           ...rawData.valuations.fcf_yield,
  116 |           available: false,
  117 |           unavailable_reason: "Share capital reconciliation conflict",
  118 |         },
  119 |       },
  120 |     };
  121 | 
  122 |     await page.route("**/api/v1/valuation/AVGO*", (route) => {
  123 |       route.fulfill({
  124 |         status: 200,
  125 |         contentType: "application/json",
  126 |         body: JSON.stringify(conflictData),
  127 |       });
  128 |     });
  129 | 
  130 |     await page.goto("/valuation/AVGO");
  131 | 
  132 |     // Verify amber badge and exact text
  133 |     const sharesBadge = page.locator('[data-testid="shares-basis-badge"]');
  134 |     await expect(sharesBadge).toBeVisible();
  135 |     await expect(sharesBadge).toContainText("股本冲突 (相关模型不可用)");
  136 |     await expect(sharesBadge).toHaveClass(/bg-amber-500\/20/);
  137 |   });
  138 | 
  139 |   test("browser displays ANNUAL_FALLBACK badge when statement data falls back to annual", async ({ page }) => {
  140 |     const fallbackData: ValuationResponse = {
  141 |       ...rawData,
  142 |       statement_basis: "ANNUAL_FALLBACK",
  143 |       annual_fallback: true,
  144 |     };
  145 | 
  146 |     await page.route("**/api/v1/valuation/AVGO*", (route) => {
  147 |       route.fulfill({
  148 |         status: 200,
  149 |         contentType: "application/json",
  150 |         body: JSON.stringify(fallbackData),
  151 |       });
  152 |     });
  153 | 
> 154 |     await page.goto("/valuation/AVGO");
      |                ^ Error: page.goto: Protocol error (Page.navigate): Cannot navigate to invalid URL
  155 | 
  156 |     const stmtBadge = page.locator('[data-testid="statement-basis-badge"]');
  157 |     await expect(stmtBadge).toBeVisible();
  158 |     await expect(stmtBadge).toContainText("年报回退 (ANNUAL_FALLBACK)");
  159 |     await expect(stmtBadge).toHaveClass(/bg-amber-500\/20/);
  160 |   });
  161 | });
  162 | 
  163 | test.describe("Markdown Generation Contract Unit Checks", () => {
  164 |   test("exported Markdown includes statement basis, shares basis, model weights, and 3x3 sensitivity matrix", () => {
  165 |     const md = generateValuationMarkdown(rawData);
  166 | 
  167 |     expect(md).toContain("财务报表统计口径");
  168 |     expect(md).toContain("连续 4 季度 (TTM)");
  169 |     expect(md).toContain("总股本口径");
  170 |     expect(md).toContain("全类别普通股穿透 (ALL_CLASS_RECONCILED)");
  171 |     expect(md).toContain("#### 终值敏感性分析矩阵 (3×3 Sensitivity Matrix)");
  172 |     expect(md).toContain("基准终值占比");
  173 |     expect(md).toContain("WACC \\ g");
  174 |     expect(md).toContain("模型权重分布");
  175 |   });
  176 | 
  177 |   test("exported Markdown reflects CONFLICT_DEGRADED without claiming reconciled", () => {
  178 |     const degradedResponse: ValuationResponse = {
  179 |       ...rawData,
  180 |       shares_basis: "CONFLICT_DEGRADED",
  181 |     };
  182 |     const md = generateValuationMarkdown(degradedResponse);
  183 |     expect(md).toContain("股本冲突，相关模型不可用 (CONFLICT_DEGRADED)");
  184 |     expect(md).not.toContain("全类别普通股穿透 (CONFLICT_DEGRADED)");
  185 |   });
  186 | });
  187 | 
```
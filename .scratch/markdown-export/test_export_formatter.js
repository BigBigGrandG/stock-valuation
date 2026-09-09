import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const {
  generateValuationMarkdown,
  buildExportFilename,
  escapeTableCell,
  formatMetricProvenance,
} = require("./dist-cjs/exportMarkdown.js");

console.log("=== Running Markdown Export Formatter Test Suite ===");

// 1. Test escapeTableCell & escapeMarkdownText
console.log("\n[Test 1] escapeTableCell & escapeMarkdownText helpers (pipes, newlines, backticks)");
assert.equal(escapeTableCell("foo|bar"), "foo\\|bar");
assert.equal(escapeTableCell("foo\nbar\r\nbaz"), "foo bar baz");
assert.equal(escapeTableCell("foo | bar\nqux"), "foo \\| bar qux");
assert.equal(escapeTableCell("foo`bar`"), "foo\\`bar\\`");
assert.equal(escapeTableCell("foo | bar`baz\nqux"), "foo \\| bar\\`baz qux");
assert.equal(escapeTableCell(null), "—");
assert.equal(escapeTableCell(undefined), "—");
assert.equal(escapeTableCell(""), "—");
assert.equal(escapeTableCell("   "), "—");
console.log("✓ escapeTableCell and backtick escaping passed");

// 2. Test buildExportFilename
console.log("\n[Test 2] buildExportFilename helper");
const fixedDate = new Date("2026-09-10T15:30:45Z");
const fn1 = buildExportFilename("NVDA", fixedDate);
assert.match(fn1, /^NVDA_valuation_\d{8}_\d{6}\.md$/);
const fn2 = buildExportFilename("brk.b", fixedDate);
assert.match(fn2, /^BRK\.B_valuation_\d{8}_\d{6}\.md$/);
const fn3 = buildExportFilename("test/foo$bar", fixedDate);
assert.doesNotMatch(fn3, /[/$]/);
console.log(`✓ buildExportFilename passed (${fn1}, ${fn2})`);

// 3. Test formatMetricProvenance
console.log("\n[Test 3] formatMetricProvenance helper");
const metricMock = {
  value: "100.5",
  unit: "USD",
  period: "FY2025",
  source: "SEC 10-K",
  source_type: "actual",
  as_of: "2025-12-31",
  confidence: 0.95,
  is_estimated: false,
};
const prov = formatMetricProvenance(metricMock);
assert.ok(prov.includes("USD"));
assert.ok(prov.includes("FY2025"));
assert.ok(prov.includes("SEC 10-K"));
assert.ok(prov.includes("实际"));
assert.ok(prov.includes("实际数据"));
assert.ok(prov.includes("置信度 95.00%"));
console.log("✓ formatMetricProvenance passed");

// Helper to validate Markdown table row column counts
function validateMarkdownTables(markdown) {
  const lines = markdown.split("\n");
  let inTable = false;
  let expectedCols = 0;
  let tableHeaderLine = 0;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    if (line.startsWith("|") && line.endsWith("|")) {
      // Count unescaped pipes
      const pipeCount = (line.match(/(?<!\\)\|/g) || []).length;
      const cols = pipeCount - 1;

      if (!inTable) {
        inTable = true;
        expectedCols = cols;
        tableHeaderLine = i + 1;
      } else if (line.match(/^\|(?:\s*:?---+:?\s*\|)+$/)) {
        // Delimiter line
        assert.equal(
          cols,
          expectedCols,
          `Table delimiter at line ${i + 1} has ${cols} cols, expected ${expectedCols}`
        );
      } else {
        // Data row
        assert.equal(
          cols,
          expectedCols,
          `Table data row at line ${i + 1} (table starting at ${tableHeaderLine}) has ${cols} cols, expected ${expectedCols}. Line: ${line}`
        );
      }
    } else {
      inTable = false;
    }
  }
}

// 4. Test live/actual NVDA valuation response
console.log("\n[Test 4] Formatter on NVDA (all 4 models active)");
const nvdaRaw = await fetch("http://127.0.0.1:8002/api/v1/valuation/NVDA").then((r) => r.json());
const nvdaMd = generateValuationMarkdown(nvdaRaw, { exportTime: new Date("2026-09-10T12:00:00Z") });

// Assert metadata
assert.ok(nvdaMd.includes("# NVIDIA Corporation (NVDA) 估值分析报告"));
assert.ok(nvdaMd.includes("- **股票代码**：NVDA"));
assert.ok(nvdaMd.includes("- **报价币种**：USD"));
assert.ok(nvdaMd.includes("- **市场参考价**："));
assert.ok(nvdaMd.includes("- **财报基准日**："));
assert.ok(nvdaMd.includes("- **数据源提供方**："));
assert.ok(nvdaMd.includes("- **数据模式**：LIVE 真实市场与财务数据"));
assert.ok(nvdaMd.includes("- **数据质量评级**："));
assert.ok(nvdaMd.includes("- **报告导出时间**："));

// Assert composite valuation
assert.ok(nvdaMd.includes("## 一、综合估值结论"));
assert.ok(nvdaMd.includes("综合公允价值区间"));
assert.ok(nvdaMd.includes("估值判断"));
assert.ok(nvdaMd.includes("安全边际 (MOS)"));
assert.ok(nvdaMd.includes("预期上行 / 下跌空间"));
assert.ok(nvdaMd.includes("有效模型数量"));
assert.ok(nvdaMd.includes("4 / 4"));
assert.ok(nvdaMd.includes("FCF Yield = FCFE · DCF = FCFF"));
assert.ok(nvdaMd.includes("#### 模型权重分布"));
assert.ok(nvdaMd.includes("#### 综合计算推导过程"));

// Assert assumptions
assert.ok(nvdaMd.includes("## 二、估值假设与情景参数"));
assert.ok(nvdaMd.includes("前瞻市盈率 (P/E Multiple)"));
assert.ok(nvdaMd.includes("EV / EBITDA 倍数"));
assert.ok(nvdaMd.includes("FCF 目标收益率 (FCF Yield)"));
assert.ok(nvdaMd.includes("DCF 加权资本成本 (WACC)"));
assert.ok(nvdaMd.includes("DCF 永续增长率 (Terminal Growth)"));
assert.ok(nvdaMd.includes("生效状态"));
assert.ok(nvdaMd.includes("系统默认基准") || nvdaMd.includes("用户覆盖生效"));

// Assert all four models & scenario intermediates
assert.ok(nvdaMd.includes("### 3.1 市盈率估值 (forward_pe)"));
assert.ok(nvdaMd.includes("### 3.2 EV / EBITDA 估值 (ev_ebitda)"));
assert.ok(nvdaMd.includes("### 3.3 FCF 收益率估值 (fcf_yield)"));
assert.ok(nvdaMd.includes("### 3.4 现金流折现（DCF） (dcf)"));
assert.ok(nvdaMd.includes("核心计算中间值 (Intermediates)"));
assert.ok(nvdaMd.includes("前瞻 EPS:"));
assert.ok(nvdaMd.includes("目标 P/E:"));
assert.ok(nvdaMd.includes("EV:"));
assert.ok(nvdaMd.includes("股权价值:"));

// Assert DCF 3 scenarios
assert.ok(nvdaMd.includes("#### DCF 五年现金流预测与折现拆解（悲观 / 基准 / 乐观）"));
assert.ok(nvdaMd.includes("##### 【悲观情景】"));
assert.ok(nvdaMd.includes("##### 【基准情景】"));
assert.ok(nvdaMd.includes("##### 【乐观情景】"));
assert.ok(nvdaMd.includes("企业价值至股权价值桥梁"));
assert.ok(nvdaMd.includes("五年 FCFF 预测与折现明细"));
assert.ok(nvdaMd.includes("企业价值 (Enterprise Value, EV)"));
assert.ok(nvdaMd.includes("终端价值 (Terminal Value, TV)"));
assert.ok(nvdaMd.includes("终端价值现值 (PV of TV)"));
assert.ok(nvdaMd.includes("股权价值 (Equity Value)"));
assert.ok(nvdaMd.includes("每股公允价值"));

// Assert disclaimer
assert.ok(nvdaMd.includes("## 四、免责声明与使用条款"));
assert.ok(nvdaMd.includes("不构成任何投资建议、买卖要约或财务咨询"));

// Validate table layout
validateMarkdownTables(nvdaMd);
console.log("✓ NVDA export verification, intermediates, and table layout passed");

// 5. Test TSM (ADR with currency isolation and unavailable models)
console.log("\n[Test 5] Formatter on TSM (ADR with unavailable models)");
const tsmRaw = await fetch("http://127.0.0.1:8002/api/v1/valuation/TSM").then((r) => r.json());
const tsmMd = generateValuationMarkdown(tsmRaw, { exportTime: new Date("2026-09-10T12:00:00Z") });

assert.ok(tsmMd.includes(tsmRaw.company_name));
assert.ok(tsmMd.includes("(TSM)"));
assert.ok(tsmMd.includes("### 3.1 市盈率估值 (forward_pe)"));
assert.ok(tsmMd.includes("✅ 可用"));
assert.ok(tsmMd.includes("### 3.2 EV / EBITDA 估值 (ev_ebitda)"));
assert.ok(tsmMd.includes("❌ 不可用"));
assert.ok(tsmMd.includes("Currency mismatch: quote currency (USD) differs from statement reporting currency (TWD)"));
assert.ok(tsmMd.includes("### 3.3 FCF 收益率估值 (fcf_yield)"));
assert.ok(tsmMd.includes("❌ 不可用"));
assert.ok(tsmMd.includes("### 3.4 现金流折现（DCF） (dcf)"));
assert.ok(tsmMd.includes("❌ 不可用"));

// Composite shows 1 / 4 models
assert.ok(tsmMd.includes("1 / 4"));
assert.ok(tsmMd.includes("市盈率估值"));

validateMarkdownTables(tsmMd);
console.log("✓ TSM unavailable model verification passed");

// 6. Test Demo data (AVGO offline fixture)
console.log("\n[Test 6] Formatter on AVGO demo data");
const avgoRaw = await fetch("http://127.0.0.1:8002/api/v1/valuation/AVGO").then((r) => r.json());
const avgoMd = generateValuationMarkdown(avgoRaw, { exportTime: new Date("2026-09-10T12:00:00Z") });
if (avgoRaw.is_demo) {
  assert.ok(avgoMd.includes("DEMO 固定演示数据"));
}
validateMarkdownTables(avgoMd);
console.log("✓ AVGO export verification passed");

// 7. Test Table Escaping with malicious / edge inputs (pipes, newlines, backticks)
console.log("\n[Test 7] Table and prose escaping with pipes, newlines, and backticks");
const edgeData = JSON.parse(JSON.stringify(nvdaRaw));
edgeData.company_name = "Edge `Corp` | With Pipes | And \n Newlines";
edgeData.valuations.forward_pe.formula_description = "Formula `inline_code` | with | pipe\nand newline";
edgeData.valuations.forward_pe.inputs.forward_eps_source = "Yahoo `API` | Finance\r\nSEC 10-K";
if (edgeData.valuations.forward_pe.input_metrics?.diluted_shares) {
  edgeData.valuations.forward_pe.input_metrics.diluted_shares.notes = "Shares `count` | notes | line1\nline2";
}

const edgeMd = generateValuationMarkdown(edgeData);
validateMarkdownTables(edgeMd);
assert.ok(!edgeMd.includes("Edge `Corp`"), "Backticks in company name should be escaped");
assert.ok(edgeMd.includes("Edge \\`Corp\\`"), "Backticks in company name should be escaped to \\`");
console.log("✓ Edge case table escaping (pipes, newlines, backticks) passed without table distortion");

// Save sample output for evidence (save to BOTH .scratch/markdown-export and .scratch/markdown-export/evidence)
const evidenceDir = path.join(process.cwd(), ".scratch", "markdown-export", "evidence");
if (!fs.existsSync(evidenceDir)) {
  fs.mkdirSync(evidenceDir, { recursive: true });
}

fs.writeFileSync(path.join(process.cwd(), ".scratch", "markdown-export", "sample_nvda_export.md"), nvdaMd, "utf-8");
fs.writeFileSync(path.join(process.cwd(), ".scratch", "markdown-export", "sample_tsm_export.md"), tsmMd, "utf-8");
fs.writeFileSync(path.join(evidenceDir, "sample_nvda_export.md"), nvdaMd, "utf-8");
fs.writeFileSync(path.join(evidenceDir, "sample_tsm_export.md"), tsmMd, "utf-8");

console.log("✓ Saved sample exports to both .scratch/markdown-export/ and .scratch/markdown-export/evidence/");

console.log("\n=== All Formatter Tests Passed Successfully! ===");

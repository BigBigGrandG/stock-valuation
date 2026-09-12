import fs from "node:fs";
import path from "node:path";
import { test, expect } from "@playwright/test";
import { generateValuationMarkdown } from "../lib/exportMarkdown";
import type { ValuationResponse } from "../lib/types";

const fixturePath = path.resolve(__dirname, "./fixtures/contract_avgo_response.json");
const rawData: ValuationResponse = JSON.parse(fs.readFileSync(fixturePath, "utf-8"));

test.describe("Frontend Contract: Markdown Export Format", () => {
  test("exported Markdown includes independent model output and 3x3 sensitivity matrix", () => {
    const md = generateValuationMarkdown(rawData);

    // Section headers
    expect(md).toContain("(AVGO) 估值分析报告");
    expect(md).toContain("## 一、估值假设与情景参数");
    expect(md).toContain("## 二、四套独立估值模型明细");
    expect(md).toContain("## 三、免责声明与使用条款");

    // Statement basis
    expect(md).toContain("**财务报表统计口径**：连续 4 季度 (TTM)");

    // Shares basis
    expect(md).toContain("**总股本口径**");

    // Composite output and weight semantics must not leak into exports.
    expect(md).not.toContain("综合估值");
    expect(md).not.toContain("综合公允价值");
    expect(md).not.toContain("模型权重分布");
    expect(md).not.toContain("effective_weights");

    for (const key of ["forward_pe", "ev_ebitda", "fcf_yield", "dcf"]) {
      expect(md).toContain(`(${key})`);
    }

    // Sensitivity matrix
    expect(md).toContain("#### 终值敏感性分析矩阵 (3×3 Sensitivity Matrix)");
    expect(md).toContain("| WACC \\ g |");
  });

  test("exported Markdown reflects CONFLICT_DEGRADED without claiming reconciled", () => {
    const degradedData: ValuationResponse = {
      ...rawData,
      shares_basis: "CONFLICT_DEGRADED",
      statement_basis: "ANNUAL_FALLBACK",
      annual_fallback: true,
      valuations: {
        ...rawData.valuations,
        dcf: {
          ...rawData.valuations.dcf,
          available: false,
          base: undefined,
        },
      },
    };

    const md = generateValuationMarkdown(degradedData);
    expect(md).toContain("年报回退 (ANNUAL_FALLBACK)");
    expect(md).toContain("股本冲突，相关模型不可用 (CONFLICT_DEGRADED)");
    expect(md).not.toContain("全类别普通股穿透");
  });

  test("exported Markdown preserves FCFF/FCFE reconciliation and identity evidence", () => {
    const bridgeData: ValuationResponse = {
      ...rawData,
      financial_bridge: {
        period: "ntm",
        forecast_start_date: "2026-09-10",
        forecast_end_date: "2027-09-10",
        as_of: "2026-09-10",
        currency: "USD",
        revenue: "1000",
        ebitda: "200",
        da: "20",
        ebit: "180",
        tax_rate: "0.2",
        nopat: "144",
        capex: "50",
        nwc_change: "10",
        fcff: "900",
        bridge_fcff: "840",
        fcfe: "1234",
        bridge_fcfe: "800",
        interest: "20",
        after_tax_interest: "16",
        net_borrowing: "5",
        identity_holds: false,
        identity_checks: { ebitda: true, ebit: true, nopat: true, fcff: false, fcfe: false },
        fcff_identity_holds: false,
        fcfe_identity_holds: false,
        reconciliation_difference: "60",
        fcfe_reconciliation_difference: "434",
        dcf_forecasts: [{
          year: 1,
          value: "840",
          period: "FY2027E",
          as_of: "2026-09-10",
          source_type: "derived",
          start_date: "2027-01-01",
          end_date: "2027-12-31",
        }],
      },
    };

    const md = generateValuationMarkdown(bridgeData);
    expect(md).toContain("五项会计恒等式状态");
    expect(md).toContain("FCFF 对账差额");
    expect(md).toContain("FCFE 对账差额");
    expect(md).toContain("DCF 显式年度预测证据");
    expect(md).toContain("2027-01-01");
    expect(md).toContain("2027-12-31");
  });
});

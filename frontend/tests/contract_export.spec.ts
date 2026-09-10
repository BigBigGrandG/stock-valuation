import fs from "node:fs";
import path from "node:path";
import { test, expect } from "@playwright/test";
import { generateValuationMarkdown } from "../lib/exportMarkdown";
import type { ValuationResponse } from "../lib/types";

const fixturePath = path.resolve(__dirname, "./fixtures/contract_avgo_response.json");
const rawData: ValuationResponse = JSON.parse(fs.readFileSync(fixturePath, "utf-8"));

test.describe("Frontend Contract: Markdown Export Format", () => {
  test("exported Markdown includes statement basis, shares basis, model weights, and 3x3 sensitivity matrix", () => {
    const md = generateValuationMarkdown(rawData);

    // Section headers
    expect(md).toContain("(AVGO) 估值分析报告");
    expect(md).toContain("## 一、综合估值结论");
    expect(md).toContain("## 二、估值假设与情景参数");
    expect(md).toContain("## 三、四套独立估值模型明细");
    expect(md).toContain("## 四、免责声明与使用条款");

    // Statement basis
    expect(md).toContain("**财务报表统计口径**：连续 4 季度 (TTM)");

    // Shares basis
    expect(md).toContain("**总股本口径**");

    // Model weights
    expect(md).toContain("#### 模型权重分布");
    expect(md).toContain("| 模型 | 键值 | 综合权重 | 状态 |");

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
          fair_value_base: undefined,
          base: undefined,
        },
      },
    };

    const md = generateValuationMarkdown(degradedData);
    expect(md).toContain("年报回退 (ANNUAL_FALLBACK)");
    expect(md).toContain("股本冲突，相关模型不可用 (CONFLICT_DEGRADED)");
    expect(md).not.toContain("全类别普通股穿透");
  });
});

import fs from "node:fs";
import assert from "node:assert";
import { generateValuationMarkdown } from "../../../frontend/lib/exportMarkdown.ts";

const rawData = JSON.parse(fs.readFileSync(".scratch/valuation-integrity/independent/avgo_response.json", "utf-8"));
const md = generateValuationMarkdown(rawData);

console.log("=== EXPORTED MARKDOWN AUDIT ===");
console.log("Length of markdown:", md.length);

assert(md.includes("财务报表统计口径"), "Exported Markdown must include 财务报表统计口径");
assert(md.includes("总股本口径"), "Exported Markdown must include 总股本口径");
assert(md.includes("全类别普通股穿透 (ALL_CLASS_RECONCILED)"), "Exported Markdown must include 全类别普通股穿透");
assert(md.includes("终值敏感性分析矩阵 (3×3 Sensitivity Matrix)"), "Exported Markdown must include 终值敏感性分析矩阵");
assert(md.includes("模型权重分布"), "Exported Markdown must include 模型权重分布");

// Test CONFLICT_DEGRADED formatting
const conflictData = { ...rawData, shares_basis: "CONFLICT_DEGRADED" };
const mdConflict = generateValuationMarkdown(conflictData);
assert(mdConflict.includes("股本冲突，相关模型不可用 (CONFLICT_DEGRADED)"), "Must correctly format CONFLICT_DEGRADED");
assert(!mdConflict.includes("全类别普通股穿透 (CONFLICT_DEGRADED)"), "Must not claim 全类别普通股穿透 on CONFLICT_DEGRADED");

// Test ANNUAL_FALLBACK formatting
const fallbackData = { ...rawData, statement_basis: "ANNUAL_FALLBACK", annual_fallback: true };
const mdFallback = generateValuationMarkdown(fallbackData);
assert(mdFallback.includes("年报回退 (ANNUAL_FALLBACK)"), "Must correctly format ANNUAL_FALLBACK");

fs.writeFileSync(".scratch/valuation-integrity/independent/exported_report.md", md, "utf-8");
console.log("ALL ITEM 7 EXPORT CHECKS AND ASSERTIONS PASSED!");

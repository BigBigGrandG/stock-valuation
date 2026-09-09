// Display helpers only. Valuation calculations are performed by the backend.

import type { DecimalLike, FinancialMetric } from "./types";

function numeric(value: unknown): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

export function fmtNumber(value: unknown, decimals = 2): string {
  const n = numeric(value);
  if (n === null) return "—";
  return n.toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

export function fmtBigNumber(value: unknown, currency = "$"): string {
  const n = numeric(value);
  if (n === null) return "—";
  const abs = Math.abs(n);
  if (abs >= 1e12) return `${currency}${(n / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `${currency}${(n / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${currency}${(n / 1e6).toFixed(2)}M`;
  return `${currency}${fmtNumber(n)}`;
}

export function fmtPct(value: unknown, decimals = 2): string {
  const n = numeric(value);
  if (n === null) return "—";
  return `${(n * 100).toFixed(decimals)}%`;
}

export function fmtPctSigned(value: unknown, decimals = 2): string {
  const n = numeric(value);
  if (n === null) return "—";
  const pct = (n * 100).toFixed(decimals);
  return n >= 0 ? `+${pct}%` : `${pct}%`;
}

export function fmtShares(value: unknown): string {
  const n = numeric(value);
  if (n === null) return "—";
  if (n >= 1e9) return `${(n / 1e9).toFixed(3)}B`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  return n.toLocaleString("en-US");
}

export function fmtPrice(value: unknown, currency = "$"): string {
  const n = numeric(value);
  if (n === null) return "—";
  return `${currency}${fmtNumber(n, 2)}`;
}

export function fmtDate(value: unknown): string {
  if (typeof value !== "string" || !value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
}

export function fmtDateTime(value: unknown): string {
  if (typeof value !== "string" || !value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  if (/^\d{4}-\d{2}-\d{2}$/.test(value.trim())) {
    return parsed.toLocaleDateString("zh-CN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    });
  }
  return parsed.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

export function pctColor(value: unknown): string {
  const n = numeric(value);
  if (n === null || n === 0) return "muted";
  return n > 0 ? "positive" : "negative";
}

export function qualityClass(quality: string | undefined): string {
  switch (quality) {
    case "HIGH":
      return "quality-high";
    case "MEDIUM":
      return "quality-medium";
    case "LOW":
      return "quality-low";
    default:
      return "quality-unknown";
  }
}

export const CLASSIFICATION_COLORS: Record<string, string> = {
  significantly_undervalued: "classification-strong-positive",
  undervalued: "classification-positive",
  slightly_undervalued: "classification-soft-positive",
  fairly_valued: "classification-neutral",
  overvalued: "classification-warning",
  significantly_overvalued: "classification-negative",
};

export const CLASSIFICATION_ZH: Record<string, string> = {
  significantly_undervalued: "严重低估",
  undervalued: "低估",
  slightly_undervalued: "略微低估",
  fairly_valued: "估值合理",
  overvalued: "高估",
  significantly_overvalued: "严重高估",
};

export function isFinancialMetric(value: unknown): value is FinancialMetric {
  if (!value || typeof value !== "object") return false;
  const record = value as Record<string, unknown>;
  return "value" in record && "unit" in record && "source" in record;
}

export function metricValue(metric: FinancialMetric | undefined): DecimalLike | undefined {
  return metric?.value;
}

export function displayMetricValue(
  value: unknown,
  key = "",
  unit = "",
): string {
  const metric = isFinancialMetric(value) ? value : undefined;
  const raw = metric ? metric.value : value;
  const lower = `${key} ${unit}`.toLowerCase();
  if (
    lower.includes("yield") ||
    lower.includes("wacc") ||
    lower.includes("growth") ||
    lower.includes("terminal") ||
    lower.includes("upside") ||
    lower.includes("premium") ||
    lower.includes("margin")
  ) {
    return fmtPct(raw);
  }
  if (lower.includes("price") || lower.includes("per_share")) {
    return fmtPrice(raw);
  }
  if (lower.includes("shares")) return fmtShares(raw);
  if (unit.toLowerCase().includes("usd") && !unit.toLowerCase().includes("/share")) {
    return fmtBigNumber(raw);
  }
  return fmtNumber(raw);
}


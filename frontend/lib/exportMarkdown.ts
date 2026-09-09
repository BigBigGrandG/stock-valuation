import {
  CLASSIFICATION_LABELS_ZH,
  DATA_QUALITY_LABELS_ZH,
  MODEL_LABELS_ZH,
  type FinancialMetric,
  type ModelValuation,
  type DCFScenario,
  type ValuationResponse,
} from "./types";
import {
  CLASSIFICATION_ZH,
  displayMetricValue,
  fmtBigNumber,
  fmtDate,
  fmtDateTime,
  fmtNumber,
  fmtPct,
  fmtPctSigned,
  fmtPrice,
  fmtShares,
  isFinancialMetric,
} from "./format";

export const FIELD_LABELS: Record<string, string> = {
  forward_eps: "前瞻 EPS",
  forward_ebitda: "前瞻 EBITDA",
  forward_fcfe: "前瞻 FCFE",
  forward_fcff: "前瞻 FCFF",
  fcff_y1: "FCFF 第一年",
  fcff_y2: "FCFF 第二年",
  current_price: "当前股价",
  diluted_shares: "稀释股数",
  cash: "现金",
  total_debt: "总债务",
  net_debt: "净负债",
  market_cap: "市值",
  historical_forward_pe: "历史前瞻 P/E",
  historical_ev_ebitda: "历史 EV/EBITDA",
  pe_multiple_low: "P/E 低位",
  pe_multiple_base: "P/E 基准",
  pe_multiple_high: "P/E 高位",
  multiple_low: "倍数低位",
  multiple_base: "倍数基准",
  multiple_high: "倍数高位",
  yield_low: "收益率低位情景",
  yield_base: "收益率基准",
  yield_high: "收益率高位情景",
  wacc_bear: "WACC 悲观",
  wacc_base: "WACC 基准",
  wacc_bull: "WACC 乐观",
  terminal_growth_bear: "永续增长悲观",
  terminal_growth_base: "永续增长基准",
  terminal_growth_bull: "永续增长乐观",
  growth_bear: "预测增长悲观",
  growth_base: "预测增长基准",
  growth_bull: "预测增长乐观",
  growth_rate: "预测增长率",
  pe_source: "P/E 来源",
  source: "来源",
  source_label: "来源说明",
  wacc_source: "WACC 来源",
  wacc_source_label: "WACC 来源说明",
  growth_source: "增长来源",
  growth_source_type: "增长来源类型",
  fcf_type: "现金流定义",
  n_years: "预测年数",
  terminal_growth_max: "永续增长上限",
};

export const SOURCE_LABELS: Record<string, string> = {
  actual: "实际数据",
  analyst_estimate: "分析师估计",
  derived: "派生值",
  configured_fallback: "配置回退",
  user_override: "用户覆盖",
  fixture: "固定演示数据",
};

export const SCENARIO_NAMES_ZH: Record<string, string> = {
  bear: "悲观情景",
  base: "基准情景",
  bull: "乐观情景",
};

export function labelForKey(key: string): string {
  return FIELD_LABELS[key] ?? key.replaceAll("_", " ");
}

export function asText(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") {
    try {
      return JSON.stringify(value);
    } catch {
      return "—";
    }
  }
  return String(value);
}

/**
 * Escapes characters that break Markdown syntax in inline prose / headings (\, `, and newlines).
 */
export function escapeMarkdownText(value: unknown): string {
  if (value === null || value === undefined) return "—";
  const str = String(value).trim();
  if (!str) return "—";
  return str
    .replace(/\\/g, "\\\\")
    .replace(/`/g, "\\`")
    .replace(/\r?\n/g, " ");
}

/**
 * Escapes characters that break Markdown table rendering (\, |, `, and newlines).
 */
export function escapeTableCell(value: unknown): string {
  if (value === null || value === undefined) return "—";
  const str = String(value).trim();
  if (!str) return "—";
  return str
    .replace(/\\/g, "\\\\")
    .replace(/\|/g, "\\|")
    .replace(/`/g, "\\`")
    .replace(/\r?\n/g, " ");
}

export function formatScenarioIntermediates(
  modelKey: string,
  intermediates: Record<string, unknown> | undefined,
  currencySymbol = "$",
): string {
  if (!intermediates || Object.keys(intermediates).length === 0) return "—";
  const parts: string[] = [];

  if (modelKey === "forward_pe") {
    if (intermediates.forward_eps !== undefined) {
      parts.push(`前瞻 EPS: ${fmtNumber(intermediates.forward_eps)}`);
    }
    if (intermediates.target_multiple !== undefined) {
      parts.push(`目标 P/E: ${fmtNumber(intermediates.target_multiple)}x`);
    }
  } else if (modelKey === "ev_ebitda") {
    if (intermediates.multiple !== undefined) {
      parts.push(`目标倍数: ${fmtNumber(intermediates.multiple)}x`);
    }
    if (intermediates.ev !== undefined) {
      parts.push(`EV: ${fmtBigNumber(intermediates.ev, currencySymbol)}`);
    }
    if (intermediates.net_debt !== undefined) {
      parts.push(`净负债: ${fmtBigNumber(intermediates.net_debt, currencySymbol)}`);
    }
    if (intermediates.equity_value !== undefined) {
      parts.push(`股权价值: ${fmtBigNumber(intermediates.equity_value, currencySymbol)}`);
    }
    if (intermediates.market_cap !== undefined) {
      parts.push(`参考市值: ${fmtBigNumber(intermediates.market_cap, currencySymbol)}`);
    }
  } else if (modelKey === "fcf_yield") {
    if (intermediates.forward_fcfe !== undefined) {
      parts.push(`前瞻 FCFE: ${fmtBigNumber(intermediates.forward_fcfe, currencySymbol)}`);
    }
    if (intermediates.yield_rate !== undefined) {
      parts.push(`目标收益率: ${fmtPct(intermediates.yield_rate)}`);
    }
    if (intermediates.equity_value !== undefined) {
      parts.push(`股权价值: ${fmtBigNumber(intermediates.equity_value, currencySymbol)}`);
    }
  } else if (modelKey === "dcf") {
    if (intermediates.enterprise_value !== undefined) {
      parts.push(`EV: ${fmtBigNumber(intermediates.enterprise_value, currencySymbol)}`);
    }
    if (intermediates.pv_terminal_value !== undefined) {
      parts.push(`PVTV: ${fmtBigNumber(intermediates.pv_terminal_value, currencySymbol)}`);
    }
    if (intermediates.equity_value !== undefined) {
      parts.push(`股权价值: ${fmtBigNumber(intermediates.equity_value, currencySymbol)}`);
    }
    if (intermediates.net_debt !== undefined) {
      parts.push(`净负债: ${fmtBigNumber(intermediates.net_debt, currencySymbol)}`);
    }
  }

  if (parts.length === 0) {
    for (const [k, v] of Object.entries(intermediates)) {
      if (typeof v === "object" && v !== null) continue;
      parts.push(`${labelForKey(k)}: ${asText(v)}`);
    }
  }

  return escapeTableCell(parts.join(" · ") || "—");
}

export function formatMetricProvenance(metric: FinancialMetric | undefined): string {
  if (!metric) return "—";
  const est = metric.is_estimated ? "估算" : "实际";
  const parts = [
    metric.unit || "—",
    metric.period || "—",
    metric.source || "—",
    fmtDate(metric.as_of),
    est,
  ];
  if (metric.source_type) {
    parts.push(SOURCE_LABELS[metric.source_type] ?? metric.source_type);
  }
  if (metric.confidence !== undefined) {
    parts.push(`置信度 ${fmtPct(metric.confidence)}`);
  }
  return parts.join(" · ");
}

function modelMetricEntries(
  model: ModelValuation,
  kind: "inputs" | "assumptions",
): Array<[string, unknown]> {
  const stableMap = kind === "inputs" ? model.input_metrics : model.assumption_metrics;
  if (stableMap && Object.keys(stableMap).length > 0) {
    return Object.entries(stableMap);
  }
  return Object.entries(kind === "inputs" ? model.inputs ?? {} : model.assumptions ?? {});
}

function projectionRows(sc: DCFScenario): Array<{
  label: string;
  fcff: unknown;
  pv: unknown;
}> {
  const metrics = sc.projection_metrics;
  if (Array.isArray(metrics) && metrics.length > 0) {
    return metrics.map((row, index) => {
      const fcff = row.fcff ?? row.fcff_metric ?? (isFinancialMetric(row) ? row : "—");
      const pv = row.pv ?? row.pv_metric ?? sc.pv_projections[index] ?? "—";
      return {
        label: String(row.label ?? row.period ?? row.year ?? `第${index + 1}年`),
        fcff,
        pv,
      };
    });
  }
  if (metrics && !Array.isArray(metrics)) {
    return Object.entries(metrics).map(([key, row], index) => {
      const fcff = row.fcff ?? row.fcff_metric ?? (isFinancialMetric(row) ? row : "—");
      const pv = row.pv ?? row.pv_metric ?? sc.pv_projections[index] ?? "—";
      return {
        label: String(row.label ?? row.period ?? row.year ?? key ?? `第${index + 1}年`),
        fcff,
        pv,
      };
    });
  }
  return (sc.fcff_projections ?? []).map((fcff, index) => ({
    label: sc.projection_periods?.[index]
      ? String(sc.projection_periods[index])
      : sc.projection_years?.[index]
        ? String(sc.projection_years[index])
      : `第${index + 1}年`,
    fcff,
    pv: sc.pv_projections?.[index] ?? "—",
  }));
}

export function buildExportFilename(ticker: string, date = new Date()): string {
  const safeTicker = (ticker || "STOCK").replace(/[^a-zA-Z0-9_.-]/g, "_").toUpperCase();
  const pad = (n: number) => String(n).padStart(2, "0");
  const yyyy = date.getFullYear();
  const mm = pad(date.getMonth() + 1);
  const dd = pad(date.getDate());
  const hh = pad(date.getHours());
  const min = pad(date.getMinutes());
  const ss = pad(date.getSeconds());
  return `${safeTicker}_valuation_${yyyy}${mm}${dd}_${hh}${min}${ss}.md`;
}

export interface GenerateMarkdownOptions {
  exportTime?: Date;
}

/**
 * Generates comprehensive, standalone Markdown document containing the complete
 * valuation state matching all sections of the valuation page.
 */
export function generateValuationMarkdown(
  data: ValuationResponse,
  options?: GenerateMarkdownOptions,
): string {
  const exportTime = options?.exportTime ?? new Date();
  const exportTimeStr = fmtDateTime(exportTime.toISOString());
  const currencySymbol = data.currency === "USD" ? "$" : `${data.currency} `;
  const qualityLabel = DATA_QUALITY_LABELS_ZH[data.data_quality] ?? data.data_quality ?? "—";
  const composite = data.composite;
  const isCompositeAvailable =
    composite?.available !== false && (composite?.available_models?.length ?? 0) > 0;

  const classification = composite?.classification_label_zh
    ?? (composite?.classification ? CLASSIFICATION_LABELS_ZH[composite.classification] : undefined)
    ?? (composite?.classification ? CLASSIFICATION_ZH[composite.classification] : undefined)
    ?? (isCompositeAvailable ? "暂不可判定" : "不可用");

  const lines: string[] = [];

  // 1. Header & Metadata
  lines.push(`# ${escapeMarkdownText(data.company_name)} (${escapeMarkdownText(data.ticker)}) 估值分析报告`);
  lines.push("");
  lines.push("> 本报告由美股估值分析平台自动生成，包含当前所有四套独立估值模型、综合评估、输入明细及数据来源。");
  lines.push("");
  lines.push("### 基本信息与行情基准");
  lines.push("");
  lines.push(`- **股票代码**：${escapeTableCell(data.ticker)}`);
  lines.push(`- **公司名称**：${escapeTableCell(data.company_name)}`);
  lines.push(`- **报价币种**：${escapeTableCell(data.currency)}`);
  lines.push(`- **市场参考价**：${fmtPrice(data.current_price, currencySymbol)}`);
  lines.push(
    `- **行情报价时间**：${
      data.price_timestamp ? fmtDateTime(data.price_timestamp) : "市场参考报价"
    }（可能存在延迟）`,
  );
  lines.push(`- **财报基准日**：${fmtDate(data.as_of)}`);
  lines.push(`- **数据源提供方**：${escapeTableCell(data.provider_label || data.provider || "公开金融数据接口")}`);
  lines.push(
    `- **数据模式**：${
      data.is_demo
        ? "DEMO 固定演示数据（AVGO 离线测试数据集 · 数据不随请求自动更新）"
        : "LIVE 真实市场与财务数据（非实时保证，行情可能存在延迟）"
    }`,
  );
  lines.push(`- **数据质量评级**：${qualityLabel}`);
  lines.push(`- **报告导出时间**：${exportTimeStr}`);
  lines.push("");

  // 2. Warnings
  if (data.warnings && data.warnings.length > 0) {
    lines.push("### 数据提醒");
    lines.push("");
    for (const w of data.warnings) {
      lines.push(`- ⚠ ${escapeTableCell(w)}`);
    }
    lines.push("");
  }

  // 3. Composite Valuation
  lines.push("---");
  lines.push("");
  lines.push("## 一、综合估值结论");
  lines.push("");
  if (isCompositeAvailable) {
    const lowPrice = fmtPrice(composite?.fair_value_low ?? composite?.low, currencySymbol);
    const basePrice = fmtPrice(composite?.fair_value_base ?? composite?.base, currencySymbol);
    const highPrice = fmtPrice(composite?.fair_value_high ?? composite?.high, currencySymbol);
    const mos = fmtPctSigned(composite?.margin_of_safety ?? composite?.mos_pct);
    const upside = fmtPctSigned(composite?.upside_downside ?? composite?.upside_pct);

    lines.push("| 综合指标 | 数值 / 评定 | 说明 |");
    lines.push("| :--- | :--- | :--- |");
    lines.push(`| **综合公允价值区间** | **低位 ${lowPrice} · 基准 ${basePrice} · 高位 ${highPrice}** | 四模型加权综合目标价 |`);
    lines.push(`| **估值判断** | **${classification}** | 现价对比基准公允价值分类 |`);
    lines.push(`| **安全边际 (MOS)** | **${mos}** | （基准公允价值 − 当前价）/ 基准公允价值 |`);
    lines.push(`| **预期上行 / 下跌空间** | **${upside}** | （基准公允价值 − 当前价）/ 当前价 |`);
    lines.push(`| **有效模型数量** | **${composite?.available_models?.length ?? 0} / 4** | 参与综合权重的模型数量 |`);
    lines.push(`| **现金流口径** | **FCF Yield = FCFE · DCF = FCFF** | 权益自由现金流 vs 企业自由现金流口径隔离 |`);
    lines.push("");

    if (composite?.weights_used && Object.keys(composite.weights_used).length > 0) {
      lines.push("#### 模型权重分布");
      lines.push("");
      lines.push("| 模型 | 键值 | 综合权重 | 状态 |");
      lines.push("| :--- | :--- | :--- | :--- |");
      for (const [key, weight] of Object.entries(composite.weights_used)) {
        const name = MODEL_LABELS_ZH[key] ?? labelForKey(key);
        lines.push(`| ${escapeTableCell(name)} | \`${key}\` | ${fmtPct(weight)} | 已纳入 |`);
      }
      lines.push("");
    }

    if (composite?.calculation_steps && composite.calculation_steps.length > 0) {
      lines.push("#### 综合计算推导过程");
      lines.push("");
      composite.calculation_steps.forEach((step, idx) => {
        lines.push(`${idx + 1}. ${escapeTableCell(step)}`);
      });
      lines.push("");
    }
  } else {
    lines.push("> **综合估值暂不可用**");
    lines.push(`> 原因：${escapeTableCell(composite?.unavailable_reason ?? "由于必要财务输入缺失，未能得出综合公允价值区间。")}`);
    lines.push("");
  }

  // 4. Model Assumptions & Effective Overrides
  lines.push("---");
  lines.push("");
  lines.push("## 二、估值假设与情景参数");
  lines.push("");
  lines.push("下表列出系统采用的核心估值参数、情景设定及数据来源（含用户自定义覆盖生效情况）：");
  lines.push("");
  lines.push("| 参数项 | 低位 / 悲观 | 基准 (Base) | 高位 / 乐观 | 生效状态 | 来源 / 依据 |");
  lines.push("| :--- | :--- | :--- | :--- | :--- | :--- |");

  const assumptions = data.assumptions_used;
  const statusLabel = (src: string | undefined) => {
    if (src === "user_override") return "用户覆盖生效";
    if (src === "configured_fallback") return "系统默认基准";
    if (src) return SOURCE_LABELS[src] ?? src;
    return "系统基准";
  };

  if (assumptions) {
    if (assumptions.pe_target) {
      lines.push(
        `| 前瞻市盈率 (P/E Multiple) | ${fmtNumber(assumptions.pe_target.low)}x | **${fmtNumber(assumptions.pe_target.base)}x** | ${fmtNumber(assumptions.pe_target.high)}x | ${statusLabel(assumptions.pe_source)} | ${escapeTableCell(assumptions.pe_source_label || assumptions.pe_source || "历史与同业倍数")} |`,
      );
    }
    if (assumptions.ev_ebitda_multiple) {
      lines.push(
        `| EV / EBITDA 倍数 | ${fmtNumber(assumptions.ev_ebitda_multiple.low)}x | **${fmtNumber(assumptions.ev_ebitda_multiple.base)}x** | ${fmtNumber(assumptions.ev_ebitda_multiple.high)}x | ${statusLabel(assumptions.ev_ebitda_source)} | ${escapeTableCell(assumptions.ev_ebitda_source_label || assumptions.ev_ebitda_source || "行业与历史分位数")} |`,
      );
    }
    if (assumptions.fcf_yield) {
      lines.push(
        `| FCF 目标收益率 (FCF Yield) | ${fmtPct(assumptions.fcf_yield.low)} | **${fmtPct(assumptions.fcf_yield.base)}** | ${fmtPct(assumptions.fcf_yield.high)} | ${statusLabel(assumptions.fcf_yield_source)} | ${escapeTableCell(assumptions.fcf_yield_source_label || assumptions.fcf_yield_source || "无风险利率 + 风险溢价")} |`,
      );
    }
    if (assumptions.dcf_wacc) {
      lines.push(
        `| DCF 加权资本成本 (WACC) | ${fmtPct(assumptions.dcf_wacc.low)} | **${fmtPct(assumptions.dcf_wacc.base)}** | ${fmtPct(assumptions.dcf_wacc.high)} | ${statusLabel(assumptions.dcf_wacc_source)} | ${escapeTableCell(assumptions.dcf_wacc_source_label || assumptions.dcf_wacc_source || "资本资产定价模型 CAPM")} |`,
      );
    }
    if (assumptions.dcf_terminal_growth) {
      const tgSource = (assumptions as unknown as Record<string, unknown>).dcf_terminal_growth_source as string | undefined;
      lines.push(
        `| DCF 永续增长率 (Terminal Growth) | ${fmtPct(assumptions.dcf_terminal_growth.low)} | **${fmtPct(assumptions.dcf_terminal_growth.base)}** | ${fmtPct(assumptions.dcf_terminal_growth.high)} | ${statusLabel(tgSource)} | 长期 GDP 增长锚定上限 5% |`,
      );
    }
    if (assumptions.dcf_fcf_growth) {
      lines.push(
        `| DCF 预测期增长率 (FCFF Growth) | ${fmtPct(assumptions.dcf_fcf_growth.low)} | **${fmtPct(assumptions.dcf_fcf_growth.base)}** | ${fmtPct(assumptions.dcf_fcf_growth.high)} | 用户覆盖生效 | 分析师预期与历史复合成长 |`,
      );
    }
  }
  lines.push("");

  // 5. Four Independent Valuation Models
  lines.push("---");
  lines.push("");
  lines.push("## 三、四套独立估值模型明细");
  lines.push("");

  const modelKeys: Array<keyof ValuationResponse["valuations"]> = [
    "forward_pe",
    "ev_ebitda",
    "fcf_yield",
    "dcf",
  ];

  modelKeys.forEach((key, modelIndex) => {
    const model = data.valuations?.[key];
    const modelName = MODEL_LABELS_ZH[key] ?? key;
    lines.push(`### 3.${modelIndex + 1} ${modelName} (${key})`);
    lines.push("");

    if (!model) {
      lines.push("> **该模型暂未提供数据**：后端未返回此模型的计算结构。");
      lines.push("");
      return;
    }

    const modelQuality = DATA_QUALITY_LABELS_ZH[model.data_quality] ?? model.data_quality ?? "—";
    lines.push(`- **模型可用状态**：${model.available ? "✅ 可用" : "❌ 不可用"}`);
    lines.push(`- **数据质量**：${modelQuality}`);
    if (model.formula) {
      lines.push(`- **计算公式**：\`${model.formula}\``);
    }
    if (model.formula_description) {
      lines.push(`- **公式说明**：${escapeTableCell(model.formula_description)}`);
    }

    if (!model.available) {
      lines.push("");
      lines.push(`> **不可用原因**：${escapeTableCell(model.unavailable_reason ?? "由于财务科目缺失或币种不一致，该模型暂不可用。")}`);
      if (model.warnings && model.warnings.length > 0) {
        lines.push(">");
        lines.push("> **模型警示与说明**：");
        for (const w of model.warnings) {
          lines.push(`> - ⚠ ${escapeTableCell(w)}`);
        }
      }
      lines.push("");
      return;
    }

    // Scenarios Table
    lines.push("");
    lines.push("#### 估值情景目标价");
    lines.push("");
    lines.push("| 情景 | 每股公允价值 | 预期上行空间 | 现价相对估值溢折价 | 核心计算中间值 (Intermediates) |");
    lines.push("| :--- | :--- | :--- | :--- | :--- |");
    const lowP = model.low ? fmtPrice(model.low.price_per_share, currencySymbol) : "—";
    const lowUp = model.low ? fmtPctSigned(model.low.upside_pct) : "—";
    const lowPrem = model.low ? fmtPctSigned(model.low.premium_discount_pct) : "—";
    const lowInter = formatScenarioIntermediates(key, model.low?.intermediates as Record<string, unknown> | undefined, currencySymbol);
    lines.push(`| 低位 (Low) | ${lowP} | ${lowUp} | ${lowPrem} | ${lowInter} |`);

    const baseP = model.base ? fmtPrice(model.base.price_per_share, currencySymbol) : "—";
    const baseUp = model.base ? fmtPctSigned(model.base.upside_pct) : "—";
    const basePrem = model.base ? fmtPctSigned(model.base.premium_discount_pct) : "—";
    const baseInter = formatScenarioIntermediates(key, model.base?.intermediates as Record<string, unknown> | undefined, currencySymbol);
    lines.push(`| **基准 (Base)** | **${baseP}** | **${baseUp}** | **${basePrem}** | **${baseInter}** |`);

    const highP = model.high ? fmtPrice(model.high.price_per_share, currencySymbol) : "—";
    const highUp = model.high ? fmtPctSigned(model.high.upside_pct) : "—";
    const highPrem = model.high ? fmtPctSigned(model.high.premium_discount_pct) : "—";
    const highInter = formatScenarioIntermediates(key, model.high?.intermediates as Record<string, unknown> | undefined, currencySymbol);
    lines.push(`| 高位 (High) | ${highP} | ${highUp} | ${highPrem} | ${highInter} |`);

    lines.push(`| 当前参考价 | ${fmtPrice(data.current_price, currencySymbol)} | — | — | 现价基准 |`);
    lines.push("");

    // Input Metrics Table
    const inputEntries = modelMetricEntries(model, "inputs");
    if (inputEntries.length > 0) {
      lines.push("#### 模型财务输入（含完整溯源）");
      lines.push("");
      lines.push("| 输入科目 | 字段代码 | 数值 | 单位 | 期间 | 数据源 | 来源类型 | 基准日期 | 置信度 | 估算标记 | 备注 |");
      lines.push("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |");
      for (const [paramKey, rawVal] of inputEntries) {
        const label = labelForKey(paramKey);
        const metric = isFinancialMetric(rawVal) ? rawVal : undefined;
        const displayVal = displayMetricValue(rawVal, paramKey, metric?.unit);
        const unit = metric?.unit ?? "—";
        const period = metric?.period ?? "—";
        const src = metric?.source ?? "—";
        const srcType = metric?.source_type ? (SOURCE_LABELS[metric.source_type] ?? metric.source_type) : "—";
        const asOf = metric?.as_of ? fmtDate(metric.as_of) : "—";
        const conf = metric?.confidence !== undefined ? fmtPct(metric.confidence) : "—";
        const est = metric ? (metric.is_estimated ? "是 (估算)" : "否 (实际)") : "—";
        const notes = metric?.notes ?? "—";

        lines.push(
          `| ${escapeTableCell(label)} | \`${paramKey}\` | ${escapeTableCell(displayVal)} | ${escapeTableCell(unit)} | ${escapeTableCell(period)} | ${escapeTableCell(src)} | ${escapeTableCell(srcType)} | ${escapeTableCell(asOf)} | ${escapeTableCell(conf)} | ${escapeTableCell(est)} | ${escapeTableCell(notes)} |`,
        );
      }
      lines.push("");
    }

    // Assumptions Table
    const assumptionEntries = modelMetricEntries(model, "assumptions");
    if (assumptionEntries.length > 0) {
      lines.push("#### 模型假设明细");
      lines.push("");
      lines.push("| 假设科目 | 字段代码 | 数值 | 单位 | 期间 | 来源 | 备注 |");
      lines.push("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |");
      for (const [paramKey, rawVal] of assumptionEntries) {
        const label = labelForKey(paramKey);
        const metric = isFinancialMetric(rawVal) ? rawVal : undefined;
        const displayVal = displayMetricValue(rawVal, paramKey, metric?.unit);
        const unit = metric?.unit ?? "—";
        const period = metric?.period ?? "—";
        const src = metric?.source ?? "—";
        const notes = metric?.notes ?? (typeof rawVal === "object" && !metric ? JSON.stringify(rawVal) : "—");

        lines.push(
          `| ${escapeTableCell(label)} | \`${paramKey}\` | ${escapeTableCell(displayVal)} | ${escapeTableCell(unit)} | ${escapeTableCell(period)} | ${escapeTableCell(src)} | ${escapeTableCell(notes)} |`,
        );
      }
      lines.push("");
    }

    // Calculation Steps
    if (model.calculation_steps && model.calculation_steps.length > 0) {
      lines.push("#### 逐步计算推导");
      lines.push("");
      model.calculation_steps.forEach((step, idx) => {
        lines.push(`${idx + 1}. ${escapeTableCell(step)}`);
      });
      lines.push("");
    }

    // Warnings
    if (model.warnings && model.warnings.length > 0) {
      lines.push("#### 模型提示与警告");
      lines.push("");
      for (const w of model.warnings) {
        lines.push(`- ⚠ ${escapeTableCell(w)}`);
      }
      lines.push("");
    }

    // DCF Scenarios Detailed Breakdown
    if (key === "dcf" && model.dcf_scenarios && model.dcf_scenarios.length > 0) {
      lines.push("#### DCF 五年现金流预测与折现拆解（悲观 / 基准 / 乐观）");
      lines.push("");
      lines.push("> 注：DCF 使用企业自由现金流 (FCFF)，并按 WACC 折现为现值，最终通过加现金、减总债务调整至股权价值。");
      lines.push("");

      for (const sc of model.dcf_scenarios) {
        const scName = SCENARIO_NAMES_ZH[sc.scenario] ?? sc.scenario;
        lines.push(`##### 【${scName}】`);
        lines.push("");
        lines.push(`- **加权资本成本 (WACC)**：${fmtPct(sc.wacc, 2)}`);
        lines.push(`- **永续增长率 (Terminal Growth)**：${fmtPct(sc.terminal_growth, 2)}`);
        if (sc.growth_rate !== undefined) {
          lines.push(`- **预测期增长率 (Growth Rate)**：${fmtPct(sc.growth_rate, 2)}`);
        }
        lines.push("");

        // Valuation bridge
        lines.push("###### 企业价值至股权价值桥梁");
        lines.push("");
        lines.push("| 财务与估值科目 | 金额 / 数值 | 说明 |");
        lines.push("| :--- | :--- | :--- |");
        lines.push(`| 企业价值 (Enterprise Value, EV) | **${fmtBigNumber(sc.enterprise_value, currencySymbol)}** | 预测期现金流现值之和 + 终端价值现值 |`);
        lines.push(`| 终端价值 (Terminal Value, TV) | ${fmtBigNumber(sc.terminal_value, currencySymbol)} | 永续年金模型估算期末价值 |`);
        lines.push(`| 终端价值现值 (PV of TV) | ${fmtBigNumber(sc.pv_terminal_value, currencySymbol)} | TV 按 WACC 折现至当前 |`);
        lines.push(`| 现金及现金等价物 (+) | ${fmtBigNumber(sc.cash, currencySymbol)} | 资产负债表货币资金 |`);
        lines.push(`| 总债务 (−) | ${fmtBigNumber(sc.total_debt, currencySymbol)} | 资产负债表长短期有息负债 |`);
        lines.push(`| 净负债 (Net Debt) | ${fmtBigNumber(sc.net_debt, currencySymbol)} | 总债务 − 现金 |`);
        lines.push(`| 股权价值 (Equity Value) | **${fmtBigNumber(sc.equity_value, currencySymbol)}** | EV − 净负债 (EV + 现金 − 总债务) |`);
        lines.push(`| 稀释后总股数 | ${fmtShares(sc.diluted_shares)} 股 | 最新稀释股本 |`);
        lines.push(`| **每股公允价值** | **${fmtPrice(sc.price_per_share, currencySymbol)}** | 股权价值 / 稀释总股数 |`);
        lines.push(`| 预期上行空间 | ${fmtPctSigned(sc.upside_pct)} | （每股价值 − 当前价）/ 当前价 |`);
        lines.push(`| 现价相对估值溢折价 | ${fmtPctSigned(sc.premium_discount_pct)} | 现价相比该情景公允价值之溢折比率 |`);
        lines.push("");

        // 5-Year Projections Table
        const rows = projectionRows(sc);
        if (rows.length > 0) {
          lines.push("###### 五年 FCFF 预测与折现明细");
          lines.push("");
          lines.push("| 预测期间 | FCFF 预测值 | FCFF 数据来源与属性 | PV 折现现值 | PV 数据来源与属性 |");
          lines.push("| :--- | :--- | :--- | :--- | :--- |");
          for (const r of rows) {
            const fcffMetric = isFinancialMetric(r.fcff) ? r.fcff : undefined;
            const pvMetric = isFinancialMetric(r.pv) ? r.pv : undefined;
            const fcffVal = fmtBigNumber(fcffMetric?.value ?? r.fcff, currencySymbol);
            const pvVal = fmtBigNumber(pvMetric?.value ?? r.pv, currencySymbol);
            const fcffProv = formatMetricProvenance(fcffMetric);
            const pvProv = formatMetricProvenance(pvMetric);

            lines.push(
              `| ${escapeTableCell(r.label)} | ${escapeTableCell(fcffVal)} | ${escapeTableCell(fcffProv)} | ${escapeTableCell(pvVal)} | ${escapeTableCell(pvProv)} |`,
            );
          }
          lines.push("");
        }

        // Scenario calculation steps if present
        if (sc.calculation_steps && sc.calculation_steps.length > 0) {
          lines.push("###### 情景推导步骤");
          lines.push("");
          sc.calculation_steps.forEach((step, idx) => {
            lines.push(`${idx + 1}. ${escapeTableCell(step)}`);
          });
          lines.push("");
        }

        // Scenario warnings
        if (sc.warnings && sc.warnings.length > 0) {
          lines.push("###### 情景注意事项");
          lines.push("");
          for (const w of sc.warnings) {
            lines.push(`- ⚠ ${escapeTableCell(w)}`);
          }
          lines.push("");
        }
      }
    }
  });

  // 6. Disclaimer
  lines.push("---");
  lines.push("");
  lines.push("## 四、免责声明与使用条款");
  lines.push("");
  lines.push("- **仅供参考**：本报告及估值结果仅用于教育、学术研究及量化财务模型验证，**不构成任何投资建议、买卖要约或财务咨询**。");
  lines.push("- **风险提示**：股票市场具有固有波动风险，未来实际业绩、宏观利率、资本开支与自由现金流可能与模型假设产生重大偏差。");
  lines.push("- **数据准确性**：数据来源于第三方公开金融数据接口，平台已标注各指标之基准日期、来源类别与置信度，但不对外部数据之完整性、时效性及绝对准确性作法律担保。");
  lines.push("");

  return lines.join("\n");
}

/**
 * Triggers a browser download of the Markdown content as a UTF-8 encoded .md file.
 * Safely cleans up the Object URL after download.
 */
export function downloadMarkdown(filename: string, content: string): void {
  if (typeof window === "undefined" || typeof document === "undefined") {
    return;
  }
  const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.setAttribute("download", filename);
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

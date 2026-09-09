"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { DCFScenarios } from "@/components/DCFScenarios";
import {
  ApiError,
  fetchValuation,
  postValuationOverride,
  resetValuation,
} from "@/lib/api";
import {
  CLASSIFICATION_COLORS,
  CLASSIFICATION_ZH,
  displayMetricValue,
  fmtDate,
  fmtDateTime,
  fmtPct,
  fmtPctSigned,
  fmtPrice,
  isFinancialMetric,
  pctColor,
  qualityClass,
} from "@/lib/format";
import {
  CLASSIFICATION_LABELS_ZH,
  DATA_QUALITY_LABELS_ZH,
  MODEL_LABELS_ZH,
  type FinancialMetric,
  type ModelValuation,
  type OverrideForm,
  type OverrideRequest,
  type PriceEstimate,
  type ValuationResponse,
} from "@/lib/types";
import {
  buildExportFilename,
  downloadMarkdown,
  generateValuationMarkdown,
} from "@/lib/exportMarkdown";

const EMPTY_FORM: OverrideForm = {
  pe_base: "",
  ev_base: "",
  fcf_yield_base: "",
  dcf_wacc: "",
  dcf_terminal_growth: "",
  dcf_fcf_growth: "",
};

const MODEL_KEYS = ["forward_pe", "ev_ebitda", "fcf_yield", "dcf"] as const;
type ModelKey = (typeof MODEL_KEYS)[number];

const FIELD_LABELS: Record<string, string> = {
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

const SOURCE_LABELS: Record<string, string> = {
  actual: "实际数据",
  analyst_estimate: "分析师估计",
  derived: "派生值",
  configured_fallback: "配置回退",
  user_override: "用户覆盖",
  fixture: "固定演示数据",
};

function labelForKey(key: string): string {
  return FIELD_LABELS[key] ?? key.replaceAll("_", " ");
}

function toDisplayValue(value: unknown, key: string, unit = ""): string {
  if (typeof value === "string" && !isFinancialMetric(value)) {
    const sourceLabel = SOURCE_LABELS[value];
    if (sourceLabel) return sourceLabel;
  }
  if (isFinancialMetric(value)) return displayMetricValue(value, key, value.unit);
  if (typeof value === "object" && value !== null) {
    try {
      return JSON.stringify(value);
    } catch {
      return "—";
    }
  }
  return displayMetricValue(value, key, unit);
}

function asText(value: unknown): string {
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

function metricProvenance(metric: FinancialMetric): string {
  const estimate = metric.is_estimated ? "估算" : "实际";
  return `${metric.unit || "—"} · ${metric.period || "—"} · ${metric.source || "—"} · ${fmtDate(metric.as_of)} · ${estimate}`;
}

interface ErrorDisplayInfo {
  title: string;
  message: string;
  advice?: string;
  status?: number;
  code?: string;
}

function ErrorMessage({
  error,
  onRetry,
  onSelectTicker,
}: {
  error: ErrorDisplayInfo;
  onRetry?: () => void;
  onSelectTicker?: (ticker: string) => void;
}) {
  const QUICK_EXAMPLES = ["NVDA", "AAPL", "MSFT", "AVGO"];
  return (
    <div className="error-panel" role="alert">
      <div className="error-icon">!</div>
      <div className="error-content">
        <div className="error-header-row">
          <strong>{error.title}</strong>
          {error.status ? <span className="error-status-badge">HTTP {error.status}</span> : null}
        </div>
        <p className="error-message-text">{error.message}</p>
        {error.advice && <p className="error-advice-text">{error.advice}</p>}
        <div className="error-actions">
          {onRetry && (
            <button type="button" className="retry-button" onClick={onRetry}>
              ↺ 重新查询
            </button>
          )}
          {onSelectTicker && (
            <div className="error-examples">
              <span>尝试其他标的：</span>
              {QUICK_EXAMPLES.map((item) => (
                <button
                  key={item}
                  type="button"
                  className="quick-ticker-button"
                  onClick={() => onSelectTicker(item)}
                >
                  {item}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function LoadingState({
  message = "正在读取估值数据…",
  onCancel,
}: {
  message?: string;
  onCancel?: () => void;
}) {
  return (
    <div className="loading-panel" role="status" aria-live="polite">
      <span className="loading-spinner" />
      <div className="loading-content">
        <strong>{message}</strong>
        <p>正在从金融数据源拉取最新财报、市场行情与分析师一致预期，并运算四套估值模型（通常需要数秒）…</p>
        {onCancel && (
          <button type="button" className="cancel-button" onClick={onCancel}>
            ✕ 取消查询
          </button>
        )}
      </div>
    </div>
  );
}

function ScenarioValue({
  label,
  estimate,
  currency,
}: {
  label: string;
  estimate: PriceEstimate | undefined;
  currency: string;
}) {
  const currencySymbol = currency === "USD" ? "$" : `${currency} `;
  return (
    <div className={`valuation-scenario valuation-scenario-${label}`}>
      <span>{label === "low" ? "低位" : label === "base" ? "基准" : "高位"}</span>
      <strong>{estimate ? fmtPrice(estimate.price_per_share, currencySymbol) : "不可用"}</strong>
      {estimate ? (
        <small className={pctColor(estimate.upside_pct)}>
          上行 {fmtPctSigned(estimate.upside_pct)} · 现价相对估值 {fmtPctSigned(estimate.premium_discount_pct)}
        </small>
      ) : <small>缺少完整情景输入</small>}
    </div>
  );
}

function ProvenanceTable({
  model,
  kind,
}: {
  model: ModelValuation;
  kind: "inputs" | "assumptions";
}) {
  const entries = modelMetricEntries(model, kind);
  return (
    <div className="provenance-table-wrap">
      <div className="section-kicker">{kind === "inputs" ? "模型输入（含来源）" : "模型假设（含来源）"}</div>
      {entries.length === 0 ? (
        <p className="empty-state">暂无可用的{kind === "inputs" ? "输入" : "假设"}来源信息。</p>
      ) : (
        <div className="provenance-list">
          {entries.map(([key, value]) => {
            const metric = isFinancialMetric(value) ? value : undefined;
            return (
              <div className="provenance-row" key={`${kind}-${key}`}>
                <span className="provenance-name">{labelForKey(key)}</span>
                <strong>{toDisplayValue(value, key, metric?.unit)}</strong>
                {metric ? (
                  <small>
                    {metricProvenance(metric)}
                    {metric.source_type && ` · ${SOURCE_LABELS[metric.source_type] ?? metric.source_type}`}
                    {metric.confidence !== undefined && ` · 置信度 ${fmtPct(metric.confidence)}`}
                  </small>
                ) : (
                  <small>后端计算字段 · 原始值：{asText(value)}</small>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function ModelCard({
  modelKey,
  model,
  currentPrice,
  currency,
}: {
  modelKey: ModelKey;
  model: ModelValuation | undefined;
  currentPrice: string | number;
  currency: string;
}) {
  const currentSymbol = currency === "USD" ? "$" : `${currency} `;
  const title = MODEL_LABELS_ZH[modelKey] ?? modelKey;

  if (!model) {
    return (
      <article className="model-card model-card-unavailable">
        <div className="model-card-header">
          <div className="model-title-row">
            <h3>{title}</h3>
            <span className="quality-badge quality-low">无数据</span>
          </div>
          <span className="availability unavailable">不可用</span>
        </div>
        <div className="unavailable-panel">
          <strong>该模型暂未提供数据</strong>
          <p>后端未返回此模型的计算结构或财务输入科目不足。</p>
        </div>
      </article>
    );
  }

  const warnings = model.warnings ?? [];
  const calculationSteps = model.calculation_steps ?? [];

  return (
    <article className={`model-card ${!model.available ? "model-card-unavailable" : ""}`}>
      <div className="model-card-header">
        <div>
          <div className="model-title-row">
            <h3>{title}</h3>
            <span className={`quality-badge ${qualityClass(model.data_quality)}`}>
              {DATA_QUALITY_LABELS_ZH[model.data_quality] ?? model.data_quality}
            </span>
          </div>
          <p>{model.formula_description}</p>
        </div>
        <span className={`availability ${model.available ? "available" : "unavailable"}`}>
          {model.available ? "可用" : "不可用"}
        </span>
      </div>

      {!model.available ? (
        <div className="unavailable-panel">
          <strong>该模型暂不可用</strong>
          <p>{model.unavailable_reason ?? "后端未返回足够的有效输入或财务科目不满足计算条件。"}</p>
          {warnings.length > 0 && (
            <div className="warning-stack">
              {warnings.map((warning) => (
                <div className="inline-warning" key={warning}>⚠ {warning}</div>
              ))}
            </div>
          )}
        </div>
      ) : (
        <>
          <div className="model-summary-grid">
            <ScenarioValue label="low" estimate={model.low} currency={currency} />
            <ScenarioValue label="base" estimate={model.base} currency={currency} />
            <ScenarioValue label="high" estimate={model.high} currency={currency} />
            <div className="valuation-scenario current-scenario">
              <span>当前参考股价</span>
              <strong>{fmtPrice(currentPrice, currentSymbol)}</strong>
              <small>以 API 返回行情为准（或有延迟）</small>
            </div>
          </div>

          <details className="details-panel" open>
            <summary>输入、假设与完整计算步骤</summary>
            <div className="details-content">
              <p className="formula-line">{model.formula}</p>
              <div className="provenance-columns">
                <ProvenanceTable model={model} kind="inputs" />
                <ProvenanceTable model={model} kind="assumptions" />
              </div>
              <div className="steps-block">
                <div className="section-kicker">逐步计算</div>
                {calculationSteps.length > 0 ? (
                  <ol className="steps-list">
                    {calculationSteps.map((step, index) => <li key={`${index}-${step}`}>{step}</li>)}
                  </ol>
                ) : <p className="empty-state">暂无逐步计算明细。</p>}
              </div>
              {warnings.length > 0 && (
                <div className="warning-stack">
                  {warnings.map((warning) => <div className="inline-warning" key={warning}>⚠ {warning}</div>)}
                </div>
              )}
            </div>
          </details>

          {modelKey === "dcf" && (
            <div className="dcf-block">
              <div className="section-heading-row">
                <div>
                  <div className="section-kicker">五年情景拆解</div>
                  <h4>DCF：悲观 / 基准 / 乐观</h4>
                </div>
                <span className="fcff-chip">FCFF ≠ FCFE</span>
              </div>
              <DCFScenarios scenarios={model.dcf_scenarios ?? []} currentPrice={currentPrice} currency={currency} />
            </div>
          )}
        </>
      )}
    </article>
  );
}

function buildOverrides(form: OverrideForm): { request?: OverrideRequest; error?: string } {
  const fields: Array<[string, string]> = [
    ["P/E 基准", form.pe_base],
    ["EV/EBITDA 基准", form.ev_base],
    ["FCF 收益率基准", form.fcf_yield_base],
    ["WACC", form.dcf_wacc],
    ["永续增长率", form.dcf_terminal_growth],
    ["FCFF 预测增长率", form.dcf_fcf_growth],
  ];
  const values: Record<string, number | undefined> = {};
  for (const [label, raw] of fields) {
    const value = raw.trim();
    if (!value) continue;
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return { error: `${label} 必须是有限数字。` };
    values[label] = parsed;
  }
  const request: OverrideRequest = {};
  if (values["P/E 基准"] !== undefined) request.forward_pe = { base: values["P/E 基准"] };
  if (values["EV/EBITDA 基准"] !== undefined) request.ev_ebitda = { base: values["EV/EBITDA 基准"] };
  if (values["FCF 收益率基准"] !== undefined) request.fcf_yield = { base: values["FCF 收益率基准"] };
  const dcf: NonNullable<OverrideRequest["dcf"]> = {};
  if (values.WACC !== undefined) dcf.wacc = values.WACC;
  if (values["永续增长率"] !== undefined) dcf.terminal_growth = values["永续增长率"];
  if (values["FCFF 预测增长率"] !== undefined) dcf.fcf_growth = values["FCFF 预测增长率"];
  if (Object.keys(dcf).length > 0) request.dcf = dcf;
  return { request };
}

function classificationLabel(composite: ValuationResponse["composite"] | undefined): string {
  if (!composite) return "暂不可判定";
  return composite.classification_label_zh
    ?? (composite.classification ? CLASSIFICATION_LABELS_ZH[composite.classification] : undefined)
    ?? (composite.classification ? CLASSIFICATION_ZH[composite.classification] : undefined)
    ?? "暂不可判定";
}

export default function ValuationPage() {
  const params = useParams<{ ticker: string }>();
  const router = useRouter();
  const routeTicker = useMemo(() => {
    const value = params?.ticker;
    return (Array.isArray(value) ? value[0] : value || "AVGO").toUpperCase();
  }, [params]);
  const [searchTicker, setSearchTicker] = useState(routeTicker);
  const [data, setData] = useState<ValuationResponse | null>(null);
  const [form, setForm] = useState<OverrideForm>(EMPTY_FORM);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ErrorDisplayInfo | null>(null);
  const [formError, setFormError] = useState("");
  const [action, setAction] = useState<"load" | "recalculate" | "reset">("load");
  const requestState = useRef<{
    generation: number;
    controller: AbortController | null;
  }>({ generation: 0, controller: null });

  const startRequest = useCallback((nextAction: "load" | "recalculate" | "reset") => {
    requestState.current.controller?.abort();
    const controller = new AbortController();
    const generation = requestState.current.generation + 1;
    requestState.current = { generation, controller };
    setLoading(true);
    setAction(nextAction);
    return { generation, controller };
  }, []);

  const isCurrentRequest = useCallback((generation: number): boolean => {
    return requestState.current.generation === generation;
  }, []);

  const loadTickerData = useCallback((targetTicker: string) => {
    setSearchTicker(targetTicker);
    setData(null);
    setForm(EMPTY_FORM);
    setFormError("");
    setError(null);
    const { generation, controller } = startRequest("load");
    fetchValuation(targetTicker, controller.signal)
      .then((response) => {
        if (isCurrentRequest(generation)) setData(response);
      })
      .catch((reason: unknown) => {
        if (!isCurrentRequest(generation)) return;
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setData(null);
        if (reason instanceof ApiError) {
          setError({
            title: reason.actionableTitle,
            message: reason.message,
            advice: reason.actionableAdvice,
            status: reason.status,
            code: reason.code,
          });
        } else if (reason instanceof Error) {
          setError({
            title: "查询未完成",
            message: reason.message,
            advice: "请检查网络或后端服务后重试。",
          });
        } else {
          setError({
            title: "查询未完成",
            message: "发生未知异常，请稍后重试。",
          });
        }
      })
      .finally(() => {
        if (isCurrentRequest(generation)) {
          requestState.current.controller = null;
          setLoading(false);
        }
      });
  }, [isCurrentRequest, startRequest]);

  useEffect(() => {
    loadTickerData(routeTicker);
    return () => {
      requestState.current.controller?.abort();
    };
  }, [loadTickerData, routeTicker]);

  function handleCancel() {
    requestState.current.controller?.abort();
    requestState.current.controller = null;
    setLoading(false);
    setError({
      title: "已取消查询",
      message: `已取消对 ${routeTicker} 的估值查询。`,
      advice: "您可以点击“重新查询”，或输入其他美股代码。",
    });
  }

  function handleRetry() {
    loadTickerData(routeTicker);
  }

  function handleSelectTicker(nextTicker: string) {
    if (nextTicker === routeTicker) {
      loadTickerData(nextTicker);
    } else {
      requestState.current.controller?.abort();
      setData(null);
      setLoading(true);
      setError(null);
      router.push(`/valuation/${nextTicker}`);
    }
  }

  function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const ticker = searchTicker.trim().toUpperCase();
    if (!/^[A-Z]{1,12}(?:[.-][A-Z0-9]{1,4})?$/.test(ticker)) {
      setError({
        title: "股票代码格式有误",
        message: "请输入有效的美股代码，例如 NVDA, AAPL, MSFT，或股份类别代码 BRK.B, BRK-B。",
        advice: "请检查股票代码拼写后重试。",
      });
      return;
    }
    if (ticker === routeTicker) {
      loadTickerData(ticker);
    } else {
      requestState.current.controller?.abort();
      setData(null);
      setLoading(true);
      setError(null);
      router.push(`/valuation/${ticker}`);
    }
  }

  async function handleRecalculate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const result = buildOverrides(form);
    if (result.error) {
      setFormError(result.error);
      return;
    }
    if (!result.request || Object.keys(result.request).length === 0) {
      setFormError("请至少填写一个覆盖值；如需恢复默认值，请点击“重置默认”。");
      return;
    }
    setFormError("");
    setError(null);
    const { generation, controller } = startRequest("recalculate");
    try {
      const response = await postValuationOverride(routeTicker, result.request, controller.signal);
      if (isCurrentRequest(generation)) setData(response);
    } catch (reason) {
      if (isCurrentRequest(generation) && !(reason instanceof DOMException && reason.name === "AbortError")) {
        if (reason instanceof ApiError) {
          setFormError(`${reason.actionableTitle}：${reason.message}`);
        } else if (reason instanceof Error) {
          setFormError(reason.message);
        } else {
          setFormError("重新计算失败，请检查覆盖数值。");
        }
      }
    } finally {
      if (isCurrentRequest(generation)) {
        requestState.current.controller = null;
        setLoading(false);
      }
    }
  }

  async function handleReset() {
    setForm(EMPTY_FORM);
    setFormError("");
    setError(null);
    const { generation, controller } = startRequest("reset");
    try {
      const response = await resetValuation(routeTicker, controller.signal);
      if (isCurrentRequest(generation)) setData(response);
    } catch (reason) {
      if (isCurrentRequest(generation) && !(reason instanceof DOMException && reason.name === "AbortError")) {
        if (reason instanceof ApiError) {
          setError({
            title: reason.actionableTitle,
            message: reason.message,
            advice: reason.actionableAdvice,
            status: reason.status,
          });
        } else {
          setError({
            title: "重置失败",
            message: "无法恢复默认估值，请稍后重试。",
          });
        }
      }
    } finally {
      if (isCurrentRequest(generation)) {
        requestState.current.controller = null;
        setLoading(false);
      }
    }
  }

  function updateField(field: keyof OverrideForm, value: string) {
    setForm((current) => ({ ...current, [field]: value }));
    if (formError) setFormError("");
  }

  function handleExportMarkdown() {
    if (!data) return;
    const filename = buildExportFilename(data.ticker);
    const content = generateValuationMarkdown(data);
    downloadMarkdown(filename, content);
  }

  const composite = data?.composite;
  const isCompositeAvailable = composite?.available !== false && (composite?.available_models?.length ?? 0) > 0;
  const qualityLabel = data ? DATA_QUALITY_LABELS_ZH[data.data_quality] ?? data.data_quality : "";
  const classificationTone = composite?.classification
    ? CLASSIFICATION_COLORS[composite.classification] ?? "classification-neutral"
    : "classification-neutral";
  const currencySymbol = data?.currency === "USD" ? "$" : `${data?.currency ?? "USD"} `;

  return (
    <main className="app-shell">
      <header className="topbar">
        <Link href="/" className="brand-mark">
          <span className="brand-icon">SV</span>
          <span>
            <strong>估值台</strong>
            <small>US STOCK VALUATION</small>
          </span>
        </Link>
        <form className="top-search" onSubmit={handleSearch}>
          <span className="search-icon">⌕</span>
          <input
            value={searchTicker}
            onChange={(event) => setSearchTicker(event.target.value.toUpperCase())}
            placeholder="输入股票代码，如 NVDA / AAPL / MSFT / BRK.B"
            maxLength={15}
            aria-label="股票代码"
          />
          <button type="submit">查询</button>
        </form>
        <div className="quick-tags">
          {["NVDA", "AAPL", "MSFT", "AVGO"].map((t) => (
            <button
              key={t}
              type="button"
              className={`quick-tag ${t === routeTicker ? "active" : ""}`}
              onClick={() => handleSelectTicker(t)}
            >
              {t}
            </button>
          ))}
        </div>
        <Link href="/" className="top-link">返回首页</Link>
      </header>

      <div className="content-wrap">
        {loading && !data && (
          <LoadingState
            message={action === "load" ? `正在加载 ${routeTicker} 估值数据…` : "正在更新估值…"}
            onCancel={handleCancel}
          />
        )}
        {error && (
          <ErrorMessage
            error={error}
            onRetry={handleRetry}
            onSelectTicker={handleSelectTicker}
          />
        )}

        {data && (
          <>
            <section className="hero-card">
              <div className="hero-heading">
                <div>
                  <div className="eyebrow">综合估值 · {data.ticker}</div>
                  <h1>{data.company_name}</h1>
                  <p className="hero-meta">
                    <span>{data.ticker}</span>
                    <span>{data.currency}</span>
                    <span>财报基准日 {fmtDate(data.as_of)}</span>
                    {data.provider_label && <span>数据源 {data.provider_label}</span>}
                  </p>
                </div>
                <div className="hero-heading-right">
                  <div className="hero-price">
                    <span>市场参考价（或有延迟）</span>
                    <strong>{fmtPrice(data.current_price, currencySymbol)}</strong>
                    <small>{data.price_timestamp ? `报价日期 ${fmtDateTime(data.price_timestamp)}（或有延迟）` : "市场参考报价（或有延迟）"}</small>
                  </div>
                  <button
                    type="button"
                    className="button-secondary export-button"
                    onClick={handleExportMarkdown}
                    disabled={loading || !data}
                    title="导出当前估值完整信息为 Markdown 文件"
                  >
                    ⭳ 导出 Markdown
                  </button>
                </div>
              </div>

              {data.is_demo ? (
                <div className="demo-banner">
                  <span className="demo-badge">DEMO</span>
                  <div>
                    <strong>固定演示数据</strong>
                    <span>AVGO 离线测试数据集 · 数据不会随请求自动更新，仅用于验证模型与界面。</span>
                  </div>
                  <span className={`quality-badge ${qualityClass(data.data_quality)}`}>{qualityLabel}</span>
                </div>
              ) : (
                <div className="live-data-banner">
                  <span className="live-badge">LIVE 市场数据（可能延迟）</span>
                  <div>
                    <strong>真实市场与财务数据（非实时保证，行情可能存在延迟）</strong>
                    <span>
                      数据源：{data.provider_label || data.provider || "公开金融数据接口"} · 财报基准日：{fmtDate(data.as_of)} · 报价日期：{data.price_timestamp ? fmtDateTime(data.price_timestamp) : "最新交易日"}（非保证实时价格）
                    </span>
                  </div>
                  <span className={`quality-badge ${qualityClass(data.data_quality)}`}>{qualityLabel}</span>
                </div>
              )}

              <div className="composite-grid">
                <div className="composite-main">
                  <div className="section-kicker">综合目标价区间</div>
                  {isCompositeAvailable ? (
                    <div className="fair-value-row">
                      <div><span>低位</span><strong>{fmtPrice(composite?.fair_value_low ?? composite?.low, currencySymbol)}</strong></div>
                      <div className="fair-value-base"><span>基准</span><strong>{fmtPrice(composite?.fair_value_base ?? composite?.base, currencySymbol)}</strong></div>
                      <div><span>高位</span><strong>{fmtPrice(composite?.fair_value_high ?? composite?.high, currencySymbol)}</strong></div>
                    </div>
                  ) : (
                    <div className="fair-value-unavailable">
                      <strong>综合估值暂不可用</strong>
                      <p>{composite?.unavailable_reason ?? "由于必要财务输入缺失，未能得出综合公允价值区间。"}</p>
                    </div>
                  )}
                </div>
                <div className="composite-metric">
                  <span>安全边际（MOS）</span>
                  <strong className={pctColor(composite?.margin_of_safety ?? composite?.mos_pct)}>
                    {isCompositeAvailable ? fmtPctSigned(composite?.margin_of_safety ?? composite?.mos_pct) : "—"}
                  </strong>
                  <small>MOS =（基准公允价值 − 当前价）/ 基准公允价值</small>
                </div>
                <div className="composite-metric">
                  <span>上涨 / 下跌空间</span>
                  <strong className={pctColor(composite?.upside_downside ?? composite?.upside_pct)}>
                    {isCompositeAvailable ? fmtPctSigned(composite?.upside_downside ?? composite?.upside_pct) : "—"}
                  </strong>
                  <small>（公允价值 − 当前价）/ 当前价</small>
                </div>
                <div className={`classification-card ${isCompositeAvailable ? classificationTone : "classification-neutral"}`}>
                  <span>估值判断</span>
                  <strong>{isCompositeAvailable ? classificationLabel(composite) : "暂不可判定"}</strong>
                  <small>价格 / 基准公允价值分类</small>
                </div>
              </div>
            </section>

            {data.warnings?.length > 0 && (
              <section className="notice-card">
                <div className="section-kicker">数据提醒</div>
                <div className="warning-stack">{data.warnings.map((warning) => <div className="inline-warning" key={warning}>⚠ {warning}</div>)}</div>
              </section>
            )}

            <section className="control-card">
              <div className="section-heading-row">
                <div>
                  <div className="section-kicker">情景控制</div>
                  <h2>覆盖假设并重新计算</h2>
                  <p>只填写需要覆盖的基准值；留空项沿用默认值。每次提交仅应用于本次分析。</p>
                </div>
                <div className="control-actions">
                  <button type="button" className="button-secondary" onClick={handleReset} disabled={loading}>↺ 重置默认</button>
                </div>
              </div>
              <form className="override-form" onSubmit={handleRecalculate}>
                <label><span>P/E 基准</span><input value={form.pe_base} onChange={(e) => updateField("pe_base", e.target.value)} placeholder={asText(data.assumptions_used?.pe_target?.base)} inputMode="decimal" /><small>倍数，例如 20</small></label>
                <label><span>EV/EBITDA 基准</span><input value={form.ev_base} onChange={(e) => updateField("ev_base", e.target.value)} placeholder={asText(data.assumptions_used?.ev_ebitda_multiple?.base)} inputMode="decimal" /><small>倍数，例如 22</small></label>
                <label><span>FCF 收益率基准</span><input value={form.fcf_yield_base} onChange={(e) => updateField("fcf_yield_base", e.target.value)} placeholder={asText(data.assumptions_used?.fcf_yield?.base)} inputMode="decimal" /><small>小数，例如 0.05</small></label>
                <label><span>WACC</span><input value={form.dcf_wacc} onChange={(e) => updateField("dcf_wacc", e.target.value)} placeholder={asText(data.assumptions_used?.dcf_wacc?.base)} inputMode="decimal" /><small>小数，例如 0.10</small></label>
                <label><span>永续增长率</span><input value={form.dcf_terminal_growth} onChange={(e) => updateField("dcf_terminal_growth", e.target.value)} placeholder={asText(data.assumptions_used?.dcf_terminal_growth?.base)} inputMode="decimal" /><small>必须低于 WACC，最高 0.05</small></label>
                <label><span>FCFF 预测增长率（可选）</span><input value={form.dcf_fcf_growth} onChange={(e) => updateField("dcf_fcf_growth", e.target.value)} placeholder="沿用后端增长推导" inputMode="decimal" /><small>仅覆盖第 3-5 年增长</small></label>
                <div className="form-submit-row">
                  {formError && <span className="form-error" role="alert">{formError}</span>}
                  <button type="submit" className="button-primary" disabled={loading}>{loading && action === "recalculate" ? "计算中…" : "应用覆盖并计算"}</button>
                </div>
              </form>
            </section>

            <section className="assumption-strip">
              <div><span>数据质量</span><strong className={`quality-badge ${qualityClass(data.data_quality)}`}>{qualityLabel}</strong></div>
              <div><span>有效模型</span><strong>{composite?.available_models?.length ?? 0} / 4</strong></div>
              <div><span>综合权重</span><strong>{Object.entries(composite?.weights_used ?? {}).map(([key, value]) => `${key} ${fmtPct(value)}`).join(" · ") || (isCompositeAvailable ? "后端未提供" : "无有效权重")}</strong></div>
              <div><span>现金流口径</span><strong>FCF Yield = FCFE · DCF = FCFF</strong></div>
            </section>

            <section className="models-section">
              <div className="section-heading-row section-heading-wide">
                <div><div className="section-kicker">独立估值模型</div><h2>四套模型结果</h2></div>
                <p>每套模型都保留公式、输入来源、假设和逐步计算明细。</p>
              </div>
              <div className="models-stack">
                {MODEL_KEYS.map((modelKey) => (
                  <ModelCard
                    key={modelKey}
                    modelKey={modelKey}
                    model={data.valuations?.[modelKey]}
                    currentPrice={data.current_price}
                    currency={data.currency}
                  />
                ))}
              </div>
            </section>

            {composite?.calculation_steps && composite.calculation_steps.length > 0 && (
              <section className="notice-card composite-steps-card">
                <div className="section-kicker">综合计算过程</div>
                <ol className="steps-list">{composite.calculation_steps.map((step, index) => <li key={`${index}-${step}`}>{step}</li>)}</ol>
              </section>
            )}

            <footer className="page-footer">估值结果仅用于教育和模型验证，不构成投资建议。数据来源、日期和估算标记请以各输入行展示为准。</footer>
          </>
        )}

        {!loading && !data && !error && <LoadingState message="暂无数据" />}
        {loading && data && <div className="refresh-indicator" role="status"><span className="loading-spinner small" />{action === "reset" ? "正在恢复默认估值…" : "正在重新计算…"}</div>}
      </div>
    </main>
  );
}

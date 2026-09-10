"use client";

import { useState } from "react";
import type {
  DCFScenario,
  DCFSensitivityMatrix,
  FinancialMetric,
} from "@/lib/types";
import { DCFSensitivityMatrixTable } from "./DCFSensitivityMatrix";
import {
  displayMetricValue,
  fmtBigNumber,
  fmtDate,
  fmtPct,
  fmtPctSigned,
  fmtPrice,
  fmtShares,
  isFinancialMetric,
  pctColor,
} from "@/lib/format";

interface Props {
  scenarios: DCFScenario[];
  currentPrice: string | number;
  currency?: string;
  sensitivityMatrix?: DCFSensitivityMatrix;
}

const SCENARIO_LABELS: Record<string, { zh: string; tone: string }> = {
  bear: { zh: "悲观情景", tone: "scenario-bear" },
  base: { zh: "基准情景", tone: "scenario-base" },
  bull: { zh: "乐观情景", tone: "scenario-bull" },
};

function metricFromValue(value: unknown): FinancialMetric | undefined {
  if (isFinancialMetric(value)) return value;
  return undefined;
}

function projectionRows(sc: DCFScenario): Array<{
  key: string;
  label: string;
  fcff: unknown;
  pv: unknown;
}> {
  const metrics = sc.projection_metrics;
  if (Array.isArray(metrics) && metrics.length > 0) {
    return metrics.map((row, index) => {
      // The final API publishes each projection metric as the FCFF metric
      // itself; older responses used {fcff, pv} pairs. Support both shapes.
      const fcff = row.fcff ?? row.fcff_metric ?? (isFinancialMetric(row) ? row : "—");
      const pv = row.pv ?? row.pv_metric ?? sc.pv_projections[index] ?? "—";
      return {
        key: `${row.label ?? row.year ?? row.period ?? index}-${index}`,
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
        key,
        label: String(row.label ?? row.period ?? row.year ?? key ?? `第${index + 1}年`),
        fcff,
        pv,
      };
    });
  }
  return sc.fcff_projections.map((fcff, index) => ({
    key: `fallback-${index}`,
    label: sc.projection_periods?.[index]
      ? String(sc.projection_periods[index])
      : sc.projection_years?.[index]
        ? String(sc.projection_years[index])
      : `第${index + 1}年`,
    fcff,
    pv: sc.pv_projections[index] ?? "—",
  }));
}

function metricProvenance(metric: FinancialMetric | undefined): string {
  if (!metric) return "";
  const estimate = metric.is_estimated ? "估算" : "实际";
  return `${metric.unit || "—"} · ${metric.period || "—"} · ${metric.source || "—"} · ${fmtDate(metric.as_of)} · ${estimate}`;
}

function SummaryItem({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="metric-tile">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function ScenarioPanel({
  scenario,
  currentPrice,
  currency,
}: {
  scenario: DCFScenario;
  currentPrice: string | number;
  currency: string;
}) {
  const [expanded, setExpanded] = useState(scenario.scenario === "base");
  const meta = SCENARIO_LABELS[scenario.scenario] ?? {
    zh: scenario.scenario,
    tone: "scenario-base",
  };
  const projectionRowsForScenario = projectionRows(scenario);
  const projectionMetric = (value: unknown) => metricFromValue(value);

  return (
    <section className={`scenario-panel ${meta.tone}`}>
      <button
        type="button"
        className="scenario-header"
        onClick={() => setExpanded((value) => !value)}
        aria-expanded={expanded}
      >
        <span className="scenario-title">
          <span className="scenario-dot" />
          {meta.zh}
        </span>
        <span className="scenario-assumptions">
          WACC {fmtPct(scenario.wacc, 1)} · 永续增长 {fmtPct(scenario.terminal_growth, 1)}
          {scenario.growth_rate !== undefined && ` · 预测增长 ${fmtPct(scenario.growth_rate, 1)}`}
        </span>
        <span className="scenario-price">
          {fmtPrice(scenario.price_per_share, currency === "USD" ? "$" : `${currency} `)}
          <small className={pctColor(scenario.upside_pct)}>{fmtPctSigned(scenario.upside_pct)}</small>
        </span>
        <span className="accordion-icon" aria-hidden="true">{expanded ? "−" : "+"}</span>
      </button>

      {expanded && (
        <div className="scenario-detail">
          <div className="metric-grid metric-grid-4">
            <SummaryItem label="企业价值 EV" value={fmtBigNumber(scenario.enterprise_value)} />
            <SummaryItem label="股权价值" value={fmtBigNumber(scenario.equity_value)} />
            <SummaryItem label="终端价值 TV" value={fmtBigNumber(scenario.terminal_value)} />
            <SummaryItem label="终端价值现值 PVTV" value={fmtBigNumber(scenario.pv_terminal_value)} />
            <SummaryItem label="净负债" value={fmtBigNumber(scenario.net_debt)} />
            <SummaryItem label="总债务" value={fmtBigNumber(scenario.total_debt)} />
            <SummaryItem label="现金" value={fmtBigNumber(scenario.cash)} />
            <SummaryItem label="稀释股数" value={fmtShares(scenario.diluted_shares)} />
            <SummaryItem label="当前股价" value={fmtPrice(currentPrice)} />
            <SummaryItem label="每股价值" value={fmtPrice(scenario.price_per_share)} />
            <SummaryItem label="上行空间" value={fmtPctSigned(scenario.upside_pct)} />
            <SummaryItem label="现价相对估值" value={fmtPctSigned(scenario.premium_discount_pct)} />
          </div>

          <div className="detail-section">
            <div className="detail-section-heading">
              <h4>五年 FCFF 预测与折现</h4>
              <span>FCFF（企业自由现金流）仅用于 DCF，并按 WACC 折现</span>
            </div>
            {scenario.growth_compound_horizon && (
              <div className="text-xs text-indigo-300 bg-indigo-950/40 border border-indigo-800/40 rounded-lg p-2.5 my-2 flex items-center gap-2">
                <span>📅</span>
                <span>预测日历基准：{scenario.growth_compound_horizon}</span>
              </div>
            )}
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>期间</th>
                    <th>FCFF</th>
                    <th>FCFF 来源 / 期间 / 日期</th>
                    <th>PV（现值）</th>
                    <th>PV 来源 / 期间 / 日期</th>
                  </tr>
                </thead>
                <tbody>
                  {projectionRowsForScenario.map((row) => {
                    const fcffMetric = projectionMetric(row.fcff);
                    const pvMetric = projectionMetric(row.pv);
                    return (
                      <tr key={row.key}>
                        <td className="table-label">{row.label}</td>
                        <td>{fmtBigNumber(fcffMetric?.value ?? row.fcff)}</td>
                        <td className="provenance-cell">{metricProvenance(fcffMetric) || "后端计算明细"}</td>
                        <td className="value-blue">{fmtBigNumber(pvMetric?.value ?? row.pv)}</td>
                        <td className="provenance-cell">{metricProvenance(pvMetric) || "后端计算明细"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {(scenario.formula || scenario.formula_description || scenario.formulas || scenario.calculation_steps?.length) && (
            <div className="detail-section">
              <div className="detail-section-heading">
                <h4>公式与计算步骤</h4>
                <span>所有中间值来自后端模型</span>
              </div>
              {scenario.formula && <p className="formula-line">{scenario.formula}</p>}
              {scenario.formula_description && <p className="helper-text">{scenario.formula_description}</p>}
              {scenario.formulas && Object.entries(scenario.formulas).length > 0 && (
                <div className="formula-map">
                  {Object.entries(scenario.formulas).map(([key, formula]) => (
                    <p className="formula-line" key={key}><strong>{key}</strong> · {formula}</p>
                  ))}
                </div>
              )}
              {scenario.calculation_steps && scenario.calculation_steps.length > 0 && (
                <ol className="steps-list">
                  {scenario.calculation_steps.map((step, index) => <li key={`${index}-${step}`}>{step}</li>)}
                </ol>
              )}
            </div>
          )}

          {(scenario.input_metrics || scenario.assumption_metrics) && (
            <div className="detail-section compact-detail">
              <div className="detail-section-heading"><h4>情景输入来源</h4></div>
              {scenario.input_metrics && Object.entries(scenario.input_metrics).map(([key, metric]) => (
                <div className="provenance-row" key={`input-${key}`}>
                  <span>{key}</span>
                  <strong>{displayMetricValue(metric, key, metric.unit)}</strong>
                  <small>{metric.unit} · {metric.period} · {metric.source} · {fmtDate(metric.as_of)} · {metric.is_estimated ? "估算" : "实际"}</small>
                </div>
              ))}
              {scenario.assumption_metrics && Object.entries(scenario.assumption_metrics).map(([key, metric]) => (
                <div className="provenance-row" key={`assumption-${key}`}>
                  <span>{key}</span>
                  <strong>{displayMetricValue(metric, key, metric.unit)}</strong>
                  <small>{metric.unit} · {metric.period} · {metric.source} · {fmtDate(metric.as_of)} · {metric.is_estimated ? "估算" : "实际"}</small>
                </div>
              ))}
            </div>
          )}

          {scenario.warnings.length > 0 && (
            <div className="warning-stack">
              {scenario.warnings.map((warning, index) => <div className="inline-warning" key={`${index}-${warning}`}>⚠ {warning}</div>)}
            </div>
          )}
        </div>
      )}
    </section>
  );
}

export function DCFScenarios({ scenarios, currentPrice, currency = "USD", sensitivityMatrix }: Props) {
  if (!scenarios || scenarios.length === 0) {
    return <p className="empty-state">暂无 DCF 情景数据</p>;
  }
  return (
    <div className="scenario-stack">
      <p className="helper-text">展开悲观、基准或乐观情景，查看五年 FCFF、逐年 PV、终端价值和股权价值的完整链路。</p>
      {scenarios.map((scenario) => (
        <ScenarioPanel key={scenario.scenario} scenario={scenario} currentPrice={currentPrice} currency={currency} />
      ))}
      {sensitivityMatrix && (
        <DCFSensitivityMatrixTable matrix={sensitivityMatrix} currency={currency} />
      )}
    </div>
  );
}

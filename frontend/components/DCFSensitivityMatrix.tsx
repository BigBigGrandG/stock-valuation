import React from "react";
import type { DCFSensitivityMatrix } from "../lib/types";

interface Props {
  matrix?: DCFSensitivityMatrix;
  currency?: string;
}

export const DCFSensitivityMatrixTable: React.FC<Props> = ({
  matrix,
  currency = "USD",
}) => {
  if (!matrix || !matrix.cells || matrix.cells.length === 0) {
    return null;
  }

  const formatPct = (val: string | number | undefined) => {
    if (val === undefined || val === null) return "-";
    const num = typeof val === "string" ? parseFloat(val) : val;
    return isNaN(num) ? "-" : `${(num * 100).toFixed(1)}%`;
  };

  const formatCurrency = (val: string | number | undefined) => {
    if (val === undefined || val === null) return "-";
    const num = typeof val === "string" ? parseFloat(val) : val;
    const symbol = currency === "USD" ? "$" : `${currency} `;
    return isNaN(num) ? "-" : `${symbol}${num.toFixed(2)}`;
  };

  const tvRatioNum = matrix.base_tv_ratio
    ? typeof matrix.base_tv_ratio === "string"
      ? parseFloat(matrix.base_tv_ratio)
      : Number(matrix.base_tv_ratio)
    : 0;

  return (
    <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-5 mt-6 backdrop-blur-sm">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-3 border-b border-slate-800 gap-2">
        <div>
          <h4 className="text-base font-semibold text-slate-200 flex items-center gap-2">
            <span>📊</span>
            <span>终值敏感性分析矩阵 (3×3 Sensitivity Matrix)</span>
          </h4>
          <p className="text-xs text-slate-400 mt-0.5">
            折现率 (WACC ±1.0%) 与永续增长率 (g ±0.5%) 的交叉估值（每股合理价值与终值占EV比例）
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-400">基准终值占比:</span>
          <span
            className={`text-xs font-semibold px-2 py-0.5 rounded-full ${
              tvRatioNum > 0.8
                ? "bg-rose-500/20 text-rose-400 border border-rose-500/30"
                : tvRatioNum > 0.7
                ? "bg-amber-500/20 text-amber-400 border border-amber-500/30"
                : "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30"
            }`}
          >
            {(tvRatioNum * 100).toFixed(1)}%
          </span>
        </div>
      </div>

      {matrix.tv_dependence_warning === "high_tv_dependence_strong" && (
        <div className="mt-3 p-3 bg-rose-500/10 border border-rose-500/30 rounded-lg flex items-start gap-2 text-rose-400 text-xs">
          <span className="text-sm leading-none mt-0.5">⚠️</span>
          <div>
            <span className="font-semibold">极高终值依赖风险 (&gt;80%)：</span>
            基准模型中终值折现占比达到 {(tvRatioNum * 100).toFixed(1)}%
            ，远期假设微小波动将对每股估值产生剧烈放大效应。
          </div>
        </div>
      )}

      {matrix.tv_dependence_warning === "high_tv_dependence_moderate" && (
        <div className="mt-3 p-3 bg-amber-500/10 border border-amber-500/30 rounded-lg flex items-start gap-2 text-amber-400 text-xs">
          <span className="text-sm leading-none mt-0.5">ℹ️</span>
          <div>
            <span className="font-semibold">中度终值敏感性 (&gt;70%)：</span>
            终值占比为 {(tvRatioNum * 100).toFixed(1)}%
            ，请重点参考矩阵不同折现率区间下的估值安全边际。
          </div>
        </div>
      )}

      <div className="overflow-x-auto mt-4">
        <table className="w-full text-center border-collapse text-xs">
          <thead>
            <tr>
              <th className="p-2 border border-slate-800 bg-slate-950/80 text-slate-400 font-medium text-left">
                WACC \ 终值增长率 (g)
              </th>
              {matrix.terminal_growth_range.map((tg, idx) => (
                <th
                  key={idx}
                  className={`p-2 border border-slate-800 text-slate-300 font-medium ${
                    idx === 1 ? "bg-indigo-950/40 text-indigo-300" : "bg-slate-950/60"
                  }`}
                >
                  {formatPct(tg)}
                  {idx === 1 && <span className="ml-1 text-[10px] text-indigo-400 font-normal">(基准)</span>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {matrix.cells.map((row, rowIdx) => {
              const rowWacc = matrix.wacc_range[rowIdx];
              const isBaseRow = rowIdx === 1;
              return (
                <tr key={rowIdx}>
                  <td
                    className={`p-2 border border-slate-800 text-left font-medium ${
                      isBaseRow
                        ? "bg-indigo-950/40 text-indigo-300 font-semibold"
                        : "bg-slate-950/60 text-slate-300"
                    }`}
                  >
                    {formatPct(rowWacc)}
                    {isBaseRow && <span className="ml-1 text-[10px] text-indigo-400 font-normal">(基准)</span>}
                  </td>
                  {row.map((cell, colIdx) => {
                    const isBaseCell = rowIdx === 1 && colIdx === 1;
                    const tvPct = cell.tv_ratio ? formatPct(cell.tv_ratio) : "-";

                    return (
                      <td
                        key={colIdx}
                        className={`p-2.5 border border-slate-800 transition-colors ${
                          isBaseCell
                            ? "bg-indigo-600/20 ring-1 ring-inset ring-indigo-400/50"
                            : "hover:bg-slate-800/40"
                        }`}
                      >
                        {cell.available ? (
                          <div className="flex flex-col items-center gap-0.5">
                            <span
                              className={`font-mono text-sm font-semibold ${
                                isBaseCell ? "text-indigo-200 font-bold" : "text-slate-200"
                              }`}
                            >
                              {formatCurrency(cell.price_per_share)}
                            </span>
                            <span className="text-[10px] text-slate-400">
                              TV: {tvPct}
                            </span>
                            {isBaseCell && (
                              <span className="text-[9px] bg-indigo-500/30 text-indigo-300 px-1 rounded uppercase tracking-wider font-semibold">
                                当前基准
                              </span>
                            )}
                          </div>
                        ) : (
                          <span className="text-[10px] text-slate-500 italic">
                            {cell.unavailable_reason || "不适用"}
                          </span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
};

# Broadcom Inc. (AVGO) 估值分析报告

> 本报告由美股估值分析平台自动生成，包含当前所有四套独立估值模型、综合评估、输入明细及数据来源。

### 基本信息与行情基准

- **股票代码**：AVGO
- **公司名称**：Broadcom Inc.
- **报价币种**：USD
- **市场参考价**：$343.83
- **行情报价时间**：2025/01/15 16:00:00（可能存在延迟）
- **财报基准日**：2025/01/15
- **财务报表统计口径**：连续 4 季度 (TTM)
- **总股本口径**：全类别普通股穿透 (ALL_CLASS_RECONCILED)
- **数据源提供方**：公开金融数据接口
- **数据模式**：DEMO 固定演示数据（AVGO 离线测试数据集 · 数据不随请求自动更新）
- **数据质量评级**：低质量
- **报告导出时间**：2026/09/10 18:21:06

### 数据提醒

- ⚠ DEMO DATA: values come from a fixed fixture.
- ⚠ DCF Terminal Value accounts for 80.2% of Enterprise Value (>80%). High sensitivity to terminal assumptions.

---

## 一、综合估值结论

| 综合指标 | 数值 / 评定 | 说明 |
| :--- | :--- | :--- |
| **综合公允价值区间** | **低位 $348.69 · 基准 $422.34 · 高位 $593.56** | 四模型加权综合目标价 |
| **估值判断** | **低估** | 现价对比基准公允价值分类 |
| **安全边际 (MOS)** | **+18.59%** | （基准公允价值 − 当前价）/ 基准公允价值 |
| **预期上行 / 下跌空间** | **+22.83%** | （基准公允价值 − 当前价）/ 当前价 |
| **有效模型数量** | **4 / 4** | 参与综合权重的模型数量 |
| **现金流口径** | **FCF Yield = FCFE · DCF = FCFF** | 权益自由现金流 vs 企业自由现金流口径隔离 |

#### 模型权重分布

| 模型 | 键值 | 综合权重 | 状态 |
| :--- | :--- | :--- | :--- |
| 市盈率估值 | `forward_pe` | 33.33% | 已纳入 |
| EV / EBITDA 估值 | `ev_ebitda` | 26.67% | 已纳入 |
| FCF 收益率估值 | `fcf_yield` | 18.18% | 已纳入 |
| 现金流折现（DCF） | `dcf` | 21.82% | 已纳入 |

#### 综合计算推导过程

1. Complete models used: forward_pe, ev_ebitda, fcf_yield, dcf
2. Selected weights = {'forward_pe': Decimal('0.25'), 'ev_ebitda': Decimal('0.20'), 'fcf_yield': Decimal('0.25'), 'dcf': Decimal('0.30')}
3. Effective weights = {'forward_pe': Decimal('0.3333'), 'ev_ebitda': Decimal('0.2667'), 'fcf_yield': Decimal('0.1818'), 'dcf': Decimal('0.2182')}
4. Cash flow group weight = 0.4000 (cap = 0.40)
5. Composite low = weighted low values = 348.69
6. Composite base = weighted base values = 422.34
7. Composite high = weighted high values = 593.56
8. MOS = (fair value base - current price) / fair value base = 0.1859
9. Upside = (fair value base - current price) / current price = 0.2283

---

## 二、估值假设与情景参数

下表列出系统采用的核心估值参数、情景设定及数据来源（含用户自定义覆盖生效情况）：

| 参数项 | 低位 / 悲观 | 基准 (Base) | 高位 / 乐观 | 生效状态 | 来源 / 依据 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 前瞻市盈率 (P/E Multiple) | 18.00x | **20.00x** | 22.00x | 系统默认基准 | Configured fallback: 18x/20x/22x (low/base/high) |
| EV / EBITDA 倍数 | 18.00x | **22.00x** | 26.00x | 系统默认基准 | Configured fallback: 18x/22x/26x (low/base/high) |
| FCF 目标收益率 (FCF Yield) | 5.50% | **5.00%** | 4.50% | 系统默认基准 | Configured fallback: 5.5%/5.0%/4.5% (low=high yield=conservative) |
| DCF 加权资本成本 (WACC) | 12.00% | **10.00%** | 8.00% | 系统默认基准 | Configured fallback: 12%/10%/8% (bear/base/bull) |
| DCF 永续增长率 (Terminal Growth) | 3.00% | **3.00%** | 4.00% | 系统默认基准 | 长期 GDP 增长锚定上限 5% |
| 预测期跨度 (Forecast Horizon) | — | **NTM** | — | 生效口径 | 分析师前瞻预测时间视界 |
| 衍生增长率上限 (Growth Cap) | — | **40.00%** | — | 生效限制 | 复合增长率上限截断阈值 |
| 衍生增长率下限 (Growth Floor) | — | **-20.00%** | — | 生效限制 | 复合增长率下限截断阈值 |

---

## 三、四套独立估值模型明细

### 3.1 市盈率估值 (forward_pe)

- **模型可用状态**：✅ 可用
- **数据质量**：低质量
- **计算公式**：`Price = Forward EPS × Target P/E`
- **公式说明**：Price target derived from forward EPS multiplied by a target P/E. Historical median is used when available; otherwise the configured fallback applies.

#### 估值情景目标价

| 情景 | 每股公允价值 | 预期上行空间 | 现价相对估值溢折价 | 核心计算中间值 (Intermediates) |
| :--- | :--- | :--- | :--- | :--- |
| 低位 (Low) | $380.36 | +10.62% | -9.60% | 前瞻 EPS: 19.21 · 目标 P/E: 19.80x |
| **基准 (Base)** | **$422.62** | **+22.92%** | **-18.64%** | **前瞻 EPS: 19.21 · 目标 P/E: 22.00x** |
| 高位 (High) | $464.88 | +35.21% | -26.04% | 前瞻 EPS: 19.21 · 目标 P/E: 24.20x |
| 当前参考价 | $343.83 | — | — | 现价基准 |

#### 模型财务输入（含完整溯源）

| 输入科目 | 字段代码 | 数值 | 单位 | 期间 | 数据源 | 来源类型 | 基准日期 | 置信度 | 估算标记 | 备注 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 当前股价 | `current_price` | $343.83 | USD | 2025-01-15 | AVGO TEST/DEMO fixture | 固定演示数据 | 2025/01/15 | 100.00% | 否 (实际) | — |
| 稀释股数 | `diluted_shares` | 4.940B | shares | FY2024 | AVGO TEST/DEMO fixture | 固定演示数据 | 2025/01/15 | 100.00% | 否 (实际) | — |
| 现金 | `cash` | $24.00B | USD | FY2024 | AVGO TEST/DEMO fixture | 固定演示数据 | 2025/01/15 | 100.00% | 否 (实际) | — |
| 总债务 | `total_debt` | $59.40B | USD | FY2024 | AVGO TEST/DEMO fixture | 固定演示数据 | 2025/01/15 | 100.00% | 否 (实际) | — |
| 净负债 | `net_debt` | $35.40B | USD | FY2024 | Derived from total_debt - cash | 派生值 | 2025/01/15 | 100.00% | 否 (实际) | Derived net debt; normalize_snapshot publishes it on the snapshot. |
| 前瞻 EPS | `forward_eps` | $19.21 | USD | NTM (w0=1.00, w1=0.00) | NTM day-weighted blend: 100.0% FY1 (19.21) + 0.0% FY2 (22.50) | 派生值 | 2025/01/15 | 50.00% | 是 (估算) | Calculated from 365/365 remaining days in fiscal year |

#### 模型假设明细

| 假设科目 | 字段代码 | 数值 | 单位 | 期间 | 来源 | 备注 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| P/E 低位 | `pe_multiple_low` | 19.80 | multiple | 5Y median | Derived low range from historical median (AVGO TEST/DEMO fixture) | P/E low: multiple_source=historical; derived ±10% scenario range |
| P/E 基准 | `pe_multiple_base` | 22.00 | multiple | 5Y median | AVGO TEST/DEMO fixture | P/E base: multiple_source=historical; observed historical median |
| P/E 高位 | `pe_multiple_high` | 24.20 | multiple | 5Y median | Derived high range from historical median (AVGO TEST/DEMO fixture) | P/E high: multiple_source=historical; derived ±10% scenario range |

#### 逐步计算推导

1. Forward EPS = 19.21 [NTM (w0=1.00, w1=0.00); NTM day-weighted blend: 100.0% FY1 (19.21) + 0.0% FY2 (22.50); as_of=2025-01-15; estimated=True]
2. P/E multiples (low/base/high) = 19.8000/22.0000/24.2000 [historical; Historical median P/E (AVGO TEST/DEMO fixture)]
3. Price (low) = 19.21 × 19.8000 = 380.36
4. Price (base) = 19.21 × 22.0000 = 422.62
5. Price (high) = 19.21 × 24.2000 = 464.88

### 3.2 EV / EBITDA 估值 (ev_ebitda)

- **模型可用状态**：✅ 可用
- **数据质量**：低质量
- **计算公式**：`EV = Forward EBITDA × Multiple; Price = (EV - Net Debt) / Shares`
- **公式说明**：EV = forward EBITDA × multiple; equity value = EV − net debt; price per share = equity value / diluted shares.

#### 估值情景目标价

| 情景 | 每股公允价值 | 预期上行空间 | 现价相对估值溢折价 | 核心计算中间值 (Intermediates) |
| :--- | :--- | :--- | :--- | :--- |
| 低位 (Low) | $164.23 | -52.24% | +109.36% | 目标倍数: 21.60x · EV: $846.72B · 净负债: $35.40B · 股权价值: $811.32B · 参考市值: $1.70T |
| **基准 (Base)** | **$183.28** | **-46.69%** | **+87.60%** | **目标倍数: 24.00x · EV: $940.80B · 净负债: $35.40B · 股权价值: $905.40B · 参考市值: $1.70T** |
| 高位 (High) | $202.32 | -41.16% | +69.94% | 目标倍数: 26.40x · EV: $1.03T · 净负债: $35.40B · 股权价值: $999.48B · 参考市值: $1.70T |
| 当前参考价 | $343.83 | — | — | 现价基准 |

#### 模型财务输入（含完整溯源）

| 输入科目 | 字段代码 | 数值 | 单位 | 期间 | 数据源 | 来源类型 | 基准日期 | 置信度 | 估算标记 | 备注 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 当前股价 | `current_price` | $343.83 | USD | 2025-01-15 | AVGO TEST/DEMO fixture | 固定演示数据 | 2025/01/15 | 100.00% | 否 (实际) | — |
| 稀释股数 | `diluted_shares` | 4.940B | shares | FY2024 | AVGO TEST/DEMO fixture | 固定演示数据 | 2025/01/15 | 100.00% | 否 (实际) | — |
| 现金 | `cash` | $24.00B | USD | FY2024 | AVGO TEST/DEMO fixture | 固定演示数据 | 2025/01/15 | 100.00% | 否 (实际) | — |
| 总债务 | `total_debt` | $59.40B | USD | FY2024 | AVGO TEST/DEMO fixture | 固定演示数据 | 2025/01/15 | 100.00% | 否 (实际) | — |
| 净负债 | `net_debt` | $35.40B | USD | FY2024 | Derived from total_debt - cash | 派生值 | 2025/01/15 | 100.00% | 否 (实际) | Derived net debt; normalize_snapshot publishes it on the snapshot. |
| 前瞻 EBITDA | `forward_ebitda` | $39.20B | USD | forward_1y | Derived from base EBITDA (28000000000) × (1 + 40.0%) | 派生值 | 2025/01/15 | 50.00% | 是 (估算) | Growth clamped to [-20.0%, 40.0%] |
| 市值 | `market_cap` | $1.70T | USD | valuation date | Derived from current quote × diluted shares | 派生值 | 2025/01/15 | 100.00% | 否 (实际) | Market capitalization used as an exposed EV/EBITDA intermediate. |

#### 模型假设明细

| 假设科目 | 字段代码 | 数值 | 单位 | 期间 | 来源 | 备注 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 倍数低位 | `multiple_low` | 21.60 | multiple | 5Y median | Derived low range from historical median (AVGO TEST/DEMO fixture) | low; multiple_source=historical |
| 倍数基准 | `multiple_base` | 24.00 | multiple | 5Y median | AVGO TEST/DEMO fixture | base; multiple_source=historical |
| 倍数高位 | `multiple_high` | 26.40 | multiple | 5Y median | Derived high range from historical median (AVGO TEST/DEMO fixture) | high; multiple_source=historical |

#### 逐步计算推导

1. Forward EBITDA = 39200000000 [forward_1y; Derived from base EBITDA (28000000000) × (1 + 40.0%); as_of=2025-01-15; estimated=True]
2. Market cap = 343.83 × 4940000000 = 1698520200000.00
3. Net debt = total debt 59400000000 - cash 24000000000 = 35400000000
4. Multiples (low/base/high) = 21.6000/24.0000/26.4000 [historical; Historical median EV/EBITDA (AVGO TEST/DEMO fixture)]
5. [low] EV = 39200000000 × 21.6000 = 846720000000.00
6. [low] Equity = 846720000000.00 - 35400000000 = 811320000000.00
7. [low] Price/share = 811320000000.00 / 4940000000 = 164.23
8. [base] EV = 39200000000 × 24.0000 = 940800000000.00
9. [base] Equity = 940800000000.00 - 35400000000 = 905400000000.00
10. [base] Price/share = 905400000000.00 / 4940000000 = 183.28
11. [high] EV = 39200000000 × 26.4000 = 1034880000000.00
12. [high] Equity = 1034880000000.00 - 35400000000 = 999480000000.00
13. [high] Price/share = 999480000000.00 / 4940000000 = 202.32

### 3.3 FCF 收益率估值 (fcf_yield)

- **模型可用状态**：✅ 可用
- **数据质量**：低质量
- **计算公式**：`Equity Value = Forward FCFE / Yield Rate; Price = Equity / Shares`
- **公式说明**：FCFE (equity free cash flow) divided by the target yield rate, then divided by shares. FCFF is never substituted or discounted in this model.

#### 估值情景目标价

| 情景 | 每股公允价值 | 预期上行空间 | 现价相对估值溢折价 | 核心计算中间值 (Intermediates) |
| :--- | :--- | :--- | :--- | :--- |
| 低位 (Low) | $412.22 | +19.89% | -16.59% | 前瞻 FCFE: $112.00B · 目标收益率: 5.50% · 股权价值: $2.04T |
| **基准 (Base)** | **$453.44** | **+31.88%** | **-24.17%** | **前瞻 FCFE: $112.00B · 目标收益率: 5.00% · 股权价值: $2.24T** |
| 高位 (High) | $503.82 | +46.53% | -31.76% | 前瞻 FCFE: $112.00B · 目标收益率: 4.50% · 股权价值: $2.49T |
| 当前参考价 | $343.83 | — | — | 现价基准 |

#### 模型财务输入（含完整溯源）

| 输入科目 | 字段代码 | 数值 | 单位 | 期间 | 数据源 | 来源类型 | 基准日期 | 置信度 | 估算标记 | 备注 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 当前股价 | `current_price` | $343.83 | USD | 2025-01-15 | AVGO TEST/DEMO fixture | 固定演示数据 | 2025/01/15 | 100.00% | 否 (实际) | — |
| 稀释股数 | `diluted_shares` | 4.940B | shares | FY2024 | AVGO TEST/DEMO fixture | 固定演示数据 | 2025/01/15 | 100.00% | 否 (实际) | — |
| 现金 | `cash` | $24.00B | USD | FY2024 | AVGO TEST/DEMO fixture | 固定演示数据 | 2025/01/15 | 100.00% | 否 (实际) | — |
| 总债务 | `total_debt` | $59.40B | USD | FY2024 | AVGO TEST/DEMO fixture | 固定演示数据 | 2025/01/15 | 100.00% | 否 (实际) | — |
| 净负债 | `net_debt` | $35.40B | USD | FY2024 | Derived from total_debt - cash | 派生值 | 2025/01/15 | 100.00% | 否 (实际) | Derived net debt; normalize_snapshot publishes it on the snapshot. |
| 前瞻 FCFE | `forward_fcfe` | $112.00B | USD | forward_1y | Derived from base FCFE (80000000000) × (1 + 40.0%) | 派生值 | 2025/01/15 | 50.00% | 是 (估算) | Growth clamped to [-20.0%, 40.0%] |

#### 模型假设明细

| 假设科目 | 字段代码 | 数值 | 单位 | 期间 | 来源 | 备注 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 收益率低位情景 | `yield_low` | 5.50% | yield | valuation assumption | Configured fallback: 5.5%/5.0%/4.5% (low=high yield=conservative) | low; low scenario is the high-yield conservative case |
| 收益率基准 | `yield_base` | 5.00% | yield | valuation assumption | Configured fallback: 5.5%/5.0%/4.5% (low=high yield=conservative) | base; low scenario is the high-yield conservative case |
| 收益率高位情景 | `yield_high` | 4.50% | yield | valuation assumption | Configured fallback: 5.5%/5.0%/4.5% (low=high yield=conservative) | high; low scenario is the high-yield conservative case |

#### 逐步计算推导

1. IMPORTANT: Uses FCFE (equity FCF), NOT FCFF (firm FCF used by DCF)
2. Forward FCFE = 112000000000 [forward_1y; Derived from base FCFE (80000000000) × (1 + 40.0%); as_of=2025-01-15; estimated=True]
3. Yield rates (low/base/high) = 0.055/0.050/0.045 [Configured fallback: 5.5%/5.0%/4.5% (low=high yield=conservative)]
4. Low valuation uses the highest yield; high valuation uses the lowest yield.
5. [low (high yield = conservative)] Equity value = 112000000000 / 0.055 = 2036363636363.64
6. [low (high yield = conservative)] Price/share = 2036363636363.64 / 4940000000 = 412.22
7. [base] Equity value = 112000000000 / 0.050 = 2240000000000.00
8. [base] Price/share = 2240000000000.00 / 4940000000 = 453.44
9. [high (low yield = optimistic)] Equity value = 112000000000 / 0.045 = 2488888888888.89
10. [high (low yield = optimistic)] Price/share = 2488888888888.89 / 4940000000 = 503.82

### 3.4 现金流折现（DCF） (dcf)

- **模型可用状态**：✅ 可用
- **数据质量**：低质量
- **计算公式**：`EV = Σ FCFF_t/(1+WACC)^t + TV/(1+WACC)^5; Equity = EV − Net Debt; Price = Equity/Shares`
- **公式说明**：Five-year FCFF DCF. PV_t = FCFF_t/(1+WACC)^t; TV = FCFF5×(1+g)/(WACC-g); PVTV = TV/(1+WACC)^5; EV = ΣPV + PVTV; equity = EV − debt + cash; price = equity/shares.

#### 估值情景目标价

| 情景 | 每股公允价值 | 预期上行空间 | 现价相对估值溢折价 | 核心计算中间值 (Intermediates) |
| :--- | :--- | :--- | :--- | :--- |
| 低位 (Low) | $472.82 | +37.52% | -27.28% | EV: $2.37T · PVTV: $1.76T · 股权价值: $2.34T · 净负债: $35.40B |
| **基准 (Base)** | **$688.21** | **+100.16%** | **-50.04%** | **EV: $3.44T · PVTV: $2.75T · 股权价值: $3.40T · 净负债: $35.40B** |
| 高位 (High) | $1,343.09 | +290.63% | -74.40% | EV: $6.67T · PVTV: $5.91T · 股权价值: $6.63T · 净负债: $35.40B |
| 当前参考价 | $343.83 | — | — | 现价基准 |

#### 模型财务输入（含完整溯源）

| 输入科目 | 字段代码 | 数值 | 单位 | 期间 | 数据源 | 来源类型 | 基准日期 | 置信度 | 估算标记 | 备注 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 当前股价 | `current_price` | $343.83 | USD | 2025-01-15 | AVGO TEST/DEMO fixture | 固定演示数据 | 2025/01/15 | 100.00% | 否 (实际) | — |
| 稀释股数 | `diluted_shares` | 4.940B | shares | FY2024 | AVGO TEST/DEMO fixture | 固定演示数据 | 2025/01/15 | 100.00% | 否 (实际) | — |
| 现金 | `cash` | $24.00B | USD | FY2024 | AVGO TEST/DEMO fixture | 固定演示数据 | 2025/01/15 | 100.00% | 否 (实际) | — |
| 总债务 | `total_debt` | $59.40B | USD | FY2024 | AVGO TEST/DEMO fixture | 固定演示数据 | 2025/01/15 | 100.00% | 否 (实际) | — |
| 净负债 | `net_debt` | $35.40B | USD | FY2024 | Derived from total_debt - cash | 派生值 | 2025/01/15 | 100.00% | 否 (实际) | Derived net debt; normalize_snapshot publishes it on the snapshot. |
| fcff ttm | `fcff_ttm` | $70.00B | USD | TTM/FY2025E | AVGO TEST/DEMO fixture | 固定演示数据 | 2025/01/15 | 100.00% | 否 (实际) | Free Cash Flow to Firm: EBIT*(1-tax) + D&A - capex - ΔNWC. DCF model ONLY (discounted at WACC). |
| forward fcff 1y | `forward_fcff_1y` | $98.00B | USD | FY1E | Derived from base FCFF (70000000000) × (1 + 40.0%) | 派生值 | 2025/01/15 | 80.00% | 是 (估算) | Growth clamped to [-20.0%, 40.0%] |
| forward fcff 2y | `forward_fcff_2y` | $137.20B | USD | FY2E | Derived from Year 1 FCFF × (1 + 40.0%) | 派生值 | 2025/01/15 | 70.00% | 是 (估算) | Growth clamped to [-20.0%, 40.0%] |

#### 模型假设明细

| 假设科目 | 字段代码 | 数值 | 单位 | 期间 | 来源 | 备注 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| WACC 悲观 | `wacc_bear` | 12.00% | rate | valuation assumption | Configured fallback: 12%/10%/8% (bear/base/bull) | wacc_source=fallback |
| WACC 基准 | `wacc_base` | 10.00% | rate | valuation assumption | Configured fallback: 12%/10%/8% (bear/base/bull) | wacc_source=fallback |
| WACC 乐观 | `wacc_bull` | 8.00% | rate | valuation assumption | Configured fallback: 12%/10%/8% (bear/base/bull) | wacc_source=fallback |
| 永续增长悲观 | `terminal_growth_bear` | 3.00% | rate | valuation assumption | Configured fallback terminal growth | terminal growth cap=0.05 |
| 永续增长基准 | `terminal_growth_base` | 3.00% | rate | valuation assumption | Configured fallback terminal growth | terminal growth cap=0.05 |
| 永续增长乐观 | `terminal_growth_bull` | 4.00% | rate | valuation assumption | Configured fallback terminal growth | terminal growth cap=0.05 |
| 预测增长悲观 | `growth_bear` | 25.50% | ratio | FY1E->FY2E | Derived from forward FCFF FY1E and FY2E; effective bear FCFF growth | Raw growth=0.4; effective growth=0.2550; floor=-0.10; cap=0.2550; lineage=Derived from forward FCFF FY1E and FY2E. |
| 预测增长基准 | `growth_base` | 30.00% | ratio | FY1E->FY2E | Derived from forward FCFF FY1E and FY2E; effective base FCFF growth | Raw growth=0.4; effective growth=0.30; floor=-0.10; cap=0.30; lineage=Derived from forward FCFF FY1E and FY2E. |
| 预测增长乐观 | `growth_bull` | 34.50% | ratio | FY1E->FY2E | Derived from forward FCFF FY1E and FY2E; effective bull FCFF growth | Raw growth=0.4; effective growth=0.3450; floor=-0.10; cap=0.3450; lineage=Derived from forward FCFF FY1E and FY2E. |

#### 逐步计算推导

1. IMPORTANT: Uses FCFF (firm/unlevered FCF), NOT FCFE.
2. Year 1 and Year 2 use explicit forward FCFF metrics when available; missing years are derived and labelled.
3. Growth lineage: derived from forward FCFF1→FCFF2 (capped); source_type=derived
4. WACC lineage: fallback; Configured fallback: 12%/10%/8% (bear/base/bull)
5. Terminal growth (bear/base/bull) = 0.03/0.03/0.04; max=0.05
6. Net debt = debt 59400000000 - cash 24000000000 = 35400000000
7. bear: EV=2371136166923.55, PVTV=1760577091883.16, equity=2335736166923.55, price=472.82
8. base: EV=3435181460556.05, PVTV=2753255544068.14, equity=3399781460556.05, price=688.21
9. bull: EV=6670271284931.40, PVTV=5905871085338.98, equity=6634871284931.40, price=1343.09

#### 模型提示与警告

- ⚠ DCF Terminal Value accounts for 80.2% of Enterprise Value (>80%). High sensitivity to terminal assumptions.

#### DCF 五年现金流预测与折现拆解（悲观 / 基准 / 乐观）

> 注：DCF 使用企业自由现金流 (FCFF)，并按 WACC 折现为现值，最终通过加现金、减总债务调整至股权价值。

##### 【悲观情景】

- **加权资本成本 (WACC)**：12.00%
- **永续增长率 (Terminal Growth)**：3.00%
- **预测期增长率 (Growth Rate)**：25.50%

###### 企业价值至股权价值桥梁

| 财务与估值科目 | 金额 / 数值 | 说明 |
| :--- | :--- | :--- |
| 企业价值 (Enterprise Value, EV) | **$2.37T** | 预测期现金流现值之和 + 终端价值现值 |
| 终端价值 (Terminal Value, TV) | $3.10T | 永续年金模型估算期末价值 |
| 终端价值现值 (PV of TV) | $1.76T | TV 按 WACC 折现至当前 |
| 现金及现金等价物 (+) | $24.00B | 资产负债表货币资金 |
| 总债务 (−) | $59.40B | 资产负债表长短期有息负债 |
| 净负债 (Net Debt) | $35.40B | 总债务 − 现金 |
| 股权价值 (Equity Value) | **$2.34T** | EV − 净负债 (EV + 现金 − 总债务) |
| 稀释后总股数 | 4.940B 股 | 最新稀释股本 |
| **每股公允价值** | **$472.82** | 股权价值 / 稀释总股数 |
| 预期上行空间 | +37.52% | （每股价值 − 当前价）/ 当前价 |
| 现价相对估值溢折价 | -27.28% | 现价相比该情景公允价值之溢折比率 |

###### 五年 FCFF 预测与折现明细

| 预测期间 | FCFF 预测值 | FCFF 数据来源与属性 | PV 折现现值 | PV 数据来源与属性 |
| :--- | :--- | :--- | :--- | :--- |
| FY1E | $98.00B | USD · FY1E · Derived from base FCFF (70000000000) × (1 + 40.0%) · 2025/01/15 · 估算 · 派生值 · 置信度 80.00% | $87.50B | — |
| FY2E | $137.20B | USD · FY2E · Derived from Year 1 FCFF × (1 + 40.0%) · 2025/01/15 · 估算 · 派生值 · 置信度 70.00% | $109.38B | — |
| FY2027E | $172.19B | USD · FY2027E · Derived from prior FCFF projection × (1 + 0.2550) · 2025/01/15 · 估算 · 派生值 · 置信度 70.00% | $122.56B | — |
| FY2028E | $216.09B | USD · FY2028E · Derived from prior FCFF projection × (1 + 0.2550) · 2025/01/15 · 估算 · 派生值 · 置信度 70.00% | $137.29B | — |
| FY2029E | $271.20B | USD · FY2029E · Derived from prior FCFF projection × (1 + 0.2550) · 2025/01/15 · 估算 · 派生值 · 置信度 70.00% | $153.84B | — |

###### 情景推导步骤

1. [bear] FCFF projections (FY1E, FY2E, FY2027E, FY2028E, FY2029E) = [Decimal('98000000000.00'), Decimal('137200000000.00'), Decimal('172186000000.00'), Decimal('216093430000.00'), Decimal('271197254650.00')]
2. [bear] PV year 1 (t=1.0000) = 98000000000.00 / (1 + 0.12)^1.0000 = 87500000000.00
3. [bear] PV year 2 (t=2.0000) = 137200000000.00 / (1 + 0.12)^2.0000 = 109375000000.00
4. [bear] PV year 3 (t=3.0000) = 172186000000.00 / (1 + 0.12)^3.0000 = 122558593750.00
5. [bear] PV year 4 (t=4.0027) = 216093430000.00 / (1 + 0.12)^4.0027 = 137288648019.05
6. [bear] PV year 5 (t=5.0027) = 271197254650.00 / (1 + 0.12)^5.0027 = 153836833271.34
7. [bear] TV = 271197254650.00 × (1 + 0.03) / (0.12 - 0.03) = 3103701914327.78
8. [bear] PVTV = 3103701914327.78 / (1 + 0.12)^5.0027 = 1760577091883.16
9. [bear] EV = 610559075040.39 + 1760577091883.16 = 2371136166923.55
10. [bear] Equity = 2371136166923.55 - 59400000000 + 24000000000 = 2335736166923.55
11. [bear] Price/share = 2335736166923.55 / 4940000000 = 472.82

##### 【基准情景】

- **加权资本成本 (WACC)**：10.00%
- **永续增长率 (Terminal Growth)**：3.00%
- **预测期增长率 (Growth Rate)**：30.00%

###### 企业价值至股权价值桥梁

| 财务与估值科目 | 金额 / 数值 | 说明 |
| :--- | :--- | :--- |
| 企业价值 (Enterprise Value, EV) | **$3.44T** | 预测期现金流现值之和 + 终端价值现值 |
| 终端价值 (Terminal Value, TV) | $4.44T | 永续年金模型估算期末价值 |
| 终端价值现值 (PV of TV) | $2.75T | TV 按 WACC 折现至当前 |
| 现金及现金等价物 (+) | $24.00B | 资产负债表货币资金 |
| 总债务 (−) | $59.40B | 资产负债表长短期有息负债 |
| 净负债 (Net Debt) | $35.40B | 总债务 − 现金 |
| 股权价值 (Equity Value) | **$3.40T** | EV − 净负债 (EV + 现金 − 总债务) |
| 稀释后总股数 | 4.940B 股 | 最新稀释股本 |
| **每股公允价值** | **$688.21** | 股权价值 / 稀释总股数 |
| 预期上行空间 | +100.16% | （每股价值 − 当前价）/ 当前价 |
| 现价相对估值溢折价 | -50.04% | 现价相比该情景公允价值之溢折比率 |

###### 五年 FCFF 预测与折现明细

| 预测期间 | FCFF 预测值 | FCFF 数据来源与属性 | PV 折现现值 | PV 数据来源与属性 |
| :--- | :--- | :--- | :--- | :--- |
| FY1E | $98.00B | USD · FY1E · Derived from base FCFF (70000000000) × (1 + 40.0%) · 2025/01/15 · 估算 · 派生值 · 置信度 80.00% | $89.09B | — |
| FY2E | $137.20B | USD · FY2E · Derived from Year 1 FCFF × (1 + 40.0%) · 2025/01/15 · 估算 · 派生值 · 置信度 70.00% | $113.39B | — |
| FY2027E | $178.36B | USD · FY2027E · Derived from prior FCFF projection × (1 + 0.30) · 2025/01/15 · 估算 · 派生值 · 置信度 70.00% | $134.00B | — |
| FY2028E | $231.87B | USD · FY2028E · Derived from prior FCFF projection × (1 + 0.30) · 2025/01/15 · 估算 · 派生值 · 置信度 70.00% | $158.33B | — |
| FY2029E | $301.43B | USD · FY2029E · Derived from prior FCFF projection × (1 + 0.30) · 2025/01/15 · 估算 · 派生值 · 置信度 70.00% | $187.11B | — |

###### 情景推导步骤

1. [base] FCFF projections (FY1E, FY2E, FY2027E, FY2028E, FY2029E) = [Decimal('98000000000.00'), Decimal('137200000000.00'), Decimal('178360000000.00'), Decimal('231868000000.00'), Decimal('301428400000.00')]
2. [base] PV year 1 (t=1.0000) = 98000000000.00 / (1 + 0.10)^1.0000 = 89090909090.91
3. [base] PV year 2 (t=2.0000) = 137200000000.00 / (1 + 0.10)^2.0000 = 113388429752.07
4. [base] PV year 3 (t=3.0000) = 178360000000.00 / (1 + 0.10)^3.0000 = 134004507888.81
5. [base] PV year 4 (t=4.0027) = 231868000000.00 / (1 + 0.10)^4.0027 = 158327615304.89
6. [base] PV year 5 (t=5.0027) = 301428400000.00 / (1 + 0.10)^5.0027 = 187114454451.23
7. [base] TV = 301428400000.00 × (1 + 0.03) / (0.10 - 0.03) = 4435303600000.00
8. [base] PVTV = 4435303600000.00 / (1 + 0.10)^5.0027 = 2753255544068.14
9. [base] EV = 681925916487.91 + 2753255544068.14 = 3435181460556.05
10. [base] Equity = 3435181460556.05 - 59400000000 + 24000000000 = 3399781460556.05
11. [base] Price/share = 3399781460556.05 / 4940000000 = 688.21

##### 【乐观情景】

- **加权资本成本 (WACC)**：8.00%
- **永续增长率 (Terminal Growth)**：4.00%
- **预测期增长率 (Growth Rate)**：34.50%

###### 企业价值至股权价值桥梁

| 财务与估值科目 | 金额 / 数值 | 说明 |
| :--- | :--- | :--- |
| 企业价值 (Enterprise Value, EV) | **$6.67T** | 预测期现金流现值之和 + 终端价值现值 |
| 终端价值 (Terminal Value, TV) | $8.68T | 永续年金模型估算期末价值 |
| 终端价值现值 (PV of TV) | $5.91T | TV 按 WACC 折现至当前 |
| 现金及现金等价物 (+) | $24.00B | 资产负债表货币资金 |
| 总债务 (−) | $59.40B | 资产负债表长短期有息负债 |
| 净负债 (Net Debt) | $35.40B | 总债务 − 现金 |
| 股权价值 (Equity Value) | **$6.63T** | EV − 净负债 (EV + 现金 − 总债务) |
| 稀释后总股数 | 4.940B 股 | 最新稀释股本 |
| **每股公允价值** | **$1,343.09** | 股权价值 / 稀释总股数 |
| 预期上行空间 | +290.63% | （每股价值 − 当前价）/ 当前价 |
| 现价相对估值溢折价 | -74.40% | 现价相比该情景公允价值之溢折比率 |

###### 五年 FCFF 预测与折现明细

| 预测期间 | FCFF 预测值 | FCFF 数据来源与属性 | PV 折现现值 | PV 数据来源与属性 |
| :--- | :--- | :--- | :--- | :--- |
| FY1E | $98.00B | USD · FY1E · Derived from base FCFF (70000000000) × (1 + 40.0%) · 2025/01/15 · 估算 · 派生值 · 置信度 80.00% | $90.74B | — |
| FY2E | $137.20B | USD · FY2E · Derived from Year 1 FCFF × (1 + 40.0%) · 2025/01/15 · 估算 · 派生值 · 置信度 70.00% | $117.63B | — |
| FY2027E | $184.53B | USD · FY2027E · Derived from prior FCFF projection × (1 + 0.3450) · 2025/01/15 · 估算 · 派生值 · 置信度 70.00% | $146.49B | — |
| FY2028E | $248.20B | USD · FY2028E · Derived from prior FCFF projection × (1 + 0.3450) · 2025/01/15 · 估算 · 派生值 · 置信度 70.00% | $182.39B | — |
| FY2029E | $333.83B | USD · FY2029E · Derived from prior FCFF projection × (1 + 0.3450) · 2025/01/15 · 估算 · 派生值 · 置信度 70.00% | $227.15B | — |

###### 情景推导步骤

1. [bull] FCFF projections (FY1E, FY2E, FY2027E, FY2028E, FY2029E) = [Decimal('98000000000.00'), Decimal('137200000000.00'), Decimal('184534000000.00'), Decimal('248198230000.00'), Decimal('333826619350.00')]
2. [bull] PV year 1 (t=1.0000) = 98000000000.00 / (1 + 0.08)^1.0000 = 90740740740.74
3. [bull] PV year 2 (t=2.0000) = 137200000000.00 / (1 + 0.08)^2.0000 = 117626886145.40
4. [bull] PV year 3 (t=3.0000) = 184534000000.00 / (1 + 0.08)^3.0000 = 146489038764.42
5. [bull] PV year 4 (t=4.0027) = 248198230000.00 / (1 + 0.08)^4.0027 = 182394646044.21
6. [bull] PV year 5 (t=5.0027) = 333826619350.00 / (1 + 0.08)^5.0027 = 227148887897.65
7. [bull] TV = 333826619350.00 × (1 + 0.04) / (0.08 - 0.04) = 8679492103100.00
8. [bull] PVTV = 8679492103100.00 / (1 + 0.08)^5.0027 = 5905871085338.98
9. [bull] EV = 764400199592.42 + 5905871085338.98 = 6670271284931.40
10. [bull] Equity = 6670271284931.40 - 59400000000 + 24000000000 = 6634871284931.40
11. [bull] Price/share = 6634871284931.40 / 4940000000 = 1343.09

#### 终值敏感性分析矩阵 (3×3 Sensitivity Matrix)

- **基准终值占比**：80.2%
- ⚠️ **终值依赖风险警报**：终值占比高达 80.2% (>80%)，估值对折现率与永续增长率高度敏感。

| WACC \ g | 2.5% | 3.0% (基准) | 3.5% |
| :--- | :---: | :---: | :---: |
| **9.0%** | **$760.40** (TV: 81.5%) | **$815.81** (TV: 82.7%) | **$881.29** (TV: 84.0%) |
| **10.0% (基准)** | **$648.53** (TV: 79.0%) | **$688.21** (TV: 80.2%) | **$734.00** (TV: 81.4%) |
| **11.0%** | **$563.30** (TV: 76.5%) | **$592.84** (TV: 77.7%) | **$626.33** (TV: 78.9%) |

---

## 四、免责声明与使用条款

- **仅供参考**：本报告及估值结果仅用于教育、学术研究及量化财务模型验证，**不构成任何投资建议、买卖要约或财务咨询**。
- **风险提示**：股票市场具有固有波动风险，未来实际业绩、宏观利率、资本开支与自由现金流可能与模型假设产生重大偏差。
- **数据准确性**：数据来源于第三方公开金融数据接口，平台已标注各指标之基准日期、来源类别与置信度，但不对外部数据之完整性、时效性及绝对准确性作法律担保。

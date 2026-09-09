# Acceptance Report: Valuation Markdown Export Feature

**Date**: 2026-09-10  
**Feature Slug**: `markdown-export`  
**Issue**: `.scratch/markdown-export/issues/01-markdown-export.md` (`Status: resolved`)  
**Task Goal**: Add a feature to export completed valuation results as Markdown formatted text, covering 100% of the information on the valuation page.

---

## 1. Executive Summary

- **Feature Delivered**: Added a discoverable Chinese action button `⭳ 导出 Markdown` in the hero card header of `/valuation/[ticker]`, downloading a standalone, publication-grade UTF-8 `.md` document named `{ticker}_valuation_{timestamp}.md`.
- **Zero Extra Network Requests**: The export executes 100% in-memory from the currently rendered valuation state, triggering 0 additional API requests to the backend or upstream data providers across all states.
- **Complete Information Coverage**:
  - Full company identity, market quotes, quote timestamps, financial statement as-of dates, LIVE/DEMO data modes, data quality ratings, and system warnings.
  - Separate explicit `报告导出时间` distinct from financial and market timestamps.
  - Model assumptions with explicit parameter status (`用户覆盖生效` vs `系统默认基准`).
  - All four valuation models (Forward P/E, EV/EBITDA, FCF Yield, DCF) with formulas, scenario target prices, and **non-DCF scenario intermediate calculation metrics** (`前瞻 EPS`, `目标倍数`, `EV`, `净负债`, `股权价值`, `前瞻 FCFE`, `收益率`).
  - Full input metric provenance table: units, periods, sources, source types, as-of dates, confidence levels, estimation flags, and notes.
  - Exact unavailable reasons and warnings preserved for unavailable models (e.g. TSM currency isolation).
  - Complete DCF 5-year projections and EV-to-equity bridges across Bear, Base, and Bull scenarios.
  - Composite target price range, MOS %, upside %, Chinese valuation classification, weights distribution, and step-by-step calculation steps.
  - Educational disclaimers and terms of use.
- **Table & Syntax Escaping**: Comprehensive escaping of backticks `` ` ``, pipes `|`, and newlines (`\r\n`, `\n`) across table cells, headings, and notes, completely preventing Markdown table syntax corruption.
- **State Integrity Verified**:
  - Unsaved form inputs (e.g. typing `99.5` without clicking submit) are **never** exported; the active applied valuation and effective assumptions are strictly preserved.
  - During recalculation and loading, the export button is disabled.
  - Ticker switching (e.g. NVDA -> AAPL) completely isolates data with zero stale data leakage.

---

## 2. Section-to-Export Coverage Matrix

| Valuation Page Section / Component | UI Visual Content / Fields | Exported Markdown Document Section | Formatting & Treatment |
| :--- | :--- | :--- | :--- |
| **Hero Heading & Metadata** | Ticker, Company Name, Currency, As-of date, Provider label | `### 基本信息与行情基准` | Bulleted list, escaped values, clear key-value labels |
| **Market Reference Quote** | Current price, Quote timestamp (or delay notice) | `### 基本信息与行情基准` | Formatted price with currency symbol (`$224.15`), quote datetime |
| **Data Freshness / Mode Banner** | DEMO fixture banner vs LIVE market data banner, Data quality rating | `### 基本信息与行情基准` | Explicit data mode (`LIVE 真实市场...` / `DEMO 固定演示...`), Chinese quality badge |
| **Export Generation Timestamp** | N/A (Generated at export time) | `### 基本信息与行情基准` | Explicit `报告导出时间` distinct from data as-of dates |
| **Data Warnings Panel** | Global data warnings and notices (`data.warnings`) | `### 数据提醒` | Bulleted list with warning icons (`⚠`) |
| **Composite Valuation Summary** | Target price range (Low, Base, High), MOS %, Upside %, Classification label | `## 一、综合估值结论` | Formatted summary table, Chinese classification, signed % |
| **Composite Model Weights & Scopes** | Active model count (`X / 4`), model weight distribution, cash flow scope note | `#### 模型权重分布` | Markdown table with model name, key, normalized weight %, and status |
| **Composite Calculation Steps** | Step-by-step mathematical synthesis steps | `#### 综合计算推导过程` | Numbered list matching backend calculation steps |
| **Model Assumptions & Overrides** | Target P/E, EV/EBITDA multiple, FCF yield, WACC, Terminal growth, sources | `## 二、估值假设与情景参数` | Comparison table showing Low/Base/High, **生效状态 (`用户覆盖生效` / `系统默认基准`)**, and sources |
| **Model 1: Forward P/E** | Formula, formula description, Low/Base/High targets, upside %, premium %, **intermediates (EPS, target P/E)**, input metrics table, assumption metrics table, calculation steps | `### 3.1 市盈率估值 (forward_pe)` | Full scenario table with **核心计算中间值**, full input metrics table with provenance, assumption table, steps |
| **Model 2: EV / EBITDA** | Formula, formula description, Low/Base/High targets, upside %, premium %, **intermediates (EV, Equity Value, Net Debt, multiple)**, input metrics table, assumption metrics table, calculation steps | `### 3.2 EV / EBITDA 估值 (ev_ebitda)` | Full scenario table with **核心计算中间值**, full input metrics table with provenance, assumption table, steps |
| **Model 3: FCF Yield** | Formula, formula description, Low/Base/High targets, upside %, premium %, **intermediates (FCFE, Yield Rate, Equity Value)**, input metrics table, assumption metrics table, calculation steps | `### 3.3 FCF 收益率估值 (fcf_yield)` | Full scenario table with **核心计算中间值**, full input metrics table with provenance, assumption table, steps |
| **Model 4: DCF** | Formula, formula description, Low/Base/High targets, upside %, premium %, intermediates, input metrics table, assumption metrics table, calculation steps | `### 3.4 现金流折现（DCF） (dcf)` | Full scenario table with **核心计算中间值**, full input metrics table with provenance, assumption table, steps |
| **Unavailable Models (e.g. TSM)** | Unavailable badge, exact unavailable reason, warnings | `### 3.X 模型名称` | Explicit `❌ 不可用` status, exact reason blockquote, and **`> **模型警示与说明**：`** list |
| **DCF Scenarios: Core Rates** | WACC, Terminal growth, Growth rate | `##### 【悲观/基准/乐观情景】` | Rates formatted as percentages with decimals |
| **DCF Scenarios: Valuation Bridge** | EV, TV, PVTV, Cash, Debt, Net Debt, Equity, Shares, Price/share, Upside, Premium | `###### 企业价值至股权价值桥梁` | Markdown table with formatted financial figures ($B, $T, shares, /share) |
| **DCF Scenarios: 5-Year Projections**| 5-year forecast periods, FCFF values, FCFF provenance, PV values, PV provenance | `###### 五年 FCFF 预测与折现明细` | Markdown table mapping each forecast period, FCFF, PV, and detailed provenance |
| **DCF Scenarios: Step Derivations** | Mathematical intermediate steps per scenario | `###### 情景推导步骤` | Numbered list of scenario steps |
| **Page Disclaimer** | Educational and model verification disclaimer | `## 四、免责声明与使用条款` | Standard risk, non-advice, and third-party data disclaimers |

---

## 3. Test Commands, Working Directories, and Exit Codes

### 3.1 Frontend Typecheck
- **Command**: `npm run typecheck`
- **Cwd**: `D:\workshop\stock-valuation\frontend`
- **Exit Code**: `0`
- **Output**:
  ```
  > frontend@0.1.0 typecheck
  > tsc --noEmit
  ```

### 3.2 Frontend Lint
- **Command**: `npm run lint`
- **Cwd**: `D:\workshop\stock-valuation\frontend`
- **Exit Code**: `0`
- **Output**:
  ```
  > frontend@0.1.0 lint
  > eslint .
  ```

### 3.3 Frontend Production Build
- **Command**: `npm run build`
- **Cwd**: `D:\workshop\stock-valuation\frontend`
- **Exit Code**: `0`
- **Output**:
  ```
  ▲ Next.js 15.4.3
  Creating an optimized production build ...
  ✓ Compiled successfully in 2000ms
  Linting and checking validity of types ...
  Collecting page data ...
  Generating static pages (5/5) ...
  ✓ Generating static pages (5/5)
  Finalizing page optimization ...
  ```

### 3.4 Formatter & Escaping Unit Tests
- **Command**: `node .scratch/markdown-export/test_export_formatter.js`
- **Cwd**: `D:\workshop\stock-valuation`
- **Exit Code**: `0`
- **Assertions Passed**:
  - `[Test 1]`: `escapeTableCell` & `escapeMarkdownText` safely escape backticks (`` ` ``), pipes (`|`), and newlines (`\r\n`, `\n`).
  - `[Test 2]`: `buildExportFilename` produces valid safe filenames matching `{TICKER}_valuation_{YYYYMMDD}_{HHMMSS}.md` and preserves class dots (e.g. `BRK.B`).
  - `[Test 3]`: `formatMetricProvenance` properly formats financial metric units, periods, sources, confidence, and estimation flags.
  - `[Test 4]`: Full 4-model validation on live `NVDA` response (title, prices, warnings, composite, assumptions with `生效状态`, 4 models with scenario intermediates, DCF 3 scenarios, bridge tables, disclaimer).
  - `[Test 5]`: Validation on ADR `TSM` response with currency isolation (Forward P/E available, EV/EBITDA/FCF/DCF unavailable with exact reasons and warnings).
  - `[Test 6]`: Validation on `AVGO` offline DEMO fixture.
  - `[Test 7]`: Edge-case testing with injected backticks, pipes, and newlines in company name, formulas, sources, and notes validating table column count integrity across all rows.
  - Dual sample save paths: Verified saves to both `.scratch/markdown-export/` and `.scratch/markdown-export/evidence/`.

### 3.5 Playwright Browser Acceptance & Zero Network Call Tests
- **Command**: `python .scratch/markdown-export/browser_test_export.py`
- **Cwd**: `D:\workshop\stock-valuation`
- **Exit Code**: `0`
- **Assertions Passed**:
  - `[Test 1] NVDA Baseline`: Page loads, `⭳ 导出 Markdown` button is visible and enabled. Click triggers browser download of `NVDA_valuation_*.md`. **Network requests during export click: 0**. Verified exact baseline numerical values (`$186.20`, `20.00x`, `系统默认基准`, intermediates).
  - `[Test 2] Unsaved Edit Proof`: User types `99.5` into P/E override input without submitting. Export is triggered. Verified `99.5` is **never** exported; old applied baseline `$186.20` and `20.00x` are strictly preserved. **Network requests: 0**.
  - `[Test 3] Applied Override Exact Numbers`: User fills `25` and submits override. Verified export button is disabled during recalculation. Exported Markdown reflects exact changed target: `**$232.75**` and `| 前瞻市盈率 (P/E Multiple) | 22.50x | **25.00x** | 27.50x | 用户覆盖生效 | User override |`. **Network requests: 0**.
  - `[Test 4] Reset Restores Defaults`: User clicks `↺ 重置默认`. Exported Markdown restores exact baseline: `**$186.20**` and `系统默认基准`. **Network requests: 0**.
  - `[Test 5] Ticker Switch to AAPL`: Switched to AAPL. Downloaded file is `AAPL_valuation_*.md`. Contains `# Apple Inc. (AAPL)` and AAPL prices, with zero stale NVDA data. **Network requests: 0**.
  - `[Test 6] TSM ADR Currency Isolation`: Preserves Forward P/E availability and EV/EBITDA, FCF Yield, and DCF exact currency mismatch reasons and warnings. **Network requests: 0**.
  - `[Test 7] Error State Safety`: On invalid ticker route (`/valuation/INVALIDXYZ999`), error panel is displayed; export button is not rendered (count == 0), preventing any bogus data export.

---

## 4. Evidence Artifacts & Verified Paths

Every listed path below has been verified to exist on disk:

| Artifact Path | Description | Verified Status |
| :--- | :--- | :--- |
| `.scratch/markdown-export/evidence/sample_nvda_export.md` | Primary NVDA full sample export in evidence directory | ✅ Exists (30,915 bytes) |
| `.scratch/markdown-export/evidence/sample_tsm_export.md` | TSM ADR sample export in evidence directory | ✅ Exists (8,591 bytes) |
| `.scratch/markdown-export/sample_nvda_export.md` | NVDA full sample export in scratch directory | ✅ Exists (30,915 bytes) |
| `.scratch/markdown-export/sample_tsm_export.md` | TSM ADR sample export in scratch directory | ✅ Exists (8,591 bytes) |
| `.scratch/markdown-export/evidence/01_nvda_page.png` | Screenshot of NVDA valuation hero card with export button | ✅ Exists (241,825 bytes) |
| `.scratch/markdown-export/evidence/02_tsm_page.png` | Screenshot of TSM valuation page with unavailable models | ✅ Exists (244,808 bytes) |
| `.scratch/markdown-export/evidence/03_error_page.png` | Screenshot of error page confirming absence of export action | ✅ Exists (91,226 bytes) |
| `.scratch/markdown-export/evidence/NVDA_valuation_20260910_010617.md` | Downloaded NVDA export from automated test run | ✅ Exists (30,915 bytes) |
| `.scratch/markdown-export/evidence/AAPL_valuation_20260910_010617.md` | Downloaded AAPL export from automated test run | ✅ Exists (16,337 bytes) |
| `.scratch/markdown-export/evidence/TSM_valuation_20260910_010618.md` | Downloaded TSM export from automated test run | ✅ Exists (8,591 bytes) |

---

## 5. Sample Markdown Export Snippet (`sample_nvda_export.md`)

```markdown
# NVIDIA Corporation (NVDA) 估值分析报告

> 本报告由美股估值分析平台自动生成，包含当前所有四套独立估值模型、综合评估、输入明细及数据来源。

### 基本信息与行情基准

- **股票代码**：NVDA
- **公司名称**：NVIDIA Corporation
- **报价币种**：USD
- **市场参考价**：$224.15
- **行情报价时间**：2026/09/09 17:05:51（可能存在延迟）
- **财报基准日**：2026/09/09
- **数据源提供方**：公开金融数据接口
- **数据模式**：LIVE 真实市场与财务数据（非实时保证，行情可能存在延迟）
- **数据质量评级**：中等质量
- **报告导出时间**：2026/09/10 01:06:17

---

## 一、综合估值结论

| 综合指标 | 数值 / 评定 | 说明 |
| :--- | :--- | :--- |
| **综合公允价值区间** | **低位 $138.98 · 基准 $171.61 · 高位 $242.94** | 四模型加权综合目标价 |
| **估值判断** | **严重高估** | 现价对比基准公允价值分类 |
| **安全边际 (MOS)** | **-30.61%** | （基准公允价值 − 当前价）/ 基准公允价值 |
| **预期上行 / 下跌空间** | **-23.44%** | （基准公允价值 − 当前价）/ 当前价 |
| **有效模型数量** | **4 / 4** | 参与综合权重的模型数量 |
| **现金流口径** | **FCF Yield = FCFE · DCF = FCFF** | 权益自由现金流 vs 企业自由现金流口径隔离 |

---

## 二、估值假设与情景参数

| 参数项 | 低位 / 悲观 | 基准 (Base) | 高位 / 乐观 | 生效状态 | 来源 / 依据 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 前瞻市盈率 (P/E Multiple) | 18.00x | **20.00x** | 22.00x | 系统默认基准 | Configured fallback: 18x/20x/22x (low/base/high) |
| EV / EBITDA 倍数 | 18.00x | **22.00x** | 26.00x | 系统默认基准 | Configured fallback: 18x/22x/26x (low/base/high) |
| FCF 目标收益率 (FCF Yield) | 5.50% | **5.00%** | 4.50% | 系统默认基准 | Configured fallback: 5.5%/5.0%/4.5% (low=high yield=conservative) |
| DCF 加权资本成本 (WACC) | 12.00% | **10.00%** | 8.00% | 系统默认基准 | Configured fallback: 12%/10%/8% (bear/base/bull) |
| DCF 永续增长率 (Terminal Growth) | 3.00% | **3.00%** | 4.00% | 系统默认基准 | 长期 GDP 增长锚定上限 5% |

---

## 三、四套独立估值模型明细

### 3.1 市盈率估值 (forward_pe)

- **模型可用状态**：✅ 可用
- **数据质量**：中等质量
- **计算公式**：`Price = Forward EPS × Target P/E`
- **公式说明**：Price target derived from forward EPS multiplied by a target P/E. Historical median is used when available; otherwise the configured fallback applies.

#### 估值情景目标价

| 情景 | 每股公允价值 | 预期上行空间 | 现价相对估值溢折价 | 核心计算中间值 (Intermediates) |
| :--- | :--- | :--- | :--- | :--- |
| 低位 (Low) | $167.58 | -25.24% | +33.76% | 前瞻 EPS: 9.31 · 目标 P/E: 18.00x |
| **基准 (Base)** | **$186.20** | **-16.93%** | **+20.38%** | **前瞻 EPS: 9.31 · 目标 P/E: 20.00x** |
| 高位 (High) | $204.82 | -8.62% | +9.44% | 前瞻 EPS: 9.31 · 目标 P/E: 22.00x |
| 当前参考价 | $224.15 | — | — | 现价基准 |
```

---

## 6. Service & Process State Verification

- **Frontend Production Service**:
  - Port: `3000`
  - Real Process ID (PID): `30252`
  - Process Name: `node`
  - CommandLine: `"node" "D:\workshop\stock-valuation\frontend\node_modules\next\dist\bin\next" start -p 3000`
  - CreationDate: `2026/09/10 01:04:20`
  - Next.js Build ID: `lTzUhlZaU4kBV7dQwv1cX`
  - Health: Verified HTTP 200 OK responding to browser and curl requests.
- **Backend API Service**:
  - Port: `8002`
  - Real Process ID (PID): `50736`
  - Process Name: `python`
  - CommandLine: `"C:\Users\Wayne\AppData\Roaming\uv\python\cpython-3.12-windows-x86_64-none\python.exe" -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8002`
  - CreationDate: `2026/09/10 00:26:55`
  - Health: Completely untouched and healthy. Responding to live API queries.

---

## 7. Modified Files & Source SHA-256 Hashes

- **Git Baseline**: `master` branch with no prior commits (initial repository state).
- **Source File Hashes (SHA-256)**:
  - `frontend/lib/exportMarkdown.ts`: `B8FE950B14CB3BE44422B31FC4086FC5711DADB62109A254E6CA8BB008ED3672`
  - `frontend/app/valuation/[ticker]/page.tsx`: `2C4CDF8253062C114E0E037C2BEB485C1E732CAC07F16D09CF17182386B5199E`
  - `frontend/app/globals.css`: `AF02D70EF73112CC4F7E6F80475E13D0F3F8CB0D9EF0821FDB2E677765C4F626`
  - `frontend/.next/BUILD_ID`: `EC7B86A3EA17911BABC1A6B8EC5C0C724A33278D3419A4BDCA4F007EC4FBDB16` (value: `lTzUhlZaU4kBV7dQwv1cX`)
- **Support & Test Files**:
  - `.scratch/markdown-export/issues/01-markdown-export.md`
  - `.scratch/markdown-export/test_export_formatter.js`
  - `.scratch/markdown-export/browser_test_export.py`
  - `frontend/README.md`
  - `README.md`

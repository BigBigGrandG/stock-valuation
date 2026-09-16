# Project Constraints & Standards

本指南记录项目长期稳定的领域、架构、数据与财务约束。Git 安全与验证流程分别见 `repository-safety.md` 和 `verification.md`。

## 1. Core Architecture & Domain Invariants

- **定位与目标**：高确定性、可溯源的美股上市公司估值分析引擎，采用 FastAPI (Python 3.12+) 后端与 Next.js / React / TypeScript 前端。
- **架构边界**：保持现有 provider → service / normalization → projection / valuation engine → API / export 的职责分层；局部需求不应触发无关的整体重构。
- **业务计算位置**：估值与核心财务计算由后端负责，前端只展示、交互和导出，不维护另一套独立估值公式。
- **任意美股标的查询**：系统面向真实全量美股上市公司，不得退回静态白名单，也不得把 demo fixture 改名复制给其他股票。
- **模型独立性**：四种模型分别输出 Low / Base / High；某模型 unavailable 时不影响、重分配或改写其他模型，不生成跨模型综合目标价。

## 2. Valuation Model Invariants

### Forward P/E

- 基于 forward EPS 与目标 P/E。
- 历史 forward P/E 中位数可作为优先倍数来源；缺失时使用明确配置或用户 override。

### EV/EBITDA

- 基于 forward EBITDA、目标倍数、净债务和 diluted shares 得到每股股权价值。
- 必须保持企业价值与股权价值之间的净债务桥接。

### FCF Yield

- 仅使用 FCFE。
- 不得使用 WACC 对 FCFE 进行折现。
- yield 与估值方向相反：更高 yield 对应更低估值。

### DCF

- 仅使用 FCFF。
- 使用五年预测、逐年折现与 terminal value。
- 企业价值转股权价值时正确处理 debt / cash。
- WACC 必须大于 terminal growth。
- TTM 数据不得直接改标签伪装成 forecast period。

具体公开公式与当前行为以 `README.md` 为准；实现发生变化时应同步保持文档和测试一致。

## 3. Precision & Provenance

- 后端核心业务计算使用 Python `Decimal`，JSON 以高精度字符串传输。
- 不允许前端对后端估值结果做二次业务计算。
- 缺失财务字段不得无根据补零。
- 不得编造目标价、汇率、财务数据或来源。
- 财务指标应保留适用的结构化 provenance，包括：
  - `value`
  - `unit`
  - `period`
  - `source`
  - `source_type`
  - `as_of`
  - `confidence`
  - `is_estimated`
- unavailable 模型必须保留明确、可解释的 `unavailable_reason`。

涉及财务变更时，应能够沿以下数据链回溯：

`source → normalizer/service → projection → valuation engine → API/export`

## 4. Data Provider Boundaries

- 默认运行模式使用实时数据；当前 live provider 为无密钥 `yfinance`。
- demo 数据只在显式 `DATA_PROVIDER=demo` 或请求 `?provider=demo` 时使用。
- `AvgoFixtureProvider` 是固定日期的 AVGO 离线 fixture，仅用于确定性测试与演示。
- live provider 失败时不得静默回退到 demo。
- demo fixture 不得复制、改名或伪装成其他 ticker 的真实数据。
- provider 返回的数据必须经过现有 validation / normalization 边界后再进入估值逻辑。

## 5. Financial Applicability

系统支持符合范围的美股上市公司，但不保证每只股票四个模型均有有效数值。

### Profitable operating companies

如 `NVDA`、`AAPL`、`MSFT`、`AVGO`、`KO`：四种模型可独立运行，实际 availability 取决于各自输入是否完整且经济学上适用。

### US-listed foreign ADRs

如 `TSM`：

- Forward P/E 可使用美国市场 USD 报价及每 ADS 的 USD forward EPS。
- 当财报币种与交易币种不一致且缺乏可信折算时，依赖财报币种的模型应返回 unavailable。
- 不得自行捏造未经审计的 FX conversion。

### Financial institutions / banks

如 `JPM`、`BAC`、`C`：

- 存款负债属于核心经营结构，传统 EV/EBITDA 与 FCFF DCF 通常不具经济适用性。
- 不适用模型应明确返回 `available: false` 与原因。
- Forward P/E 等仍可在输入适用时独立运行。

### Loss-makers / early-stage companies

如 `RIVN`、`SNAP`：

- 依赖正收益、正 EBITDA 或正现金流的模型在条件不满足时返回 unavailable。
- 不应因单个模型不适用导致整个公司请求崩溃或返回通用错误。

### Unsupported asset classes

ETF、crypto、mutual fund、SPAC 或不符合系统范围的非美股证券，通过类型化错误拒绝；当前公开错误行为以 `README.md` 为准。

## 6. Forecast Alignment

- 预测财年应使用 upstream `nextFiscalYearEnd` 等可验证时间信息对齐。
- 不得无条件使用 `year + 1` 推断下一财年。
- forecast、TTM、historical period 必须保持语义区别。

## 7. Public Contract

当任务影响以下内容时，应检查并同步 `README.md`：

- 公开 API；
- request / response schema；
- model formulas；
- provider behavior；
- setup / run instructions；
- error taxonomy；
- 用户可见能力或限制。

## 8. Verification & Repository Safety

不要在本文件复制操作性流程。

- 验证范围、标准命令和证据规则：`docs/agents/verification.md`
- Git baseline、dirty / untracked 保护和破坏性操作限制：`docs/agents/repository-safety.md`

## 9. Historical Artifacts

`.scratch/` 与根 `HANDOFF.md` 中可能保留旧任务的 spec、验收记录、报告和历史工作流命名。这些内容可作为历史证据，但不自动代表当前代码状态，也不定义当前 Agent 执行方式。

对于当前工作，以当前代码、当前 diff、当前验证输出以及本文件定义的领域不变量为准。

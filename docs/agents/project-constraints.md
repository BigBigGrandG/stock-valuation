# Project Constraints & Standards

本指南记录本项目的核心领域约束、架构不变量、数据与财务准则、版本库安全策略以及标准工具链验证命令。

## 1. Core Architecture & Domain Invariants (核心架构与领域不变量)

- **定位与目标**：高确定性、可溯源的美股上市公司估值分析引擎，采用 FastAPI (Python 3.12+) 后端与 Next.js (TypeScript) 前端。
- **任意美股标的查询**：系统面向真实全量美股上市公司（如 `NVDA`、`AAPL`、`MSFT`、`AVGO`、`KO`、`JPM`、`TSM`、`RIVN` 等），绝不退回至任何静态白名单，严禁将演示数据（如 AVGO fixture）重命名复制给其他股票。
- **模型适用性与数值约束**：支持任意美股标的查询，**但不保证每只股票四个模型均产生数值**；仅数据完整且业务适用的模型产生有效结果，不适用或缺少必要输入的模型诚实隔离并标记原因（`available: false`），综合估值仅在有效模型之间动态重归一化权重。
- **数据源与离线隔离**：
  - 生产与默认运行模式采用无密钥实时行情源（固定依赖 `yfinance`）。
  - 离线演示数据（`AvgoFixtureProvider`，基准日 2025-01-15）仅在显式配置 `DATA_PROVIDER=demo` 或请求携带 `?provider=demo` 时生效，专用于网络隔离下的确定性自动化测试与离线演示，严禁在线查询时静默回退。
- **四模型与综合估值稳定约束**：
  - **Forward P/E**：基于分析师预期或历史中位数 EPS 及目标倍数计算。
  - **EV/EBITDA**：基于预期 EBITDA、目标倍数及净债务扣除，折算每股股权价值。
  - **FCF yield**：仅基于 FCFE（股权自由现金流），严禁使用 WACC 折现。
  - **DCF**：仅基于 FCFF（企业自由现金流），包含五年预测折现及终值折现。
  - **Composite (综合估值)**：仅纳入数值完整且为正的有效模型输出，动态重新分配权重。
  - 详细公式、情景与分类阈值以权威规范文档为准，不在此复制易陈旧的静态实现常量。
- **计算精度与溯源元数据**：
  - 后端业务计算全量采用 Python `Decimal` 确定性运算，JSON 接口以高精度字符串传输，禁止前端做二次业务估值计算。
  - 所有指标具备结构化元数据（`value`、`unit`、`period`、`source`、`source_type`、`as_of`、`confidence`、`is_estimated`）。严禁对缺失财务字段进行无根据补零。

## 2. Financial Applicability & Robust Isolation (财务适用性与边界隔离)

系统依据公司类型与财务现实执行细粒度隔离，杜绝编造数据或无端崩溃：

- **正常盈利企业**（如 `NVDA`、`AAPL`、`MSFT`、`KO`）：四种模型与综合估值完整执行。
- **美股上市外国 ADR**（如纽交所代码 `TSM`，上市交易所 `NYQ`）：
  - 支持 Forward P/E 分析：使用美股市场的 USD 交易报价与分析师一致预期的每 ADS USD 预测 EPS。
  - 隔离财报类模型：当财报披露币种与交易币种不一致（如台币 TWD vs 美元 USD）且缺乏权威折算时，EV/EBITDA、FCF yield 与 DCF 明确标记 `available: false`，原因标明“记账币种与交易币种不一致，不进行未经审计的汇率折算”，严禁随意捏造汇率。
- **金融机构与银行**（如 `JPM`、`BAC`）：
  - 存款负债构成其核心经营资产，EV/EBITDA 与 FCFF DCF 在经济学上不适用。
  - 系统将其隔离标记为 `available: false` 并输出业务原因，Forward P/E 正常计算，综合估值动态调整。
- **亏损与早期标的**（如 `RIVN`）：
  - 依赖正向收益或现金流的模型诚实输出 `available: false` 与具体 `unavailable_reason`（如负 EBITDA），系统正常返回 HTTP 200，绝不因缺少正盈利而崩溃或返回 422 错误。
- **非股票资产类别**（如 ETF `SPY`、加密货币）：
  - 统一通过类型化错误 `UnsupportedCompanyError` 拒绝并返回 HTTP 422。
- **财年预测对齐准则**：
  - 预测财年必须通过 upstream `nextFiscalYearEnd` 时间戳严格验证，严禁盲目采用 `year+1` 粗暴推算；对基准日非相邻的情况实施严格校验。

## 3. Git Baseline & Untracked File Safety (版本库基线与安全策略)

- **先查基线与保护成果**：
  - 任何操作前必须首先核实当前 Git 基线与分支状态（如 `git status`、`git log`）。
  - 严格保护未提交与未跟踪文件，严禁执行 `git clean -fd`、`git reset --hard`、破坏性脚手架覆盖或重新初始化 Git 仓库。
  - 除非用户发出明确授权指令，否则严禁擅自执行 `git commit` 或 `git push`。
- **Diff Stat 统计与基线说明**：
  - 在未建立 commit 基线或包含未跟踪文件时，`git diff --stat` 无法提供改动行数。此时应通过工作区文件快照比对、文件行数统计或逐文件清单说明变动，不得因 `git diff` 为空而声称没有修改。

## 4. Toolchain Baseline & Verification Commands (工具链与验证命令)

### 环境基线
- 后端：Python 3.12+，虚拟环境位于 `.venv`，依赖版本以 `pyproject.toml` 及 `backend/requirements.lock` 锁定为准。
- 前端：Node，Next.js / React / TypeScript，位于 `frontend/` 目录，依赖版本以 `frontend/package.json` 为准。

### 标准验证命令（开发与全量验收参考）
以下命令为系统开发与全量验收时的标准命令集（指明来源）：

```powershell
# 1. 后端离线单元与回归测试（必须在 demo 隔离环境中运行，来源：pyproject.toml / backend/tests/）
.\.venv\Scripts\python.exe -m pytest backend/tests/ -v

# 2. 真实多股票与特殊边界标的在线验证（来源：.scratch/live-tickers/）
.\.venv\Scripts\python.exe .scratch/live-tickers/verify_live.py
.\.venv\Scripts\python.exe .scratch/live-tickers/verify_special_tickers.py

# 3. 前端质量与构建检查（在 frontend/ 目录下执行，来源：frontend/package.json）
cd frontend
npm run typecheck
npm run lint
npm run build
cd ..

# 4. 前后端流式协议与端到端浏览器验收（来源：.scratch/live-tickers/）
node --experimental-strip-types .scratch/live-tickers/test_api_deep.mjs
python .scratch/live-tickers/browser_acceptance.py
```

### 文档任务的执行纪律
- **禁止过度测试**：对于纯文档、规范或指引类的调整，**严禁**为纯文档改动盲目运行整套产品测试（尤其是涉及大量依赖或在线网络请求的测试套件）。
- **区分历史证据与当前执行**：交接文档与报告中若提及测试结果，必须明确说明其为历史轮次已沉淀的验证记录（如 HANDOFF 第 13 节记录的历史通过），非本轮文档工作的重复执行，准确标明 `NOT RUN` / `history`。

### 工作流质量门槛

- **证据优先于结论**：任何“通过”“已修复”“已交付”都必须绑定实际命令、工作目录、退出码和可复核 artifact；Worker 自报、旧日志或历史 `HANDOFF.md` 只能作为相应等级的证据，不能覆盖当前 `git status`、当前 diff 或当前失败输出。
- **报告可复现**：每项任务报告必须记录基线、Ownership、Acceptance 矩阵、changed files、测试/静态检查的 `PASS`/`FAIL`/`NOT RUN`、风险和未决事项；未验证的模型可用性、实时数据、汇率或产品行为必须标记 `Not verified` / `Inference`。
- **验证范围跟随改动**：只改 Markdown 指引时运行 Markdown 内链、空白、终止换行和结构静态检查即可；不运行产品全套测试。若同一工作区另有产品代码 dirty/untracked，报告必须分离这些历史/并发成果，不得把它们冒充为本轮文档验证。
- **提供商回退不改变领域规则**：默认 Antigravity / `gemini-3.8-flash-high` / Full Access 不可用时，可在宿主实际暴露并授权的前提下回退到 Codex Luna Max；须记录 provider/model、原因、时间和 `resets_at`/下次探测时间，且不得因换模型放宽任意美股支持、模型适用性隔离、Decimal、来源元数据、缺失不补零、汇率审计或仓库安全约束。
- **副作用有界**：在工具、文件或外部请求已经产生副作用后，不得盲目重试非幂等动作；使用 continuation boundary 和交接证据恢复。回退、并行和会话复用都不能成为重复执行或绕过人工决策的理由。

## 5. Authoritative Spec References (权威规范索引)

当面临业务规则与技术实现分歧时，以以下高优先级权威文档为准，不复制冗余历史实现快照：

1. **功能与核验规范**：[`.scratch/live-tickers/spec.md`](../../.scratch/live-tickers/spec.md) 与 [`.scratch/live-tickers/coordinator-verification-plan.md`](../../.scratch/live-tickers/coordinator-verification-plan.md)。
2. **最新验收与交付状态**：[`HANDOFF.md`](../../HANDOFF.md) 第 13 节（Final Acceptance & Closeout Status，明确真实多 Ticker 需求已全量验收交付闭环）。
3. **公开接口与使用手册**：[`README.md`](../../README.md)。

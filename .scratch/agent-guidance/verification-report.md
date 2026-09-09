# Agent Guidance & Baseline Verification Report

## 1. Summary & Execution Context
本报告记录对 `AGENTS.md` 体系的验收修正、文档链接与空白规范验证、运行环境与模型核实，以及用户新授权的阶段性 Git 基线提交核验结果。

### 模型与权限核实 (Model & Authority Verification)
- **实际运行模型 (Actual Model)**：`Gemini 3.8 Flash (Medium)`（通过当前 Orca Worker 调度环境及系统设置核实）。
- **指引偏好与实际情况**：项目指引（`AGENTS.md` / `orchestration.md`）中将 `gemini-3.8-flash-high` 列为推荐配置；当前 Worker 会话实际分配运行于 `Gemini 3.8 Flash (Medium)`。依据诚信原则如实记录实际运行配置，绝不虚报为 `high`。
- **自治权限边界**：全量预授权任务范围内的普通文件编辑、命令执行、依赖与格式检查。普通技术问题自主推进，无需向用户转嫁工具确认。

### 测试执行属性界定 (Test Execution Boundary)
- **本轮任务定位**：纯文档体系修正、链接与格式自动化核验及初始阶段性 Git 提交。
- **产品测试状态**：`NOT RUN (Historical)`。
- **说明**：遵循“纯文档或指引改动绝不要跑整套产品测试”的执行纪律，本轮未重新执行 250 项 Pytest 或在线行情抓取；历史测试通过证据（如 250 passed）以 `HANDOFF.md` 第 13 节记录为准，本报告绝不声称本轮验证了产品无回归。

## 2. Rule Coverage Mapping (用户规则 1~13 映射表)

| 规则编号 | 核心规则概要 | 落地文档与对应章节 |
|---|---|---|
| **Rule 1** | Coordinator 通过 Orca 调度，默认 Antigravity / `gemini-3.8-flash-high` / Full Access；高不确定性×高影响归主控，可契约化归 Worker；严禁主控重读重写反模式 | [`AGENTS.md`](../../AGENTS.md) (Execution Model)<br>[`docs/agents/orchestration.md`](../../docs/agents/orchestration.md) (第 1 节 Roles & Division of Labor) |
| **Rule 2** | Worker 负责端到端闭环（代码探索/搜索/阅读/实现/测试/debug/diff review），不拆微任务；Task 五要素（Goal/Scope/Constraints/Ownership/Acceptance）；普通自主，架构/API/模型缺口才 question；调度与接手规则针对 Coordinator，Worker 不另派 Worker | [`AGENTS.md`](../../AGENTS.md) (Autonomous Authority)<br>[`docs/agents/orchestration.md`](../../docs/agents/orchestration.md) (第 1, 2 节) |
| **Rule 3** | 用户全量预授权普通文件修改/命令/依赖/测试，不向 Worker/用户转嫁工具权限确认；禁止无关/破坏性操作；遵守平台硬性限制 | [`AGENTS.md`](../../AGENTS.md) (Autonomous Authority)<br>[`docs/agents/orchestration.md`](../../docs/agents/orchestration.md) (第 2 节 Permissions & Safety Boundaries) |
| **Rule 4** | 通信仅传递契约、关键决策与验收证据（question, escalation, worker_done）；普通日志/探索/debug 留存 Worker 本地 | [`docs/agents/orchestration.md`](../../docs/agents/orchestration.md) (第 3 节 Communication Protocol) |
| **Rule 5** | 完成报告规范：outcome (succeeded/failed)、3 句话 summary、files_modified 逐文件一句、核心结果、实际验证命令与结果、diff stat、risks/unresolved；无源码/大段日志倾倒 | [`docs/agents/orchestration.md`](../../docs/agents/orchestration.md) (第 3 节 Reporting Schema) |
| **Rule 6** | 强制低 token 等待：首选 `orca check --wait 900000ms`，禁止 status/heartbeat 监听或频繁轮询，无事件主控不执行；正确 ACK；timeout 仅为无事件继续长等待；异常才 bounded terminal；适配宿主异步等待 | [`docs/agents/orchestration.md`](../../docs/agents/orchestration.md) (第 4 节 Low-Token Waiting & Delivery Ack) |
| **Rule 7** | 最低成本验收五步顺序：Acceptance → tests/build/typecheck/lint → changed files → diff stat → risks；仅特定高风险/矛盾场景才调阅局部 diff，绝不重读全库 | [`docs/agents/orchestration.md`](../../docs/agents/orchestration.md) (第 5 节 Verification Sequence) |
| **Rule 8** | 验收失败复用原 Worker 会话，指出具体 Acceptance 失败和证据；提供返工模板；主控仅在不可用/多次合理尝试失败/架构冲突/用户要求时最小必要深入 | [`docs/agents/orchestration.md`](../../docs/agents/orchestration.md) (第 5 节 Rework Protocol) |
| **Rule 9** | 真正独立无依赖无冲突才并行（优先 1~3 Tasks）；独立任务先全启动再等待；同领域复用会话（新 dispatch 复用 terminal，不复用失效身份）；结算调用 worker-release/retain | [`docs/agents/orchestration.md`](../../docs/agents/orchestration.md) (第 6 节 Parallelism, Session Reuse & Lifecycle) |
| **Rule 10** | 记忆分离：主控保留决策记忆，Worker 保留工作记忆；不为确认重做探索，不传无决策价值 progress | [`docs/agents/orchestration.md`](../../docs/agents/orchestration.md) (第 7 节 Memory Architecture) |
| **Rule 11** | 现有信息自主推进，技术问题 Worker→主控；仅真实产品选择、不可推断需求变更、高风险不可逆才升级用户 | [`AGENTS.md`](../../AGENTS.md) (Autonomous Authority)<br>[`docs/agents/orchestration.md`](../../docs/agents/orchestration.md) (第 7 节 Escalation Boundary) |
| **Rule 12** | 上下文/额度耗尽或中断前必写根 `HANDOFF.md` 然后停工；必备 10 节（Objective, Current State, Completed, In Progress, Pending, Key Decisions, Repo Changes, Verification, Risks, Resume Here）；真实保真，未核实标 Unknown，无流水账 | [`docs/agents/handoff.md`](../../docs/agents/handoff.md) (第 1 节 Trigger & Generation Protocol) |
| **Rule 13** | 接手先读 HANDOFF，从 Resume Here 与最新权威节（如第 13 节交付状态）继续，最小核查；不重做已完成调查；优先复用现有 Orca 会话；保护历史关闭状态，不重新激活已交付需求 | [`docs/agents/handoff.md`](../../docs/agents/handoff.md) (第 2 节 Takeover Sequence) |

## 3. Project Constraints & Standards Mapping (项目需求与约束映射表)

| 项目约束要点 | 来源证据与规则说明 | 落地文档与对应章节 |
|---|---|---|
| **任意美股标的分析与模型适用性** | 支持任意全量美股标的，但不保证每只股票四个模型均产生数值；仅适用模型产生结果，不适用模型诚实隔离（`available: false`） | [`AGENTS.md`](../../AGENTS.md) (Financial Fidelity)<br>[`docs/agents/project-constraints.md`](../../docs/agents/project-constraints.md) (第 1 节) |
| **数据源模式与离线隔离** | 默认实时 `yfinance`；demo 模式（`DATA_PROVIDER=demo`）严格用于网络隔离离线测试，禁止静默回退 | [`AGENTS.md`](../../AGENTS.md) (Financial Fidelity)<br>[`docs/agents/project-constraints.md`](../../docs/agents/project-constraints.md) (第 1 节) |
| **四模型与综合估值稳定约束** | 明确四模型与综合重归一化稳定概念，公式以权威规范为准，杜绝静态易陈旧常量复制 | [`docs/agents/project-constraints.md`](../../docs/agents/project-constraints.md) (第 1 节) |
| **财务适用性与边界隔离** | TSM/ADR 记账币种不一致隔离财报模型、银行隔离 EV/DCF、亏损标的 unavailable_reason 隔离、ETF/SPY 报 422；财年时间戳严格对齐 | [`docs/agents/project-constraints.md`](../../docs/agents/project-constraints.md) (第 2 节) |
| **Git 基线与未跟踪文件保护** | 建立“先查基线、保护未提交与未跟踪成果”的稳定规则；严禁 `git clean` 或 `reset --hard`；明确 diff stat 限制说明 | [`AGENTS.md`](../../AGENTS.md) (Repository Safety)<br>[`docs/agents/project-constraints.md`](../../docs/agents/project-constraints.md) (第 3 节) |
| **工具链基线与验证命令** | 后端 Python 3.12+ (`.venv`)，前端 Node/Next.js；版本以 lock/manifest 为准；提供开发验证命令集；纯文档改动不跑产品测试，历史测试标明非本轮重跑 | [`AGENTS.md`](../../AGENTS.md) (Toolchain Baseline)<br>[`docs/agents/project-constraints.md`](../../docs/agents/project-constraints.md) (第 4 节) |
| **现有规则完整保留** | 严格保留 `issue-tracker.md`、`triage-labels.md`、`domain.md` 的内容与相对链接 | [`AGENTS.md`](../../AGENTS.md) (Progressive Disclosure Architecture) |

## 4. Verification Results (核验执行记录)

### 1. 相对链接与空白规范自动化检查
- **执行命令**：`.\.venv\Scripts\python.exe .scratch/agent-guidance/verify_docs.py`
- **执行结果**：
  - 检查文档：`AGENTS.md`、`docs/agents/orchestration.md`、`docs/agents/handoff.md`、`docs/agents/project-constraints.md`、`docs/agents/issue-tracker.md`、`docs/agents/triage-labels.md`、`docs/agents/domain.md`、`.scratch/agent-guidance/verification-report.md`。
  - 内部相对链接检查：**40 / 40 PASS（0 处失效链接）**。
  - 空白与换行检查：**PASS（0 处多余尾随空白，全部以标准换行结尾）**。

### 2. 暂存区 Diff 规范检查 (Staged Git Diff Check)
- **执行命令**：`git diff --cached --check`
- **执行结果**：**PASS（退出码 0，无任何空白、冲突标记或格式违规）**。

## 5. Staged Files & Commit Inventory (提交清单与版本库状态)

阶段性提交（Initial Baseline Commit）纳入完整的产品源码、测试套件、工程配置、必要规范与指引文档：
- **工程配置与依赖**：`.gitignore`、`pyproject.toml`、`requirements.txt`、`uv.lock`
- **项目文档**：`README.md`、`HANDOFF.md`、`AGENTS.md`
- **核心指引与领域文档**：`docs/agents/`（`orchestration.md`, `handoff.md`, `project-constraints.md`, `issue-tracker.md`, `triage-labels.md`, `domain.md`）
- **后端完整基线**：`backend/`（FastAPI 服务、4 大估值引擎、yfinance/demo provider、250 项离线测试套件、锁文件及环境配置示例）
- **前端完整基线**：`frontend/`（Next.js 客户端、估值页面、DCF 场景组件、API 客户端、样式与配置文件）
- **必要权威规范与验证脚本**：
  - 规范与核验计划：`.scratch/live-tickers/spec.md`、`coordinator-verification-plan.md`、`final-acceptance.md`、`backend-final-acceptance.md`、`frontend-final-acceptance.md`
  - 核心 Issue 记录：`.scratch/live-tickers/issues/01-real-ticker-valuation.md`、`.scratch/markdown-export/issues/01-markdown-export.md`、`.scratch/valuation-mvp/issues/01-implementation.md`
  - 核心验收脚本：`verify_live.py`、`verify_special_tickers.py`、`test_api_deep.mjs`、`browser_acceptance.py`
  - 本次核验工具与报告：`.scratch/agent-guidance/verification-report.md`、`verify_docs.py`

### 剩余未跟踪文件处理说明 (Remaining Untracked Files)
- 历史 `.scratch/` 下的大型截图（`.png`）、临时接口快照（`*-snapshot.json`, `*-valuation.json`）、生成产物（`dist/`）及中间日志，依据 `.gitignore` 规则排除在提交范围之外，完整保留在工作区未作删除。

## 6. Risks & Unresolved Items (风险与状态)
- **业务代码零变更**：本次提交完全基于此前已通过 Round 3 全量验收的产品代码，未做任何修改，逻辑行为与此前交付记录 100% 一致。
- **提交不可逆风险为零**：本次仅执行本地阶段性 commit，严格遵守不 push 原则。

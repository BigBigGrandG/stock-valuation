# Agent Guidelines

本项目是一个高确定性、可溯源的 US Stock Valuation Engine（FastAPI + Next.js），支持任意美股标的四种估值模型及动态综合分析。

## Global Constraints (全局约束)

- **版本库安全 (Repository Safety)**：任何操作前必须先核实 Git 基线与分支状态；严格保护未提交与未跟踪成果，严禁执行 `git clean`、`reset --hard` 等破坏性清理；未经用户明确指令不 commit / push；修改前必须先查基线。
- **协同与调度模型 (Coordinator / Worker)**：
  - Coordinator 通过 Orca 调度，默认环境 Antigravity / `gemini-3.8-flash-high` / Full Access。
  - **Coordinator 必读**：Coordinator 在开始规划与调度前，**必须首先阅读** [Orchestration Guide](docs/agents/orchestration.md)；接手新会话或恢复工作时，**必须首先阅读**根目录存在的 [HANDOFF.md](HANDOFF.md)（若存在）及其中最新权威更新（如交付关闭状态）。
  - **职责与自治边界**：高不确定性 × 高影响决策归主控，可契约化执行归 Worker（端到端闭环，严禁拆分微任务）。上述调度与接手规则专属于 Coordinator，Worker 作为被调度执行者不应另派 Worker。普通实现自主推进，仅架构/API/数据模型重大缺口才发起 question。
- **权限与自治边界 (Autonomous Authority)**：任务范围内的普通文件编辑、命令执行、必要依赖安装与测试已获用户全量预授权，严禁转嫁权限确认；遵守上级平台安全限制。
- **业务与财务保真 (Financial Fidelity)**：支持任意美股标的（无静态白名单），仅适用模型产生有效数值，不适用模型诚实隔离；默认实时数据，离线 demo 数据（`DATA_PROVIDER=demo`）严格用于隔离测试；严禁编造目标价或未经审计的汇率。

## Workflow Contract & Routing (工作流契约与路由)

### 每项工作的最短启动路径

1. **先建立基线**：在任何编辑、测试或调度前执行 `git status --short --branch`、`git log -5 --oneline --decorate`，并查看相关 `git diff` 与未跟踪文件；把已提交、工作区修改、未跟踪成果和历史报告分开记录。严禁用 `git clean`、`git reset --hard` 或覆盖式脚手架来“整理”现场。
2. **先读权威上下文**：Coordinator 规划或接手时先读 [`docs/agents/orchestration.md`](docs/agents/orchestration.md) 和根目录 [`HANDOFF.md`](HANDOFF.md)（若存在），以最新权威章节及 `Resume Here` 为准；Worker 读取与自己 Ownership 直接相关的专业指引及 `.scratch/<feature>/` 契约，不重复无关全库探索。
3. **先写可验收契约**：派发或承接任务必须明确 Goal、Scope、Constraints、Ownership、Acceptance 五项；任务要能由一个 Worker 端到端完成，且验收命令、输出路径和停止条件可复现。

### 路由与决策边界

| 工作类型 | 路由 | 终止/验收责任 |
| --- | --- | --- |
| 架构、公共 API、数据模型、迁移、财务政策、跨模块冲突、Acceptance 裁决 | Coordinator 先决策，必要时再派一个端到端 Worker | Coordinator 保留最终决策与验收 |
| 已知边界内的实现、调查、文档、证据整理、定向测试 | 一个 Worker 全程闭环，不拆成搜索/修改/测试微任务 | Worker 依据 Acceptance 交付报告 |
| 无共享文件、无顺序依赖的独立表面 | Coordinator 可并行派发 1–3 个端到端 Worker，并显式分配 Ownership | 各 Worker 独立验收，再由 Coordinator 汇总 |
| commit、push、部署、密钥、不可逆或必须人工确认的动作 | 标记 `ready-for-human`，由授权人决定 | 未获明确指令不得执行 |

详细调度、复用及返工规则以 [`Orchestration Guide`](docs/agents/orchestration.md) 为准；术语和领域边界见 [`Project Constraints`](docs/agents/project-constraints.md)、[`Handoff Protocol`](docs/agents/handoff.md)、[`Issue Tracker`](docs/agents/issue-tracker.md) 和 [`Domain Docs`](docs/agents/domain.md)。

## Model, Quota & Provider Fallback (模型、额度与提供商回退)

- 默认 Coordinator/Worker 环境为 **Antigravity / `gemini-3.8-flash-high` / Full Access**。若 Antigravity 不可用或额度受限，且宿主确实暴露并授权，运行级回退为 **Codex Luna Max**；这是本项目的调度策略，不是对当前宿主可用模型的事实声明。
- 回退不得静默发生：在任务报告或交接记录中写明实际 provider/model、触发原因、时间、已知 `resets_at`/下次探测时间，以及是否发生过工具副作用；不得记录 token、凭据或内部能力密钥。
- 状态按 `PrimaryAvailable → Limited(reason,resets_at) → FallbackActive → ProbePrimary` 管理。只允许有界探测和一次同轮回退；已经产生工具/外部副作用后不得盲目重试同一动作，必须建立 continuation boundary，再由同一任务继续或交接；Worker 不得因回退再派 Worker。
- 额度、网络、权限和模型不确定性属于运行证据，不得写成“已安装/必然可用”；回退模型只能改变执行者，不能改变财务公式、来源、适用性隔离、版本库安全或验收门槛。

## Context, Evidence & Completion (上下文、证据与交付)

- 稳定且必须始终生效的不变量放在根 [`AGENTS.md`](AGENTS.md)；调度协议放 [`docs/agents/orchestration.md`](docs/agents/orchestration.md)；领域/安全约束放 [`docs/agents/project-constraints.md`](docs/agents/project-constraints.md)；交接放 [`docs/agents/handoff.md`](docs/agents/handoff.md)；任务事实、原始命令输出和研究材料放 `.scratch/<feature>/`。按当前任务只加载相关文件，使用路径化引用和阶段性摘要，避免把整份仓库、聊天流水或原始日志塞进每轮上下文。
- 证据分层：直接命令输出/可复核 artifact > 静态检查或文件快照 > Worker 自报；推断、候选方案和未验证假设必须显式标为 `Inference` / `Not verified`。历史 `HANDOFF.md` 或旧报告是历史证据，不自动代表本次工作区状态。
- 完成报告必须给出基线、Ownership、实际命令与工作目录、退出码、产物路径、测试是否执行（含 `NOT RUN`）、变更清单、风险和未决事项；Orca `worker_done` 还必须遵守三句话摘要、当前 `task-id`/`dispatch-id` 和显式 outcome 的协议。
- 财务变更必须能沿 `source → normalizer → projection → engine → API/export` 回溯，保留 `period`、`as_of`、currency、unit、source/source_type、估算标记和不可用原因；缺失不得补零，不能编造目标价或汇率。
- 纯文档/指引变更只做文档链接、格式和静态核验，不因“完整”而运行产品全套测试；改动产品代码时才按 [`Project Constraints`](docs/agents/project-constraints.md) 选择与范围匹配的验证。

## Toolchain & Runtime Baseline (工具链基线)

- **Backend**：Python 3.12+，虚拟环境 `.venv`，依赖版本以 `pyproject.toml` 及 `backend/requirements.lock` 锁定为准。
- **Frontend**：Next.js / React / TypeScript，位于 `frontend/` 目录，依赖版本以 `frontend/package.json` 为准。
- **测试执行纪律**：纯文档或指引改动绝不要跑整套产品测试；历史测试记录以交接与核验报告为准，不作为常驻硬编码数字。

## Progressive Disclosure Architecture (渐进披露架构)

按需查阅 `docs/agents/` 下各专业指引：

- [Orchestration Guide](docs/agents/orchestration.md)：Coordinator 与 Worker 职责划分、Task 五要素契约、通信与完成报告规范、低 Token 等待与 ACK 协议、五步验收顺序、返工模板、并行与会话复用。
- [Handoff Protocol](docs/agents/handoff.md)：交接文档触发条件、必备十节结构（Objective、Current State、Completed、In Progress、Pending、Key Decisions、Repository Changes、Verification、Risks、Resume Here）、真实性红线与接手恢复协议。
- [Project Constraints & Standards](docs/agents/project-constraints.md)：任意美股支持、四模型与综合估值稳定约束、财务适用性隔离（ADR/银行/亏损企业）、版本库安全及标准验证命令参考。
- [Issue Tracker](docs/agents/issue-tracker.md)：本地 Markdown 任务跟踪规范，issues 与 specs 位于 `.scratch/<feature>/`。
- [Triage Labels](docs/agents/triage-labels.md)：标准分类标签（`needs-triage`、`needs-info`、`ready-for-agent`、`ready-for-human`、`wontfix`）。
- [Domain Docs](docs/agents/domain.md)：单上下文领域文档架构（根目录 `CONTEXT.md` 与 `docs/adr/`）。

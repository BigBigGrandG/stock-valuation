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

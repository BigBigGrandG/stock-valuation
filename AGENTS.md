# Agent Guidelines

本项目是一个高确定性、可溯源的 US Stock Valuation Engine，采用 FastAPI + Next.js。

目标是支持真实美股上市公司，通过四种彼此独立的估值模型提供分析：

- Forward P/E
- EV/EBITDA
- FCF Yield（FCFE）
- DCF（FCFF）

模型不适用或数据不足时，应诚实返回 unavailable，而不是补零、猜测数据或跨模型重分配结果。

## Core Rules

- 保持现有 FastAPI + Next.js 架构和模块职责边界。
- 不因局部任务重写整体架构。
- 不改变公共 API、核心数据模型或财务语义，除非任务明确要求。
- 后端负责业务估值计算；前端不重新实现估值逻辑。
- 支持任意符合范围的美股上市公司，不得退化成静态 ticker 白名单。
- 四个估值模型始终独立，不生成跨模型综合目标价。
- 财务计算保持 Decimal 精度和完整 provenance。
- 缺失数据不得无依据补零。
- 不得编造财务数据、目标价、汇率或来源。
- live 数据和 demo fixture 必须严格隔离。

完整领域规则见 `docs/agents/project-constraints.md`。

## Working Model

在当前任务范围内自主完成：

- repo exploration
- 相关代码和文档阅读
- 文件修改
- 本地命令
- 测试、lint、typecheck、build
- debug → fix → retest

根据任务自行判断需要读取哪些文件，不要预读整个仓库或全部文档。

不要把搜索、阅读、实现、测试人为拆成多个微步骤；一个任务应尽可能从探索到验证形成端到端闭环。

## Decision Boundaries

普通源码、文档、本地测试和构建可以自主执行。

以下操作必须获得用户明确授权：

- `git commit`
- `git push`
- 创建或合并 PR
- 部署
- 修改生产数据
- 使用或修改真实 secrets
- 不可逆或破坏性操作

禁止：

- `git clean`
- `git reset --hard`
- 覆盖用户已有未提交成果
- 为整理环境而重建工作区

详细 repository safety 见 `docs/agents/repository-safety.md`。

## Completion

不要在代码刚写完时停止。

实现任务应尽量完成：

`implementation → verification → fix → re-verification`

停止前确认：

- 请求的行为已经实现；
- 相关验证已经运行；
- 本次修改导致的问题已经修复；
- 结果与任务目标一致。

验证范围应与修改范围匹配。纯文档修改不要运行完整产品测试。

详细验证策略见 `docs/agents/verification.md`。

## Financial Changes

涉及财务逻辑时，保持数据链可追溯：

`source → normalizer/service → projection → valuation engine → API/export`

关键字段应保留适用的：

- period
- as_of
- currency
- unit
- source / source_type
- confidence
- is_estimated
- unavailable_reason

详细模型、适用性和数据规则见 `docs/agents/project-constraints.md`。

## Context Routing

根 `AGENTS.md` 只保存长期生效的项目规则。根据当前任务按需读取以下文档。

### Financial / architecture / data rules

`docs/agents/project-constraints.md`

用于估值模型、财务适用性、provider、Decimal、provenance、currency、missing data 和架构边界。

### Verification

`docs/agents/verification.md`

用于 backend tests、frontend checks、integration / E2E、live ticker verification 和按修改范围选择验证方式。

### Repository safety

`docs/agents/repository-safety.md`

用于 Git baseline、dirty / untracked files、破坏性命令限制和 diff / 交付边界。

### Handoff

`HANDOFF.md`
`docs/agents/handoff.md`

只在恢复历史任务或当前工作依赖之前未完成成果时读取。普通独立任务无需预读 HANDOFF。

历史 HANDOFF 中的 Orca、Coordinator、Worker、provider/model 调度记录只作为历史证据，不是当前开发流程。

### Specs / issues

`docs/agents/issue-tracker.md`
`.scratch/<feature>/`

仅在已有 spec、issue、acceptance 或研究材料时按需读取。

### Domain / ADR

`docs/agents/domain.md`

涉及长期领域设计、CONTEXT 或 ADR 时读取。

### Public behavior

`README.md`

涉及公开 API、用户行为、setup、运行方式或公开产品能力时读取。

## Reporting

任务结束时简要说明：

- 修改了什么；
- 修改了哪些文件；
- 运行了哪些验证；
- PASS / FAIL / NOT RUN；
- 剩余风险或未验证事项。

历史测试结果不得冒充本轮验证。

## Toolchain

Backend:

- Python 3.12+
- FastAPI
- `.venv`
- `pyproject.toml`
- `backend/requirements.lock`

Frontend:

- Next.js
- React
- TypeScript
- `frontend/package.json`

## Principle

项目文档负责提供 Context、Constraints、Decision Boundaries 和 Completion Criteria。

让 Agent 自己决定普通实现过程，包括搜索哪些文件、阅读哪些实现、如何修改、如何 debug、运行哪些相关验证。

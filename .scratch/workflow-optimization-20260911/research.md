# 近期 AI Coding / Agent Workflow 一手实践研究

> 研究截止/访问日期：2026-09-11（Asia/Shanghai）
> 范围：官方产品文档、官方工程/产品博客、官方 GitHub 仓库/Issue/Changelog；不把社区转述或未合并提案当作已发布能力。
> 适配目标：本项目的高确定性、财务保真、Coordinator/Worker/Orca 调度，而非追逐模型或平台的花哨功能。

## 结论摘要

最值得落地的不是“让代理无限自主”，而是把长任务变成可路由、可复核、可暂停恢复的闭环：issue-shaped Task 契约、按需披露上下文、有界并行与会话复用、额度回退的副作用边界、财务来源链和真实命令证据。本轮已经把这些原则写入 [AGENTS.md](../../AGENTS.md)、[orchestration.md](../../docs/agents/orchestration.md)、[handoff.md](../../docs/agents/handoff.md) 和 [project-constraints.md](../../docs/agents/project-constraints.md)。

## 研究与适配矩阵

| # | 一手来源（发布日期/状态；均于 2026-09-11 访问） | 可落地实践（经转述） | 采用/不采用及本项目适配判断 |
| --- | --- | --- | --- |
| R1 | [OpenAI — How OpenAI uses Codex](https://openai.com/business/guides-and-resources/how-openai-uses-codex/)（发布日期未在页面标注；访问 2026-09-11） | 先以 Ask/计划模式澄清大改动，再用包含文件路径、组件、预期差异和文档/验证要求的 issue-shaped 提示执行；用 `AGENTS.md` 保存稳定上下文，并维护任务队列。 | **采用**：对应本项目 Goal/Scope/Constraints/Ownership/Acceptance 五要素与先计划后执行；稳定不变量留在根指引，任务事实留 `.scratch/<feature>/`。**不采用**默认 Best-of-N 多次生成：会放大额度和不可确定性成本，只有 Coordinator 明确批准的高价值候选才考虑。 |
| R2 | [OpenAI — Unrolling the Codex agent loop](https://openai.com/index/unrolling-the-codex-agent-loop/)（2026-01-23；访问 2026-09-11） | Codex 通过模型/工具迭代完成任务；上下文接近阈值时自动压缩；静态指令放前、变化内容放后，有利于稳定前缀与长会话连续性。 | **采用原则**：根 AGENTS、专业指引和任务契约形成稳定上下文；命令输出、阶段状态和当前 diff 作为变化内容放 `.scratch` artifact，报告链接它们。**不采用**把压缩当作事实存储：财务数值、退出码和交接状态必须落盘，不能只依赖模型记忆。 |
| R3 | [Google Gemini CLI — Provide context with GEMINI.md files](https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/gemini-md.md)（living docs，发布日期未标注；访问 2026-09-11）；[官方 Issue #11488 — JIT context proposal](https://github.com/google-gemini/gemini-cli/issues/11488)（2025-10-19 提出，已关闭 roadmap；访问 2026-09-11） | 通过层级化上下文、显式 `@file`/memory 操作和按目录的 JIT 读取，把相关指引加载到当前意图；该 Issue 的方案还强调根/全局启动上下文与读写目标时的局部上下文分开。 | **采用适配后的渐进披露**：本仓库按根 AGENTS → 调度/领域专业指引 → `.scratch/<feature>` 证据分层，Worker 只加载 Ownership 相关内容。**不宣称采用 Gemini CLI runtime**：本项目运行在 Orca/Antigravity，官方 Issue 是提案/roadmap 证据，不代表当前宿主已经按该规则加载。 |
| R4 | [OpenAI — Running Codex safely at OpenAI](https://openai.com/index/running-codex-safely/)（2026-05-08；访问 2026-09-11） | 低风险工作尽量降低摩擦，高风险工作需要沙箱/审批/网络约束；agent-native telemetry 记录 prompt、工具批准、工具结果及网络决策，便于审计和复盘。 | **采用**：把仓库安全红线、Ownership、人工决策边界、命令/cwd/退出码和 artifact 路径写入证据契约；commit/push/部署/凭据等停在 `ready-for-human`。**不复制平台实现**：本项目不声称已经接入 OpenAI telemetry、沙箱策略或网络 allowlist，未知能力写 `Not verified`。 |
| R5 | [Anthropic — Agents for financial services](https://www.anthropic.com/news/finance-agents)（2026-05-05；访问 2026-09-11） | 金融代理实践把领域 skills、受治理的数据连接器、专门子代理、按工具权限、凭据库、审计日志和人工 review/approve 组合起来；模型方法需要服从机构 conventions、风险与审批流程。 | **采用**：财务 source → normalizer → projection → engine → API/export 链、模型适用性隔离、来源元数据、人工验收和可追溯 artifact 都成为硬门槛；允许专业 Worker，但由 Coordinator 决定边界。**不采用**自动外部连接器、自动客户交付或凭据注入：本任务没有授权也没有验证这些外部系统。 |
| R6 | [Anthropic — Measuring AI agent autonomy in practice](https://www.anthropic.com/news/measuring-agent-autonomy)（2026-02-18；访问 2026-09-11）；[Anthropic — Enabling Claude Code to work more autonomously](https://www.anthropic.com/news/enabling-claude-code-to-work-more-autonomously)（2025-09-29；访问 2026-09-11） | 长会话和后台任务提升吞吐，但复杂任务中的澄清停点、版本控制 checkpoint/rewind、hooks 和人工监督仍是安全闭环；高后果领域不能只看代理“完成”状态。 | **采用有界自治**：Worker 在 Acceptance 完成、需要 `question`、发生阻塞或发现范围外问题时明确停止；版本库安全、返工模板和复盘保留恢复点。**谨慎采用 hooks/background**：只记录为可选宿主能力，不在本项目文档中假设会执行任意命令或绕过审批。 |
| R7 | [OpenAI — Introducing the Agents API](https://openai.com/index/introducing-the-agents-api/)（2026-09-10；访问 2026-09-11） | 长会话压缩、按需 tool search、程序化并行/链式调用和专门 subagent 可用于复杂工作；示例使用有限并发而非无界派生。 | **采用原则**：独立且无共享 Ownership 的表面才并行，默认 1–3 个端到端 Worker；复用需新的 Task/Dispatch；上下文只载入相关定义。**不采用具体 `max_concurrent_subagents: 3` 作为硬性平台参数**：它是官方示例而非本项目 Orca 的已验证限制，文档只采用保守默认和 Coordinator 调整权。 |
| R8 | [OpenAI — How agents are transforming work](https://openai.com/index/how-agents-are-transforming-work/)（2026-06-25；访问 2026-09-11） | 生产中的 agent turn 已出现长时长、多并行代理分布，说明长周期任务需要队列、状态和可观察性，而不是每步都由人重新启动。 | **采用队列/状态思想**：任务契约、expected Dispatch、supervised wait、settlement 和 weekly review 形成可观察闭环。**不采用“并行越多越好”**：本项目的共享财务语义、公共 API 和未提交成果使 Ownership/风险比吞吐更优先。 |
| R9 | [OpenAI Help — Using Codex with your ChatGPT plan](https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan)（页面显示 `Updated: 12 days ago`，按本次访问约 2026-08-30；访问 2026-09-11）；[OpenAI Codex Issue #32341 — quota-aware fallback](https://github.com/openai/codex/issues/32341)（2026-07-11 提出、访问时仍为 open feature request；访问 2026-09-11） | 额度会随计划、模型、任务复杂度、上下文和工具变化；官方帮助建议通过 usage/status 观察并等待 reset/使用 credits。Issue 的未发布设计提出 provider-scoped quota 窗口、`resets_at`、Primary→Limited→Fallback→Probe 状态、同轮副作用前一次重试和副作用后的 continuation boundary。 | **采用经降级验证的策略**：默认 Antigravity / `gemini-3.8-flash-high`，不可用/受限且宿主实际授权时回退 Codex Luna Max；报告 provider/model、原因、时间、`resets_at`/下次探测，且副作用后不重放非幂等动作。**不把 Issue 当已发布功能**：Orca 当前是否实现自动 quota accounting、provider failover 或 `Codex Luna Max` 可用性均 `Not verified`；文档只规定可审计的人工/Coordinator 调度策略。 |
| R10 | [GitHub Changelog — Copilot code review: AGENTS.md support](https://github.blog/changelog/2026-06-18-copilot-code-review-agents-md-support-and-ui-improvements/)（2026-06-18；访问 2026-09-11）；[GitHub Changelog — visibility into coding agent sessions](https://github.blog/changelog/2026-03-19-more-visibility-into-copilot-coding-agent-sessions/)（2026-03-19；访问 2026-09-11） | 官方产品把仓库内 AGENTS.md 作为 code review 指引，并增加 setup、custom setup、subagent activity 等会话可见性。 | **采用可迁移的文档/日志原则**：根 AGENTS 只放稳定高优先级规则，报告列出实际路径、命令、退出码和 Worker 产物，便于 Coordinator 只读必要 section。**不声称跨平台同等支持**：这些是 GitHub Copilot 行为，本项目不假设 Orca 自动读取所有 AGENTS 层级。 |
| R11 | [GitHub Changelog — Copilot coding agent validates security and quality](https://github.blog/changelog/2025-10-28-copilot-coding-agent-now-automatically-validates-code-security-and-quality/)（2025-10-28；访问 2026-09-11）；[GitHub Docs — Adding agent skills for Copilot](https://docs.github.com/en/copilot/how-tos/copilot-on-github/customize-copilot/customize-cloud-agent/add-skills)（living docs，发布日期未标注；访问 2026-09-11） | 官方 coding agent 在特定产品面执行安全/质量检查；skills 把详细指引、脚本和资源按相关性封装，区别于总是加载的简短 custom instructions。 | **采用分层和验证门槛**：专业 docs 按需加载，纯文档 Task 做链接/空白静态检查，产品改动才按范围跑测试；报告不把未运行的 CodeQL、secret scanning 或 build 写成通过。**本轮不新增 Copilot skill 目录**：用户 Scope 仅允许 `AGENTS.md`、`docs/agents/*.md` 和三份报告，且已有专业指引足以覆盖当前流程。 |

## 采用后的仓库落点

- 路由、五要素 Task、端到端 Worker、并行/复用/停止与 Orca settlement：[`docs/agents/orchestration.md`](../../docs/agents/orchestration.md)。
- 默认模型、Codex Luna Max fallback、稳定上下文与完成报告最短契约：[`AGENTS.md`](../../AGENTS.md)。
- 交接触发、周复盘分离、fallback continuation boundary 和敏感信息脱敏：[`docs/agents/handoff.md`](../../docs/agents/handoff.md)。
- 财务来源链、适用性隔离、验证范围和证据质量门槛：[`docs/agents/project-constraints.md`](../../docs/agents/project-constraints.md)。

## 明确不采纳的边界

1. 不把未发布 GitHub Issue、living docs 的宿主细节或本次没有验证的 provider 能力写成当前系统事实。
2. 不默认 Best-of-N、无界 subagent 派生、后台 hooks、自动凭据/外部连接器或自动 commit/push；它们会增加额度、权限、重复副作用和审计成本。
3. 不以一份模型生成的摘要替代命令输出、退出码、来源元数据、历史/当前状态分类和人工高影响决策。

# Handoff Protocol

本指南定义跨会话或中断任务的最小交接规范。只有当前工作尚未完成且后续需要继续时，才创建或更新根目录 `HANDOFF.md`。

普通独立任务不需要预读或维护 HANDOFF。

## 1. When to Create a Handoff

在以下情况下创建或更新 `HANDOFF.md`：

- 当前任务尚未完成，但必须中断；
- 后续会话需要依赖当前未提交或未合并成果；
- 上下文即将不足以安全继续；
- 存在需要下一位 Agent 明确接续的外部阻塞。

已完整交付的普通任务不需要为了记录历史而更新 HANDOFF。

## 2. Factual Integrity

HANDOFF 只记录可核实的当前状态：

- 未验证事项标记 `Unknown` 或 `Not verified`；
- 不把推断写成事实；
- 不复制完整源码、长日志或聊天流水；
- 历史测试结果与本轮实际验证明确区分；
- 不记录 API key、token、密码、secret 或可重放的敏感请求。

## 3. Recommended Structure

根 `HANDOFF.md` 应包含足够恢复任务的最小信息：

1. `Objective`：用户目标、当前阶段和边界。
2. `Current State`：当前代码、服务和工作区事实。
3. `Completed`：已经完成且有证据支持的部分。
4. `In Progress`：尚未完成的具体工作与涉及文件。
5. `Pending`：后续待办及优先级。
6. `Key Decisions`：架构、API、数据或财务上的重要决定及理由。
7. `Repository Changes`：branch / HEAD、dirty / untracked、changed files。
8. `Verification`：本轮实际命令与 PASS / FAIL / NOT RUN。
9. `Risks / Unknowns`：未验证假设、环境问题、测试缺口和阻塞。
10. `Resume Here`：下一步最小可执行动作和停止条件。

不要求为了满足模板填写没有价值的内容；重点是让后续 Agent 能准确恢复，而不是生成冗长报告。

## 4. Resume Rules

只有当当前任务确实依赖历史未完成成果时，才读取根 `HANDOFF.md`。

恢复时：

- 先确认 HANDOFF 所描述的 branch、HEAD、文件和当前实际状态仍然一致；
- 从 `Resume Here` 和未完成事项开始，不默认重新探索整个仓库；
- 已经通过当前证据确认的结论不重复调查，除非代码或环境已变化；
- 历史日志不能覆盖当前 `git status`、diff 或测试结果；
- 如 HANDOFF 与当前仓库冲突，以当前可复核状态为准，并记录差异。

## 5. Historical Workflow Metadata

旧 `HANDOFF.md` 或 `.scratch/` 报告可能包含 Orca、Coordinator、Worker、dispatch、terminal、provider/model fallback 等历史字段。

这些字段只用于理解历史工作发生过什么：

- 不需要恢复旧 Orca task、worker terminal 或 dispatch；
- 不把旧 provider/model 调度策略视为当前执行规则；
- 不因旧文档中的等待、通信或 worker 协议而改变当前工作方式；
- 只提取仍然有效的产品事实、决策、改动、验证证据和未完成事项。

当前 Agent 工作方式以根 `AGENTS.md` 及其路由到的现行文档为准。

## 6. Repository and Verification References

交接中的版本库状态遵循：

`docs/agents/repository-safety.md`

交接中的验证结果遵循：

`docs/agents/verification.md`

涉及财务和领域规则时遵循：

`docs/agents/project-constraints.md`

## 7. Weekly or Historical Reviews

周期性复盘、研究材料和历史验收记录应放在对应 `.scratch/<feature>/` 下，而不是为了归档而不断膨胀根 `HANDOFF.md`。

HANDOFF 的职责只有一个：保存恢复当前未完成工作的最小可靠上下文。

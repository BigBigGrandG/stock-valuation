# Coordinator & Worker Orchestration

本指南定义本项目中 Coordinator（主控）与 Worker（工作代理）在 Orca 调度体系下的协作契约、通信规范与执行流程。

## 1. Roles & Division of Labor (角色与分工)

Coordinator 与 Worker 遵循明确的职责边界与契约化分工：

- **Coordinator (主控)**：
  - 运行环境：通过 Orca 进行调度，默认配置为 Antigravity / `gemini-3.8-flash-high` / Full Access。
  - **调度前必读**：Coordinator 在开始规划与调度前，**必须首先阅读**本指引；在接手会话或恢复开发时，**必须首先阅读**根目录存在的 `HANDOFF.md` 及最新权威更新。
  - 职责范围：仅聚焦高不确定性 × 高影响的核心事务，包括需求目标界定、系统架构设计、跨模块依赖与 Ownership 划分、重大技术决策裁决、验收标准制定与最终交付。
  - 行为准则：不从事可契约化执行的常规工作。严禁在 Worker 调研后主控重新通读仓库自己实现；严禁在 Worker 实现后主控全量重读全库重写。
- **Worker (工作代理)**：
  - 职责范围：负责具体功能的端到端闭环，包括代码仓库探索 (repo exploration)、搜索与阅读、功能实现与重构、配置与文档、测试与命令执行、debug-fix-retest 循环、diff review 及精炼总结。
  - 端到端原则：一个独立功能由一个 Worker 端到端负责到底，绝不拆分为“搜索”、“阅读”、“修改”、“测试”等琐碎微任务。任务涉及的未知文件由 Worker 自行定位。
  - 角色纪律：本指引的调度、派发与接手规则专属于 Coordinator。Worker 作为被调度的执行主体，仅负责自身任务的闭环实现，绝不应误以为自己还应另派 Worker。
  - 自治与决策边界：普通技术实现与代码细节由 Worker 自主判断推进；仅当遇到架构调整、公共 API 变更、数据模型或 migration 改动、安全与权限控制、跨模块行为冲突、或用户目标存在不可推断的重大缺口时，才向 Coordinator 发起 `question`。

## 2. Task Specification & Autonomous Authority (任务契约与权限)

### Task 契约结构
每个下发给 Worker 的 Task 必须包含五项核心要素：
1. **Goal**：明确、单一的业务或技术目标。
2. **Scope**：允许操作与交付的边界范围。
3. **Constraints**：硬性技术、架构与平台约束。
4. **Ownership**：专属负责的模块、目录或文件清单。
5. **Acceptance**：可验证的验收准则与断言标准。

### 权限与安全红线
- **自主授权**：用户已全量预授权任务范围内的普通文件修改/创建、命令执行、必要依赖配置、测试/lint/typecheck/build 运行及标准工具调用。严禁向 Worker 或用户转嫁普通工具执行的权限确认。
- **禁止高风险操作**：严禁任何无关修改、不可逆破坏、全库覆盖式脚手架重建或高风险文件清理。
- **平台限制优先**：严格遵守上级与宿主平台的实际权限与沙箱限制；Full Access 授权不代表可以绕过底层平台强制安全策略。

## 3. Communication Protocol & Reporting Schema (通信协议与报告契约)

### 通信原则
通信信道仅传递契约、关键决策与验收证据。普通的探索过程、操作日志与调试细节保留在 Worker 本地工作记忆中。

### 核心消息类型
- **`question`**：仅用于无法从现有信息推断的关键决策、架构分歧或重大规范缺口。
- **`escalation`**：仅用于真正的外部阻塞、不可调和的冲突、系统异常或连续尝试失败。
- **`worker_done`**：任务完成时向 Coordinator 汇报，每次调度严格发送一次。

### 完成报告规范 (`worker_done`)
Worker 完成任务后必须发送标准化 `worker_done`，载荷包含：
- `--outcome`：显式指定 `succeeded` 或 `failed`，严禁隐晦表达失败或静默退出。
- `--body`：严格限制为 3 句话的执行摘要（做了什么、发现了什么、遗留什么）。
- `files_modified`：每个改动文件一句话说明其用途与变动。
- `core_results`：核心结果与关键结论。
- `verification`：实际执行的验证命令及逐项 PASS / FAIL 结果。
- `diff_stat`：修改行数与统计（如无 git 基线需说明文件行数变化）。
- `risks_unresolved`：潜在风险、未覆盖边界与未决事项。
- 紧凑原则：默认不附带完整源码、大段 diff 或全量日志；Coordinator 仅在必要时精确索取局部代码。若生成长篇报告，写入文件并通过 `--report-path` 指向。

## 4. Low-Token Waiting & Delivery Ack Protocol (低 Token 等待协议)

Coordinator 必须严格遵守低 token 消费的等待模式：

- **首选等待命令**：
  ```powershell
  orca orchestration check --wait --types "worker_done,escalation,question" --timeout-ms 900000 --json
  ```
- **禁止频繁轮询**：不监听 status/heartbeat 消息，严禁 30~60 秒频繁轮询，严禁反复催问、持续读取 terminal tail 或要求无意义的进度汇报。
- **静默等待原则**：在未收到决策事件（`question` / `escalation` / `worker_done`）期间，主控不得从事执行工作。
- **完整 ACK 推进**：每个处理完成的 Delivery 必须显式 ACK，并继续阻塞等待：
  ```powershell
  orca orchestration check --ack <delivery_id> --wait --types "worker_done,escalation,question" --timeout-ms 900000 --json
  ```
- **超时语义**：`timeout` 仅表示当前等待周期内无新事件，不是任务失败；应继续发起下一轮长等待。
- **异常诊断限制**：仅在长期无有效事件且强烈怀疑 Worker 崩溃、死锁或异常退出时，才允许执行一次有限的状态诊断；仅在确认异常时有界读取 terminal 输出。
- **宿主限制适配**：若当前工具宿主对单次命令等待时长施加硬性上限，应使用宿主支持的异步等待机制保留同一阻塞等待语义，遵守更高优先级限制，不得退化为高频轮询。保留 900000ms 原始首选参数。

## 5. Verification Sequence & Rework Protocol (验收顺序与返工契约)

### 最低成本验收五步顺序
Coordinator 收到 Worker 报告后，按以下顺序核验，信息充分即止，不重新探索全库：
1. **Acceptance**：逐项对照任务的验收准则。
2. **Tests / Build / Typecheck / Lint**：核实实际执行的自动化测试命令与退出码。
3. **Changed Files**：核对改动文件列表是否与 Scope 和 Ownership 吻合。
4. **Diff Stat**：评估改动规模与行数是否合理。
5. **Risks / Unresolved**：评估报告中披露的潜在风险与未决事项。

### 局部 Diff 审查条件
仅在以下情况下才调阅局部 diff，绝不通读全库：
- 涉及公共 API、认证/安全、数据迁移、并发模型或关键架构变更。
- 涉及高风险删除操作。
- Worker 报告结论与实际测试证据存在矛盾。
- 仅凭报告无法确认 Acceptance 达成。
- 用户有明确且严格的 review 要求。

### 验收失败与返工模板 (Rework Protocol)
验收不通过时，优先复用原 Worker 会话，指出具体未达成的 Acceptance 项与证据，要求其针对性修复并仅返回紧凑报告：

```markdown
### Rework Request
- **Task ID / Dispatch ID**: [task_xxx / ctx_xxx]
- **Failed Acceptance**: [明确指出具体未达成的准则]
- **Evidence / Failure Details**: [具体的报错日志、测试失败断言或不一致证据]
- **Action Required**: 修复问题、重新执行相关验证，仅返回紧凑完成报告（按规范更新 files_modified、验证结果及 diff stat）。
```

主控仅在 Worker 彻底不可用、连续多次合理尝试失败、存在跨模块架构冲突、需多 Worker 仲裁、或用户明确要求主控本人实现/审查时，才在最小必要范围内深入代码实现。

## 6. Parallelism, Session Reuse & Lifecycle (任务并行与会话复用)

- **真正独立并行**：仅当任务之间无实现依赖、无共享文件冲突时才允许并行执行，优先保持 1~3 个端到端 Task。
- **批量启动后等待**：存在多个独立任务时，先全部完成创建与 dispatch 注入，再进入统一等待循环。
- **会话与终端复用**：同一业务领域或连续问题优先复用现有终端/会话。在 Orca 中，已结算的 Dispatch 需创建新的 Task 与 Dispatch 绑定复用该 terminal，严禁使用已失效的 lifecycle 凭据。
- **生命周期结算**：任务验收通过且不再复用终端时，必须严格按 Orca 协议调用 `worker-release`，或显式声明 `retain` 保留供排查。

## 7. Memory Architecture & Escalation Boundary (记忆分工与升级边界)

- **记忆分离**：Coordinator 仅维护“决策记忆”（架构设计、关键决策、验收判定、依赖拓扑）；Worker 维护“工作记忆”（代码实现细节、调试栈、临时数据）。严禁主控为了“核实”而重新做 Worker 已完成的细粒度调查。
- **自主推进**：在现有信息完备的情况下自主闭环；普通技术问题由 Worker 升级至主控。
- **用户升级红线**：仅在面临真实的产品业务取舍、用户目标发生不可推断的变更、或面临高风险不可逆破坏时，才向用户请求决策输入。

# Coordinator & Worker Orchestration

本指南定义本项目中 Coordinator（主控）与 Worker（工作代理）在 Orca 调度体系下的协作契约、通信规范与执行流程。

## 1. Roles & Division of Labor (角色与分工)

Coordinator 与 Worker 遵循明确的职责边界与契约化分工：

- **Coordinator (主控)**：
  - 角色定位：当前高级主控模型，通过 Orca 调度 Worker；Coordinator 本身不等同于 Antigravity Worker。
  - **调度前必读**：Coordinator 在开始规划与调度前，**必须首先阅读**本指引；在接手会话或恢复开发时，**必须首先阅读**根目录存在的 `HANDOFF.md` 及最新权威更新。
  - 职责范围：仅聚焦高不确定性 × 高影响的核心事务，包括需求目标界定、系统架构设计、跨模块依赖与 Ownership 划分、重大技术决策裁决、验收标准制定与最终交付。
  - 行为准则：不从事可契约化执行的常规工作。严禁在 Worker 调研后主控重新通读仓库自己实现；严禁在 Worker 实现后主控全量重读全库重写。
- **Worker (工作代理)**：
  - 默认运行环境：Antigravity / `gemini-3.8-flash-high` / Full Access，由 Coordinator 通过 Orca 调度。
  - 职责范围：负责具体功能的端到端闭环，包括代码仓库探索 (repo exploration)、搜索与阅读、功能实现与重构、配置与文档、测试与命令执行、debug-fix-retest 循环、diff review 及精炼总结。
  - 端到端原则：一个独立功能由一个 Worker 端到端负责到底，绝不拆分为“搜索”、“阅读”、“修改”、“测试”等琐碎微任务。任务涉及的未知文件由 Worker 自行定位。
  - 角色纪律：本指引的调度、派发与接手规则专属于 Coordinator。Worker 作为被调度的执行主体，仅负责自身任务的闭环实现，绝不应误以为自己还应另派 Worker。
  - 自治与决策边界：普通技术实现与代码细节由 Worker 自主判断推进；仅当遇到架构调整、公共 API 变更、数据模型或 migration 改动、安全与权限控制、跨模块行为冲突、或用户目标存在不可推断的重大缺口时，才通过 `ask` 向 Coordinator 发起阻塞式 `question`。

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
- **`question`**：Worker 仅在遇到无法从现有信息推断的关键决策、架构分歧或重大规范缺口时，通过 `ask` 请求 Coordinator 决策；Coordinator 处理后必须明确 `reply`。
- **`escalation`**：仅用于真正的外部阻塞、不可调和的冲突、系统异常或连续尝试失败。
- **`worker_done`**：任务完成时向 Coordinator 汇报，每次调度严格发送一次。

### Worker completion report (`worker_done`)

Worker 完成任务后必须发送标准化 `worker_done`。Orca lifecycle envelope 只使用当前 CLI 明确支持的字段：

- `--task-id` 与 `--dispatch-id`：标识当前 expected Task 与 authoritative Dispatch。
- `--outcome`：显式指定 `succeeded` 或 `failed`，严禁隐晦表达失败或静默退出。
- `--body`：严格限制为 3 句话的 executive summary（做了什么、发现了什么、遗留什么）。
- `--files-modified`：列出实际修改的文件。
- `--report-path`：可选；指向详细验收报告。

Acceptance matrix、verification 命令与结果、diff stat、risks / unresolved 等详细证据统一写入 `reportPath` 指向的报告文件，不得假定它们是 Orca CLI 的一级参数。默认不附带完整源码、大段 diff 或全量日志。

Coordinator 默认只消费 `outcome`、`body`、`filesModified` 与 `reportPath`。只有现有证据不足以完成验收时，才读取报告的相关 section；只有高风险或证据冲突时，才读取局部 diff。禁止默认展开完整报告或重新探索仓库。

## 4. Coordinator Cost Discipline & Supervised Waiting (主控成本纪律与监督等待)

### 高级推理边界

Coordinator 的高级模型推理只允许发生在以下阶段：

1. 初始目标、架构与 Task 设计；
2. Worker 阻塞式 `question`；
3. `escalation` 或失败处理；
4. `worker_done` 验收；
5. 用户发出新指令。

除此之外均属于 execution / waiting 阶段，不进行高级模型分析。核心原则是：**No actionable event = no reasoning + no narration.**

### Orca supervised wait

Worker 启动后，Coordinator 必须严格遵守低 token 消费的 Orca supervised wait 模式：

- **首选等待命令**：
  ```powershell
  orca orchestration check --wait --types "worker_done,escalation,question" --timeout-ms 900000 --json
  ```
- **等待前置条件**：只有当前存在至少一个尚未 settled 的 expected Dispatch 时，才允许执行 `check --wait`。**No active expected Dispatch = no wait.**
- **只监听可行动事件**：当前主线仅监听 `worker_done`、`escalation`、`question`；不监听 progress、status 或 heartbeat。
- **禁止频繁轮询**：严禁 30~60 秒频繁轮询、反复催问、持续读取 terminal tail 或要求无意义的进度汇报。正常 coding Worker 可连续运行 15–60 分钟。
- **静默等待原则**：background terminal 尚未返回且没有可行动事件时，只继续 wait；不得输出自然语言，不重复任务、验收标准或预期实现，不推测 Worker 进度，不读取 Worker terminal，不重新读取 repository，也不得产生状态总结。
- **Checkpoint 语义**：wait timeout 或 count=0 只表示 checkpoint，不是任务失败或 Worker 失活。前两次连续空 wait 后保持静默并继续长等待；连续第 3 次空 wait 后，执行一次 `orca orchestration worker-list --include-remote --json`，只按返回的 `projection.attention` / `nextAction` 行动，不默认读取 terminal。
- **单次消费原则**：`check` 返回的 Delivery 本身就是待处理事件；不得在 ACK 前再次执行无 `--wait` 的 `check` 来“确认”或重新读取同一 Delivery。Delivery 在 ACK 前可能被 FIFO 重放，因此每个 Delivery 必须且只能完整处理一次。
- **固定处理顺序**：一个 Delivery 的流程必须是：接收 → 处理其中每条 message → `question` 则 `reply` / `escalation` 则只解决 blocker / `worker_done` 则验证 settlement → 对已 settled Worker 执行 reuse、retain、release 三选一 → 更新 expected active Dispatch 集合 → ACK 恰好一次 → 按剩余 active 数决定等待或退出。
- **ACK 分支**：发出 ACK 前必须先计算处理后的 expected active Dispatch 集合。若 active 数大于 0，可用 ACK-and-wait 原子推进：
  ```powershell
  orca orchestration check --ack <delivery_id> --wait --types "worker_done,escalation,question" --timeout-ms 900000 --json
  ```
- 若 active 数等于 0，只 ACK 而不附加 `--wait`，随后立即退出 supervised wait：
  ```powershell
  orca orchestration check --ack <delivery_id> --json
  ```
- **等待退出条件**：每次处理 `worker_done` 后必须更新 expected active Dispatch 集合。若所有预期 Dispatch 均已 settled，禁止再次执行 `check --wait`；立即进入下一 Task、最终验收或交付。不得在 active expected Dispatch 为零时仅为“确认是否还有消息”而空等待。
- **事件处理边界**：收到 Worker 通过 `ask` 发起的 `question` 时，仅处理所请求的决策并 `reply`；收到 `escalation` 时仅解决 blocker；收到 `worker_done` 时才进入验收与 settlement 判定。
- **异常诊断限制**：只有 `worker-list --include-remote --json` 的 `projection.attention` / `nextAction` 指示异常，或有其他明确失活证据时，才允许有界读取 terminal 进行诊断。
- **宿主限制适配**：若当前工具宿主对单次命令等待时长施加硬性上限，应使用宿主支持的异步等待机制保留同一阻塞等待语义，遵守更高优先级限制，不得退化为高频轮询。保留 900000ms 原始首选参数。

### Completion lifecycle & settlement

有效 `worker_done` 是正常完成的唯一权威信号。它必须属于当前 expected Task 与 authoritative Dispatch，并显式包含 `succeeded` 或 `failed` outcome；Coordinator 验证这些标识与结果后，方可判定 settlement。

只有 accepted settlement 才允许对 Worker 做且只做一个后续选择：

1. **Immediate reuse**：立即复用原 terminal / session 承担后续任务；
2. **Explicit retain**：明确保留原 terminal / session 供稍后排查或继续；
3. **Release**：调用 `worker-release` 完成 post-settlement cleanup。

`worker-release` 不是 cancellation。不得因 timeout、idle、heartbeat、status、`question`、`escalation`、没有新输出或“看起来已经完成”而 release Worker。所有 expected Dispatch settled 后，Coordinator 必须退出 supervised wait。

## 5. Verification Sequence & Rework Protocol (验收顺序与返工契约)

### 最低成本验收五步顺序
Coordinator 收到 Worker 报告后，按以下顺序核验，信息充分即止，不重新探索全库：
1. **Completion Envelope**：先读取 `outcome`、3 句话 `body`、`filesModified` 与 `reportPath`。
2. **Acceptance**：逐项对照任务的验收准则。
3. **Tests / Build / Typecheck / Lint**：核实实际执行的自动化测试命令与退出码。
4. **Changed Files / Diff Stat**：核对改动文件是否符合 Scope 与 Ownership，并评估规模是否合理。
5. **Risks / Unresolved**：评估潜在风险与未决事项；仅在证据不足时按需读取报告相关部分。

### 局部 Diff 审查条件
只有高风险或证据冲突时才调阅局部 diff，绝不通读全库。适用情形包括：
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
- **Action Required**: 修复问题并重新执行相关验证；发送标准 `worker_done` envelope，将验证结果、diff stat 与剩余风险写入 `reportPath` 指向的报告，仅返回紧凑摘要。
```

主控仅在 Worker 彻底不可用、连续多次合理尝试失败、存在跨模块架构冲突、需多 Worker 仲裁、或用户明确要求主控本人实现/审查时，才在最小必要范围内深入代码实现。

## 6. Parallelism, Session Reuse & Lifecycle (任务并行与会话复用)

- **真正独立并行**：仅当任务之间无实现依赖、无共享文件冲突时才允许并行执行，优先保持 1~3 个端到端 Task。
- **批量启动后等待**：存在多个独立任务时，先全部完成创建与 dispatch 注入，再进入统一等待循环。
- **会话与终端复用**：同一业务领域、连续问题或 retry 优先复用健康的原 Worker terminal / session，以保留工作记忆。已结算的 Dispatch 需创建新的 Task 与 Dispatch 绑定该 terminal，严禁使用已失效的 lifecycle 凭据；只有原 Worker 无法安全复用时才新建 Antigravity terminal。
- **自定义终端就绪检查**：使用 `terminal create → terminal wait → worker-start` 启动带自定义参数的 Antigravity 时，必须确认 `terminal wait` 返回 `satisfied == true` 后才能执行 `worker-start`；命令返回本身不代表 terminal 已 ready。
- **生命周期结算**：只有 accepted settlement 才能执行 reuse、retain、release 三选一。任务验收通过且不再复用终端时调用 `worker-release`；需要保留时必须显式 `retain`。

## 7. Memory Architecture & Escalation Boundary (记忆分工与升级边界)

- **记忆分离**：Coordinator 仅维护“决策记忆”（架构设计、关键决策、验收判定、依赖拓扑）；Worker 维护“工作记忆”（代码实现细节、调试栈、临时数据）。严禁主控为了“核实”而重新做 Worker 已完成的细粒度调查。
- **自主推进**：在现有信息完备的情况下由 Worker 自主闭环普通技术问题；只有符合阻塞式 `question` 或 `escalation` 边界的事项才升级至 Coordinator。
- **用户升级红线**：仅在面临真实的产品业务取舍、用户目标发生不可推断的变更、或面临高风险不可逆破坏时，才向用户请求决策输入。

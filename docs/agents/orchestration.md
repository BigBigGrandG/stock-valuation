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

### 快速路由与任务形状

先按影响与不确定性路由，再按文件 Ownership 分派，避免为了“并行”而制造共享状态：

| 信号/工作 | 决策人和执行方式 | 例外与验收 |
| --- | --- | --- |
| 架构、公共 API、数据模型/迁移、财务政策、跨模块冲突、最终 Acceptance | Coordinator 先做决策；实现可交给一个端到端 Worker | 决策记录必须进入任务契约或 ADR；Coordinator 最终验收 |
| 已知边界内的实现、调查、文档、证据整理、定向验证 | 单一 Worker 从探索到报告闭环 | 不拆成搜索、修改、测试等微任务 |
| 彼此无共享文件、顺序依赖和合并冲突的独立表面 | Coordinator 并行派发 1–3 个端到端 Worker | 每个 Worker 有互斥 Ownership 和独立 Acceptance |
| commit/push、部署、凭据、不可逆动作或需业务拍板的取舍 | `ready-for-human`，暂停在人工决策边界 | 未获明确指令不得执行 |

每个 Task 应是“issue-shaped”：说明用户目标、相关路径/组件、约束、预期差异和可执行验证。大型变更先由 Coordinator 形成计划并确认边界，再派发闭环执行；Worker 发现重大缺口时使用 `question`，不擅自改写架构或另派 Worker。

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

### 模型、额度与提供商回退

- 默认环境为 **Antigravity / `gemini-3.8-flash-high` / Full Access**。当 Antigravity 不可用或额度受限，并且宿主确实暴露、授权并可审计时，才使用 **Codex Luna Max** 作为运行级回退；不要把策略写成模型已经可用的事实。
- Worker/Coordinator 必须在报告中记录实际 provider/model、触发原因、发生时间、可知的 `resets_at` 或下次探测时间。不得记录 token、凭据、能力密钥或其他秘密；若模型/额度不可验证，写 `Not verified`。
- 采用有界状态机：`PrimaryAvailable → Limited(reason,resets_at) → FallbackActive → ProbePrimary`。一次任务只做有限次探测和一次同轮回退；不以通用重试掩盖额度耗尽、权限拒绝或服务故障。
- **副作用边界**：若工具调用、文件写入、外部请求或其他动作已经产生副作用，禁止在同一边界重复执行可能非幂等的动作；建立 continuation boundary，沿原 Task/Dispatch 继续或交接，并带上已执行命令和产物路径。只有在尚无助手/工具副作用时，才允许一次受控的同轮重试。
- 回退模型只改变执行者，不能降低金融保真、来源元数据、适用性隔离、仓库安全或 Acceptance 门槛。Worker 不得因回退再派 Worker；提供商专属凭据和额度状态不可互相冒用。

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

### Evidence Contract (证据契约)

每个 Worker 报告必须让另一位代理能够复核“当时发生了什么”，而不是只复述结论：

| 必填项 | 最低要求 |
| --- | --- |
| Baseline/Ownership | 分支、HEAD、相关 dirty/untracked 状态，以及本 Task 实际拥有的文件；不得把别人的工作区成果算入自身 diff |
| Commands | 完整命令、工作目录、时间/环境（必要时 provider/model）、退出码；长日志写入 artifact 并给出路径 |
| Acceptance | 每个准则标记 `PASS`、`FAIL` 或 `NOT RUN`，并链接到支持它的输出、测试或快照 |
| Changes | changed files、核心 diff 摘要、tracked 与 untracked 的区别；未跟踪报告也必须列出 |
| Risks | 未验证假设、模型/额度/网络限制、测试缺口、后续动作和明确停止点 |

证据强度按以下顺序理解：直接命令输出/可复核 artifact > 静态检查或文件快照 > Worker 自报。推断、候选修复和“应该如此”必须标为 `Inference` / `Not verified`；旧 `HANDOFF.md`、旧报告和旧日志只能证明历史状态，不能覆盖当前实际 `git status`、当前测试输出或当前 diff。

涉及财务逻辑时，报告还要给出 `source → normalizer → projection → engine → API/export` 的证据链，以及关键字段的 `period`、`as_of`、currency、unit、source/source_type、`is_estimated`/confidence 和 `unavailable_reason`。缺失、币种不一致或模型不适用必须保持诚实隔离；报告不得以“测试方便”解释补零、未经审计的汇率或编造目标价。

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

### Worker 停止条件

Worker 在以下任一条件满足时停止当前 Task 并交付或升级，不继续“顺便优化”：

- Acceptance 全部有证据地 `PASS`，报告、产物和 `worker_done` 已准备完成；
- 遇到不可安全推断的架构/财务/权限决策，发送 `question` 并等待决定；
- 遇到外部故障、Ownership 冲突、额度/模型不可用且无授权回退，发送 `escalation`；
- 发现范围外缺陷或需要其他领域工作，记录为 Pending/风险并停止扩张。

发送 `worker_done` 后立即退出本轮；不得继续修改、测试、睡眠轮询或重复发送生命周期消息。纯等待只针对当前仍有 expected Dispatch 的 Coordinator，且无 active expected Dispatch 时禁止 `check --wait`。

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

- **真正独立并行**：仅当任务之间无实现依赖、无共享文件冲突时才允许并行执行，优先保持 1–3 个端到端 Task；并行前还要检查各自 quota/model 预算、验证资源和失败后的回收方案。
- **Ownership 是并行闸门**：同一个文件、共享配置、数据库/迁移、公共 API 或同一验收 artifact 不得由多个 Worker 同时写；必要时先由 Coordinator 拆成有顺序依赖的阶段。
- **批量启动后等待**：存在多个独立任务时，先全部完成创建与 dispatch 注入，再进入统一等待循环。
- **会话与终端复用**：同一业务领域、连续问题或 retry 优先复用健康的原 Worker terminal / session，以保留工作记忆。已结算的 Dispatch 需创建新的 Task 与 Dispatch 绑定该 terminal，严禁使用已失效的 lifecycle 凭据；只有原 Worker 无法安全复用时才新建 Antigravity terminal。
- **自定义终端就绪检查**：使用 `terminal create → terminal wait → worker-start` 启动带自定义参数的 Antigravity 时，必须确认 `terminal wait` 返回 `satisfied == true` 后才能执行 `worker-start`；命令返回本身不代表 terminal 已 ready。
- **生命周期结算**：只有 accepted settlement 才能执行 reuse、retain、release 三选一。任务验收通过且不再复用终端时调用 `worker-release`；需要保留时必须显式 `retain`。
- **复用不是偷渡状态**：复用必须创建新的 Task/Dispatch，重新声明 Goal、Ownership、Acceptance 和当前 continuation boundary；禁止复用已 settled 的 lifecycle 凭据，也禁止把旧报告当作新一轮通过证据。
- **停止即回收**：settled 后在 `reuse`、`retain`、`release` 中明确选一项；失败或 fallback 结束也要保留实际日志与产物路径，避免孤儿终端和无限重试。

## 7. Memory Architecture & Escalation Boundary (记忆分工与升级边界)

- **记忆分离**：Coordinator 仅维护“决策记忆”（架构设计、关键决策、验收判定、依赖拓扑）；Worker 维护“工作记忆”（代码实现细节、调试栈、临时数据）。严禁主控为了“核实”而重新做 Worker 已完成的细粒度调查。
- **自主推进**：在现有信息完备的情况下由 Worker 自主闭环普通技术问题；只有符合阻塞式 `question` 或 `escalation` 边界的事项才升级至 Coordinator。
- **用户升级红线**：仅在面临真实的产品业务取舍、用户目标发生不可推断的变更、或面临高风险不可逆破坏时，才向用户请求决策输入。

## 8. Weekly Review Loop (周复盘闭环)

每周复盘是可追溯的工作区快照，不替代 `HANDOFF.md`，也不重新激活已经关闭的历史任务。

### 快照内容

在报告中固定记录：

1. 周期与时区、执行日期、分支/HEAD，以及基线命令的实际输出摘要；
2. 本周 `committed`、`workspace dirty`、`untracked`、`historical`、`inference` 五类事实的分离清单；
3. 已完成、进行中、未完成/待决工作，各自对应证据路径、Task/Dispatch 和验收状态；
4. 关键教训（包括失败测试、错误的 Worker 自报、范围或 Ownership 冲突）、模型/provider、额度和 fallback 状态；
5. 下一周最多 1–3 个有明确 Owner/Acceptance 的动作，以及停止或升级条件。

### 执行顺序

`weekly-review.md` 快照 → 选择 1–3 个高收益文档/流程改进 → 查阅并记录近期一手来源 → 修改受 Ownership 保护的指引 → 做 Markdown 内链、空白和结构静态核验 → 写 `implementation-report.md` → Coordinator 按五步顺序验收。纯文档复盘不运行产品全套测试；若同时存在产品代码变更，必须在报告中分离“本轮未执行”和“其他轮次历史结果”。

若本周工作区仍有未提交或未跟踪产品成果，复盘必须链接其证据但不得清理、覆盖、代提交或把它们纳入文档 Task 的 changed files。只有新的交接触发条件满足且得到相应授权时才更新根 `HANDOFF.md`；否则把周复盘放在 `.scratch/<feature>/` 并标明它不是最新交接权威。

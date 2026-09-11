# Handoff Protocol

本指南定义项目交接（Handoff）的触发条件、文档结构规范以及接手代理的恢复执行流程。

## 1. Trigger & Generation Protocol (交接触发与生成规范)

### 触发时机
当 Coordinator 遇到上下文（Context）或 Token 额度即将耗尽，或因客观原因必须中断但当前任务尚未全部完成时，必须在仓库根目录创建或更新 `HANDOFF.md`，随后立即停止开发工作。

### 事实性红线 (Factual Integrity)
- **绝对保真**：仅记录经工具核实与证据确认的真实状态。
- **未知显式标注**：未经工具验证或无法 100% 确认的事项，必须明确标记为 `Unknown` 或 `Not verified`，严禁猜测或掩盖。
- **杜绝冗余灌水**：严禁写入对话流水账、完整源码切片或未消化的长篇原始日志。

### 必备十节结构 (Mandatory 10 Sections)
根目录 `HANDOFF.md` 必须严格包含以下 10 个标准章节：

1. `## 1. Objective`：明确记录用户最终目标与当前阶段的具体目标、适用范围与边界约束。
2. `## 2. Current State`：客观陈述系统当前的实际运行状态、服务存活情况与核心事实。
3. `## 3. Completed`：记录已完成并具备确凿证据支持的工作项，清晰区分“主控直接观察证据”与“Worker 上报证据”，不把 Worker 自报完成等同于最终主控验收。
4. `## 4. In Progress`：记录当前正在进行的工作项，必须精确包含：
   - Task ID、Worker Terminal 句柄、Dispatch ID 与会话状态。
   - 涉及修改的文件清单。
   - 已完成部分与尚未完成部分的具体界限。
   - 当前阻碍（Blockers）与具体错误上下文。
5. `## 5. Pending`：梳理后续待办事项，并严格按优先级排序（P0、P1、P2 等）。
6. `## 6. Key Decisions`：汇总关键架构、设计、技术选型与财务逻辑决策，并记录其权衡理由、排除方案及不可违背的约束。
7. `## 7. Repository Changes`：全面记录版本库状态：
   - 实际 `git status` 输出与未跟踪（untracked）状态说明。
   - 变更文件清单及每项文件的用途与改动点。
   - `git diff --stat` 实际情况（若索引为空无 tracked diff 必须如实说明统计限制）。
   - 强调保护未跟踪文件，严禁盲目运行破坏性命令。
8. `## 8. Verification`：列出实际执行过的命令及确切结果表格，明确标注 `PASS`、`FAIL` 或 `NOT RUN`，并附带证据路径与执行环境。
9. `## 9. Risks / Unknowns`：深入披露系统已知风险、潜在缺陷、未证实假设、测试局限与环境不确定性。
10. `## 10. Resume Here`：恢复执行的精准操作指引：
    - 接手后的第一个具体动作（First Action）。
    - 优先复用的 Task、Worker Terminal 与 Dispatch 会话。
    - 具体操作步骤与核验命令。
    - 阶段性验收准则（Milestone Acceptance Criteria）。

## 2. Takeover Sequence (接手恢复协议)

接手代理恢复工作时，必须严格遵守以下恢复准则：

- **先读交接再行动**：接手后必须首先完整阅读根目录 `HANDOFF.md`，严禁在未消化交接文档的情况下盲目启动全仓代码探索或直接开始编码。
- **从 Resume Here 与最新权威节起步**：严格按照 `Resume Here`（第 10 节）和文档中最新的权威更新记录（例如 `HANDOFF.md` 第 13 节最终验收与交付关闭状态）展开行动，仅做最小必要的存活性与状态核查。
- **禁止重复无效探索**：严禁推翻或重做前任已经充分调查、验证并形成确定结论的事项。
- **优先复用现有资源**：优先复用 HANDOFF 中记录的现有 Orca task、worker 终端及 dispatch 会话，避免不必要地启动新终端或破坏已存在的上下文。
- **历史关闭状态保护**：若最新权威章节已明确某些历史需求或前序轮次已验收关闭（例如真实多 Ticker 需求已在第 13 节闭环交付），接手代理严禁擅自重新激活或恢复该已结算任务，本次工作仅聚焦当前新任务范围。

## 3. Weekly Review & Provider-Fallback Addendum (周复盘与提供商回退附录)

周复盘与交接承担不同职责：`HANDOFF.md` 只在触发交接时更新并承载恢复所需的最小权威状态；周期性复盘应写入 `.scratch/<feature>/weekly-review.md`，不得为了记录本周工作而覆盖当前交接或重新激活已关闭任务。

周复盘和交接在涉及代理执行时，至少区分并记录：

- 周期/时区、分支与 HEAD，以及 `committed`、`workspace dirty`、`untracked`、`historical`、`inference` 的事实来源；
- Task/Dispatch、Worker terminal、Ownership、Acceptance 和每项结论对应的 artifact 路径；
- 实际 provider/model、额度或可用性状态、fallback 原因、时间、已知 `resets_at`/下次探测时间；不可验证时写 `Not verified`；
- 已执行命令、工作目录、退出码、测试的 `PASS`/`FAIL`/`NOT RUN`，以及副作用是否已经发生；
- 当前完成边界、未完成事项、风险、第一恢复动作和停止条件。

当默认 **Antigravity / `gemini-3.8-flash-high` / Full Access** 不可用或额度受限时，只有在宿主实际暴露并授权的前提下，才按 `PrimaryAvailable → Limited → FallbackActive → ProbePrimary` 采用 **Codex Luna Max**。回退不能改变财务不变量、来源链、仓库安全或验收门槛；已经产生工具/文件/外部请求副作用后，不得重放非幂等动作，必须在交接中写出 continuation boundary 和已执行产物，恢复时沿原 Task/Dispatch 继续而不是重复执行。

交接、复盘和验证报告严禁包含 API key、token、密码、凭据内容、内部能力密钥或可直接重放的敏感请求；只记录脱敏后的 provider/model、状态和证据路径。

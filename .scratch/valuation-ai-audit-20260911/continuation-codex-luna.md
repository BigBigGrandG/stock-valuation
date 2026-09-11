# Antigravity 额度中断后的接续边界

## Goal

用户明确要求后续改用 Codex Luna / max Worker，接续工单 01/02 第四轮，不重做已完成工作。沿用 implementation-01-02.md 和 rework-01-02-r4.md 全部 Acceptance，前序 rework-r2/r3 按需定位背景。

## Current State / Evidence

- 基线 master / 11b04955ad62e9825fa778975a2f136f92a143a2；产品改动全部未提交。不要 reset/clean/commit/push。
- 旧 Worker task_5c87c1406885 / ctx_607b82d01f25 / terminal term_5abf4fd1-a6db-4d7f-a593-73affbcefd0c 已明确显示 Individual quota reached，停于输入提示符；未收到有效 R4 worker_done，也没有 implementation-report-r4.md。
- 最后有界输出显示它正在读取 projections、valuation_service、exportMarkdown 和旧测试。当前 base.py 等已有额外产品改动；精确完成程度未验证，必须继承当前文件，不假定全部未做或已做。
- 主控局部核对确认：base.py 新增 da_period/da_as_of；Normalizer 已开始使用这两个元数据；run_all_engines 已增加部分旧非共识值清空分支。verification/r4/red.log 已存在（17:00:47，41482 bytes），没有 green 或 R4 完成报告。这些是部分实现证据，不是验收通过。
- 旧 dispatch 已通过 worker-abandon 撤销任务权限，结果 abandoned / processAction none；保留旧终端与文件，不再让它继续写本任务。
- 额度提示相对重置时间为 2h17m24s，但该终端提示不是当前计时器，绝对 resets_at 未验证。用户已决定改提供商，不反复探测 Antigravity。
- R3 报告误报全绿；主控先前实跑全量得到 10 failed / 303 passed，exit 1；见 rework-01-02-r4.md。这是历史测试基线，不代表中断后代码的当前结果。新 Worker 先核查现状和补丁，再运行定向/全量测试建立真实反馈。

## Scope / Ownership

Worker 端到端负责 01/02 相关 backend/frontend/测试及 implementation-report-r4.md、verification/r4/。主控负责接续记录与最终验收。不另派 Worker。03—08 延后。

当前 AGENTS.md、docs/agents/orchestration.md、handoff.md、project-constraints.md 及 .scratch/workflow-optimization-20260911/ 是工作区其他成果，读规范但不得覆盖、回滚或计入本任务贡献；ai_comment/ 和全部历史审计证据保留。禁止重放不明非幂等外部操作。纯实现/测试自主闭环，不向用户索取普通操作批准。

## Acceptance / Stop

接续启动核验：Orca launch effective 为 codex / gpt-5.6-luna / max；新 task_88095c628df0 / ctx_f4560ebb6d38，terminal term_99467d04-990e-44de-ba9e-6aaf79c5b32d。原始 transcript 已出现 Worker 接续确认，projection activity=working、liveness=live，状态进入 FallbackActive。此记录不包含凭据。

优先处理 R4 的六项缺口：真实失败分类修复与报告勘误、projection到engine隔离、DCF共识覆盖/期间、D&A元数据贯穿、全部桥接恒等式与导出披露、指定四标的及前端行为验证。遵循 source -> normalizer -> projection -> engine -> API/export。

如需变更既有错误算法测试，保留其原本期间/隔离/缓存不变量并解释替换；不得跳过失败换成功。以实际输出/退出码为准。完成报告写明实际 provider/model/effort 与中断接续、实际新增修改、日志、剩余限制，发送新 dispatch 的有效 worker_done。不要使用旧生命周期凭据，不在报告保存凭据。主控验收前不关闭工单。用户要求主控没有其他工作时停止等待，不影响 Worker 自主完成本任务。

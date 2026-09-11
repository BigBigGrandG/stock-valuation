# 工单 01/02 主控最终验收

日期：2026-09-11。基线 master / 11b0495；本次代码与证据保留在未提交工作区。结论：**01/02 在本次实现及验证范围内验收通过，关闭工单**。其他 03—08 仍按原状态延后；本记录不改变历史审计事实，也不是对所有股票估值准确性的保证。

## 验收依据

- 已核实 R6 task_54e01348ad83 / ctx_acc0dce139db 的有效 succeeded worker_done，执行者为接续原会话的 Codex gpt-5.6-luna / max。
- 主控独立执行 `.venv/Scripts/python.exe -m pytest backend/tests/ -q`（cwd 项目根）：exit 0，**346 passed、2 warnings、5.27s**。两条为既有 Starlette/AnyIO 弃用警告。
- R4 前端 typecheck/lint/build、导出契约 3 项、真实浏览器 fixture 后端 E2E 3 项通过，证据见 implementation-report-r4.md 及其原始日志；R5/R6 未改前端，不将这些历史结果写成新执行。
- 主控核对 R6 期间解析及生产 DCF eligibility 局部代码：有锚点的相对年度标签可用；前两期缺失、非有限或非正时不再回退历史 FCFF。验收保留 standalone engine 的显式历史兼容边界，不允许生产 API 使用该退路。
- R5 保存指定 AMD/META/GOOG/NVDA 七类 live provider payload 与完整响应；R6 使用这些历史实采 payload 离线回放，不是重新网络抓取。主控已读取回放及 artifact-check 日志，12 案（四标 × 完整/缺FY1/缺FY2）全部通过。
- 完整回放：AMD、GOOG、NVDA DCF 可用，FY1/FY2 bridge 与 engine input 的值/期间/as_of 对账；META 的本次驱动预测 FCFF 两期均负，DCF 不适用。缺年度案例全部隔离，部分预测仍可作为证据展示，但不进入 DCF。

## 工单结论

| 工单 | 结果与边界 |
| --- | --- |
| 01 前瞻合成指标 | 独立利润率、D&A、CapEx、NWC、税率及融资驱动、共识优先/用户覆盖、FCFF/FCFE 对账及 API/页面/Markdown 披露已实现；默认生产预测不再使用旧统一历史现金流增长退路。缺关键驱动及不适用模型隔离。 |
| 02 季度 bundle 回退 | 季度缓存初始化及异常传播已修复；真实 bundle 受控源读取、TTM 与 PIT、缺数/预算/限流回归及 live 数据链路证据覆盖。上游实际缺数仍允许有说明的年度回退。 |

## 限制与交付状态

- 前瞻运营驱动仍包含显式历史延续假设，并非管理层指引或独立分析师全科目共识；回放金额仅是该输入与假设下的计算结果，不是新的投资建议。
- 日期与数据来源受 provider 元数据和覆盖限制；本次并非对所有美股、所有52/53周财年及供应商字段变体的穷尽认证。历史数据回放不保证下一次 live 调用可用性。
- 保留 R1—R6 报告、失败日志及勘误。尤其 R3 原报告误报全绿，后续 R4/R5/R6 与主控实测才是对应版本的验证依据。
- 未 commit、push、部署或重启用户服务。已有 AGENTS/docs 工作流修改、workflow-optimization 及 ai_comment 成果保持不动，不算本次产品修复贡献。
- 本次无剩余 Worker 实现任务。任何后续部署、提交或其他工单实施需另行指令。

关键证据：implementation-report-r4.md、implementation-report-r5.md（含勘误）、implementation-report-r6.md、verification/r5/live-validation-r5.json、verification/r6/full-after.log、verification/r6/replay-r5-payloads-r6.json、verification/r6/artifact-check.log。

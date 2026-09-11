# Round 3 主控验收退回

## Goal / Scope / Ownership

延续 implementation-01-02.md 和 rework-01-02-r2.md；原 Worker 端到端负责 01/02，主控负责验收。R2 task_e8cd508a8585 / ctx_3904399d304c 有效 succeeded 已核实，但产品验收不通过。保留既有报告，新增 implementation-report-r3.md、verification/r3/。不改 03—08，不 commit/push、不清理既有成果，不另派 Worker。

## 已确认进展

季度字段初始化已实现，现金流历史增长主分支已删除，关键现金流驱动改为 Optional，新增 provider 穿透测试及前端编辑。主控读取 green.log 确认 301 passed、2 warnings（日志 4.53s，与报告 4.75s 不同，报告需以实际记录为准）。这些不等于全部财务契约满足。

## Failed Acceptance / Evidence / Action

1. projections.py 仍保留 raw_forward_ebitda 非共识 -> base_ebitda * (1 + effective_g) 分支，优先于 revenue * margin；provider 是否仍生成该旧值需闭环清除。不能只修现金流而遗漏工单01的 EBITDA。默认路径断言 EBITDA 等于同期间 revenue * margin（允许明确舍入）。
2. 直接共识 EBITDA 被保留时，ebitda_margin 却优先取历史利润率；直接共识 FCFF 被保留时，bridge 却展示独立计算 NOPAT/CapEx 等。当前 bridge 构建仅判非空，无恒等式或来源兼容检查。分别测试直接 EBITDA、FCFF、FCFE 共识，保留来源与期间；不可能勾稽时展示独立共识与估算桥的区别/差额或不输出伪桥，绝不能声称五式恒等成立。非共识 raw_forward_fcff/fcfe 的最后回退也不能绕过缺驱动隔离。
3. 当前 forward_fcff_1y 可明确标 NTM，而 forward_fcff_2y 固定 FY2E，DCF 引擎没有对应时间轴更改。必须为 DCF 单独生成一致的前两期（原契约明确禁止 NTM 当 FY1），EV/FCF 与 PE 按所选 horizon 对齐。不要仅改标签。next_fy 分支的桥接/metric FY1E 标签也应核实。
4. forecast_start 固定 as_of，current_fy 却展示全年收入；这是 stub 起止与全年金额混配。使用真实财年起止，NTM 使用有效估值日，fallback 使用 effective_horizon。replace(year+1) 在闰日会抛 ValueError，增加离线日期测试。驱动来源须含各自实际基期起止/as_of，不只是 derived_historical 字符串。
5. statement_aggregator 新增 NWC 直接使用现金流表 Change In Working Capital 原值，projections 再减该值。请用真实上游行定义及 CFO 对账验证现金流贡献与资产增量的符号转换，不能用自造同符号 fixture 证明语义；Change In Other Working Capital 只是分项，不能当总 NWC。新增 annual_da 回退到 TTM effective_da 却未独立披露期间；禁止历史科目混期后标同一 TTM。
6. restrictions_note 声称排除非经营投资损益，但 EBITDA 直接采用 vendor EBITDA，未证明运营口径剔除；R2 live GOOG EBITDA margin 73.29% 需要从原始报表分项验证，并区分标准 EBITDA 与运营预测基准。本次只处理桥接必需口径，不扩大为工单06 EPS 调整。无法确认则披露实际限制或隔离，不写不存在的归一化处理。

## Acceptance / Verification

先以失败回归锁定上述实际默认/共识/日期路径，再修复；不得删除有用不变量换绿。维持原契约缺值/429/预算/真实 bundle 验收；按高风险财务输入链路核验原始报表 -> 标准化 -> 驱动 -> 模型输入 -> API/Markdown 恒等式与期间。真实 Live 证据应有原始源科目及响应，不只是桥接摘要；若有网络限制如实记录。相关前端行为/导出测试与后端全量回归保存命令、退出码、日志。三句有效 worker_done + 新报告，工单验收前不关闭。普通实现自主推进，重大无法推断决策才 ask。

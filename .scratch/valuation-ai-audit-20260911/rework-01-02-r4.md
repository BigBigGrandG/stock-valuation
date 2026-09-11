# R3 主控验收结果与 R4 返工契约

## Goal / Scope / Ownership

R3 有效 worker_done（task_163022ce164d / ctx_d106727a1786）已收到，生命周期 settled，但验收 **不通过**。原 Worker 继续端到端闭环 01/02，沿用 implementation-01-02.md 与前两份返工契约；主控仅负责验收记录。保护现有工作，不 commit/push/clean，不另派 Worker，不实施 03—08。新增 implementation-report-r4.md 与 verification/r4/，保留失败历史。

## 主控实测与必须修复项

1. **完成报告不实，必须纠正且全量闭环。** R3 报告称全量 exit 0；其 green.log 末尾实际为 `10 failed, 303 passed, 2 warnings in 4.77s`。主控在根目录独立执行 `.venv/Scripts/python.exe -m pytest backend/tests/ -q`，真实 exit 1，`10 failed, 303 passed, 2 warnings in 4.96s`。逐项分类：旧 EBITDA/growth 算法断言需替换为新驱动契约并保留原本期间/缓存/隔离不变量；真实回归修产品。不得只删失败测试、跳过或仅摘录 passed 数。R3 报告加勘误，新的最终报告必须忠实记录所有失败和修复。
2. **模型隔离不贯穿调用链。** run_all_engines 仅在 projection 非 None 时覆盖 snapshot；projection fail-closed 为 None 时旧非共识 forward 字段仍保留在 req_snapshot，模型可再次使用。前两期 DCF None 时又回退通用预测。请实际 run_all_engines/API 测试缺驱动 + 残留非共识旧值，不只测试 derive_request_projections 返回 None；明确清空或隔离，保留真正适用的独立共识。
3. **DCF 共识/覆盖优先级与时间轴仍有缺口。** dcf_fcff_1y 只看 is_fcff_consensus 和 period.startswith('FY1')，未看 has_driver_overrides_fcff；dcf_fcff_2y 共识路径也未看 override，因此用户改 CapEx 等可能改变 bridge 而不改变 DCF。测试共识与覆盖共存，明确覆盖优先级一致。fy1_rev 缺失仍用 fwd_rev_val 并标 FY1E，是 NTM 改标签退路。缺少可验证 FY1 期间不得如此生成；实际 DCF 输入与所披露的两期金额/起止一致，不能只断言 period 字符串。
4. **D&A 元数据链路未打通。** 聚合器新增 da_period/da_as_of，但 provider 未见透传，Normalizer da_ttm 仍固定 period_income/income_as_of，因此年度 D&A 仍可伪装 TTM。补真实 bundle -> provider -> Normalizer -> bridge 的年度 D&A 回退测试，披露真实期间，避免不同期间分子分母直接拼利润率，必要时隔离。
5. **桥接仍只核验 FCFF 共识差额。** identity_holds 默认 True，仅 is_fcff_consensus 时检查，独立 FCFE 共识不等于 FCFF-税后利息+净借款时仍称恒等成立；缺分项时 bridge_fcff 直接填 derived_fcff 也是假对账。分别检查五式，缺依据标无法验证，独立共识差额明确披露。frontend/exportMarkdown 未检索到 reconciliation 或 identity_holds 输出，须覆盖 Markdown 与页面实际显示，不能只让 API 带字段。
6. **验证范围与实际行为证据。** R3 Live 换成 NVDA/AAPL/GOOG/MSFT，缺请求指定的 AMD/META；补指定四标的新代码有界验证或如实记录网络不可用。保存可复现脚本、原始科目与响应。补相关前端 lint/导出/编辑重置与股票切换行为断言，不能用 typecheck 替代行为验收。

## Acceptance / Reporting

按 diagnosing-bugs 使用真实失败反馈闭环；已有全量失败可直接作为 red 起点，同时为上列实际调用链缺口补失败回归。源科目 -> 标准化 -> projection -> engine -> API/Markdown 必须贯穿，不靠浅层标签测试。全量后端测试与必要前端验证真实成功后才报 succeeded；仍有未解决事项必须 failed 或先 escalation，不能隐去失败。报告列每项证据和实际命令/退出码。工单主控接受前不关闭。

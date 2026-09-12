# 三项致命问题实施契约（2026-09-12）

基线：master/68e98d4，与 origin/master 一致；启动前工作区干净。禁止 commit/push/clean/reset。四模型继续独立输出 Low/Base/High；禁止编造数据或综合结论。三个 worker 使用 Codex Luna Max，分别端到端负责互斥文件面，主控最终验收与解决跨模块冲突。

## Worker A — 取消 Composite
Goal：移除综合估值计算、API/schema/frontend/Markdown 中的 composite 结果与权重语义，保留四模型独立输出和 unavailable 语义。
Ownership：backend/app/engines/composite.py（可废弃但不得破坏导入）、backend/app/services/valuation_service.py 中 composite 调用/组装、domain response/schema、frontend types/components/pages/export/styles、相关测试/docs。不得改 projections.py、dcf.py 核心公式。
Acceptance：真实 API 不返回可计算 composite/target/weights/effective weights；UI/Markdown 无 Composite/Fair Value/目标综合 section；四模型各自 Low/Base/High，单模型 unavailable 不重分配；回归与前端检查。

## Worker B — Forward FCFE 借款隔离
Goal：禁止 net_borrowing_ttm 进入 forward FCFE；仅用户 forward override、明确 provider forward borrowing 或可靠模型可用，否则 normalized forward borrowing=0 或模型 unavailable，并区分历史字段和 forward 字段、warnings。
Ownership：backend/app/services/projections.py forward FCFE bridge、backend/app/providers/{base,yfinance_provider,statement_aggregator}.py 相关 forward borrowing normalization、backend/app/engines/fcf_yield.py 仅相关质量/warning、专属测试/证据。不得改 composite 或 dcf.py。
Acceptance：Case A/B/C 精确断言；META/GOOG 回放不含 TTM 借款；历史 TTM 仅展示；FCFE 质量/不可用诚实，禁止把 TTM 标成高质量 forward proxy；全后端回归。

## Worker C — Fiscal-year DCF time axis
Goal：DCF 预测现金流期间与 valuation date 对齐，FY1 采用 stub/prorating（除非 valuation date 为 fiscal start），真实日期差计算 discount time、PV/TV，并在 API/UI/Markdown 显示 period start/end、t、factor、PV。
Ownership：backend/app/engines/dcf.py、相关 domain DCF fields、frontend DCFScenarios/export（仅时间轴字段）、专属测试/证据。不得改 composite 或 projections.py。
Acceptance：2026-09-11 对 2026 FY1/FY2 精确断言 stub、t<1、FY2≈1.3、TV真实终点；fiscal start 可完整FY1；保留增长衰减/敏感性/01/02门槛；真实四 ticker 验证或清晰 replay。

每个 worker 报告必须列完整命令/cwd/exit、dirty基线、provider/model、changed files、风险与未决。worker_done 三句话且只发一次；主控按五步验收。

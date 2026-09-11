# 01/02 主控验收退回 / Round 2

## Goal / Settlement

已核实 task_886e7bc60e29 / ctx_d032a74b937d 的有效 succeeded worker_done。生命周期完成不等于验收通过；本轮验收不通过，复用原 Worker 端到端补齐，不关闭两张工单。

## Scope / Ownership / Constraints

沿用 implementation-01-02.md 全部五要素契约和文件所有权。仅修复 01/02；保留当前成果，不 commit/push，不改 03—08。原报告保留为历史证据，新增 implementation-report-r2.md 和 verification/r2/。Worker 不另派人。按 diagnosing-bugs 先写真实路径失败回归并保存实际 red 输出，再修复；既有根因和下列代码证据明确，不必重新做假设探索。

## Failed Acceptance / Evidence

1. projections.py 仍有多处分支计算 base_fcff/base_fcfe/base_ebitda × (1 + effective_g)，且优先于默认 bridge 分支；provider 的旧合成预测未移除。新增 override 路径不能代替修复默认 live 路径。去除生产历史现金流统一增长退路；旧测试固化错误算法可按契约解释替换，不以保留错误结果换全绿。
2. D&A 缺失采用 EBITDA × 15%，CapEx、NWC、interest、net borrowing 缺失默认零，部分被标 derived_historical。没有实际依据的数值不能进入估值。打通真实 provider/aggregator 到 normalizer 科目来源、符号、期间；缺关键驱动隔离相关模型。非现金营运资本现金流符号、FCFE 与 CFO-capex 区别需对账，不能把 FCFE 当普通 FCF 倒算 CapEx。
3. financial_bridge 把独立计算 NOPAT/CapEx 等与旧 growth 路径 FCFF 同时拼装，未保证桥接恒等式。默认、覆盖、直接共识、缺数都需验证；直接共识与自建 bridge 不同口径不得拼成假对账。模型实际输入与披露数字一致。
4. fwd_rev_val 优先 blended_rev，却将衍生指标标 FY1E；桥接只有 horizon 字符串，没有完整预测起止、as_of、各驱动来源期间；FY2 还可退到 FCFF × growth。明确 FY1/FY2/NTM，DCF 前两期不得拿 NTM 当 FY1。补足币种/单位、来源、基期与预测期，以及 SBC/租赁/非经营项限制。
5. test_issue_02_bundle_with_valid_quarterly_statements_produces_ttm 直接调 aggregate_ttm_cashflow，未调用 bundle/provider；PIT 测试也只调 helper。补受控 upstream -> 真实 bundle -> provider/normalizer/service 回归，覆盖缺季度/缺值、AttributeError、429、请求总预算。不要 mock 掉被修的 getter/_fetch_property 来声称真实链路通过。
6. schema_and_reset 测试仅验证 schema，未 reset；consensus 只测 EBITDA；bridge 仅测完整用户覆盖。补默认真实路径 bridge、FCFF/FCFE 共识来源期间保护、缺驱动隔离、实际 API reset/股票切换与 Markdown 导出内容断言。前端目前只类型与导出改动，需提供可理解的驱动参数编辑/披露和相关验证，或明确现有界面如何满足契约。
7. verification/evidence-01-02.md 仅摘要，live 命令是 python <script>，无可复现脚本与原始响应；报告 294 与 8 项的数量关系也需以实际输出为准。保存真实命令、cwd、退出码、完整测试日志、red-green、四 ticker 新代码有界 live 原始响应/来源期间。网络缺数或限流如实记录，不要求四模型全有值。

## Action / Acceptance

按上述缺口修复、测试、对账，完成原契约全部验收项；只返回三句 worker_done，报告详细列缺口逐项证据、命令退出码、diff stat、剩余限制。不得凭编译通过或四模型有数字宣称财务正确。常规实现自主推进，确有重大业务缺口再 ask。

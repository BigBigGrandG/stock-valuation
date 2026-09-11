# R5 主控验收与 R6 有界返工

## Goal / Scope / Ownership

原 Codex Luna max Worker 继续 01/02，仅修期间校验导致的误隔离及直接关联测试/证据。沿用原实施契约，不扩展03—08，不另派 Worker，不 commit/push、不动其他工作流文档。Worker 负责相关代码测试与 implementation-report-r6.md、verification/r6/；主控最终验收。

## 已核实通过部分

R5 task_150a3c010ae2 / ctx_0b75e50e443e 有效 succeeded。主控独立全量复跑 exit0：328 passed、2 warnings、4.84s。缺 FY1 时清空历史 FCFF 的生产隔离已确认实现；R5 保存四标七类 provider payload 及完整响应。保留这些成果，不恢复历史增长退路。

## 确定问题及复现

projections._is_explicit_fy_metric 首先执行 `if not period.startswith('FY') ...: return False`，导致后面的 0Y/+1Y/FORWARD_1Y/FORWARD_2Y 映射永远不可达。R5 live artifact 对四标都提供 forward_revenue_1y_period='0y'，并有 forecast_fiscal_year_end：AMD 2026-12-27、META/GOOG 2026-12-31、NVDA 2027-01-25。全部 DCF false 不能归因为上游无 FCFF 一致预期：任务明确允许有依据的独立驱动预测，而收入期间被错误拒绝。

主控离线复现（cwd root，PYTHONPATH=backend）：

```python
from datetime import date
from decimal import Decimal
from app.models.domain import FinancialMetric, SourceType
from app.services.projections import _is_explicit_fy_metric
m = FinancialMetric(value=Decimal(100), unit='USD', period='0y', source='test', source_type=SourceType.ANALYST_ESTIMATE, as_of=date(2026,9,11))
print(_is_explicit_fy_metric(m, 1, date(2026,12,31)))
# 实际 False；合法的明确财年锚点 + 相对年度标签应通过验证。
```

## Action / Acceptance

1. 修复分支顺序/期间解析，明确有效相对年度标签 + 可核实财年锚点的支持；保持无锚点、NTM/TTM、错误slot/错财年等拒绝。不要仅放宽所有字符串，也不要把未知财年默认为12月31日。
2. 用真实 provider/normalizer/projection/engine 路径回放 R5 已保存四标 payload，验证合法驱动路径能进入 DCF；缺驱动仍隔离。不要求四标必有数值，但逐项给出真实原因，不能将本地 parser 错误解释为上游缺数。
3. 对前两期各自完整驱动/期间缺失保持明确隔离，不能 FY1 合格但 FY2 缺失后再次由 engine 历史/growth 补出未经验证第二期（第3—5年策略不改）。
4. 更新有界新代码 live 验证或离线 payload 重放证据，明确区分本次新抓取与历史原始输入重放；DCF 可用时真正运行桥接金额/期间与 engine input 的一致性断言，而不是只检查 unavailable 无泄漏。若脚本对输入键或类型假设错误，修脚本并如实记录。
5. 保存 red-green、全量后端结果与报告；frontend 未改可沿用 R4 证据。纠正 R5 报告把四标不可用仅归因为 upstream null/uncertified 的解释（保留历史结论但加勘误）。所有工单验收前不关闭。完成发当前新 dispatch worker_done，主控仅剩等待时按用户要求停下。

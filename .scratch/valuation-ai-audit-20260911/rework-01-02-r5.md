# R4 主控验收 / R5 定向返工

## Goal / Scope / Ownership

原 Codex Luna max Worker 接续 01/02，沿用原实施契约。R4 task_88095c628df0 / ctx_f4560ebb6d38 有效 succeeded 已核实，但主控未接受关闭。仅修以下确定缺口及必要回归，不重做已通过部分，不扩展 03—08。Worker 负责相关 backend/frontend 测试与新 implementation-report-r5.md、verification/r5/；主控负责最终验收。不另派 Worker，不 commit/push，不修改其他工作流文档，不清理既有成果。

## 已接受的证据

主控独立执行 `.venv/Scripts/python.exe -m pytest backend/tests/ -q`：exit 0，318 passed、2 warnings，4.81s。R4 前端浏览器日志实有 3 passed。R3 报告误报的问题已在 R4 报告明确记录。保留这些证据，不再声称 R4 全量测试有失败。

## 1. 确定失败：DCF 历史退路绕过 projection 隔离

主控用已有 R4 fixture 离线执行下列逻辑，得到 `dcf_projection None model_available True`，且 calculation_steps 明示 `configured fallback FCFF growth`：

```python
import runpy
from app.services.valuation_service import run_all_engines
from app.services.projections import derive_request_projections
from app.models.domain import ValuationAssumptions, SourceType
t = runpy.run_path('backend/tests/test_audit_issues_01_02_regression_r4.py')
s = t['_snapshot'](capex_ttm=None, fcff_ttm=t['_m']('700', source_type=SourceType.ACTUAL))
p = derive_request_projections(s, ValuationAssumptions())
d = run_all_engines(s, ValuationAssumptions())['dcf']
print(p.dcf_fcff_1y, d.available, d.calculation_steps)
```

根因：run_all_engines 仅在无 forward_revenue 且 fcff_ttm 不是 ACTUAL/FIXTURE 时清空历史值；有收入预测时甚至 DERIVED 历史值也保留。run_dcf 据此补生前两年。原契约不允许缺关键驱动后重新走历史 FCFF×growth 的生产退路，历史数据真实也不能证明未来预测成立。

修复要求：生产入口没有合格前两期驱动/独立共识时应诚实隔离，不应让历史 FCFF fallback 替代缺失前瞻关键输入。请测试 ACTUAL、DERIVED、FIXTURE，各种有无收入预测与仅 FY2 情况，实际进入 run_all_engines/API 断言。独立 engine 历史测试或 demo 可保持明确隔离兼容，但不能因此放开普通 live 请求。保持第3—5年既有策略，工单04不在范围。

## 2. Live 证据仍不够对账

R4 live-validation-r4-final.log 仅价格、models_available、financial_bridge 布尔摘要，provider 字段为 null。报告命令是方法名而非完整可执行脚本。原契约要求指定 AMD/META/GOOG/NVDA 的新代码原始来源/响应/期间，可复算关键桥接与模型输入。补一个保存原始源科目和完整响应的有界脚本；必须区分 live/demo，不要求四模型都有值。网络失败如实记录，不用旧 R2/R3 响应冒充新结果。基于采集结果实际断言 bridge 与 engine 的期间/输入一致，不以有数字为正确性证据。

## Acceptance / Reporting

先将上面确定复现转失败回归，修复后定向测试及全量 backend 回归；frontend 若没有新代码变化可引用 R4 原始通过证据，不强制重跑。报告所有命令、cwd、退出码、实际变更和限制。只处理本轮所列缺口及直接相关回归，不为了保留旧测试而降低金融保真。结束发送当前新 dispatch 的 worker_done 与 R5 报告；工单仍待主控验收。主控交付任务后按用户要求不持续等待，不影响 Worker 自主完成。

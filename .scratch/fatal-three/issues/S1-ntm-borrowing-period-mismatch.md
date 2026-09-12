# S1（严重）：NTM FCFE 与 forward net borrowing 期间可能错配

状态：resolved (2026-09-12)

`backend/app/services/projections.py:791-793` 对 `ntm` 选择 1Y borrowing；`backend/app/providers/yfinance_provider.py:761-763` 对该字段默认标注 `FY1E`。未来 provider 返回完整 FY1 borrowing 时，会与滚动 NTM FCFF 混用。当前 live 数据为空，未触发该路径。

后续方案：要求 NTM borrowing；仅有 FY1/FY2 时按真实 fiscal stub/FY2 权重转换，或明确 unavailable。

验收：NTM/FY1/FY2 period-aware resolver、provider metadata 和回归测试已完成；全量后端测试通过。

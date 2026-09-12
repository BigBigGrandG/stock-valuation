# F1（致命）：历史 TTM FCFE 仍可进入 Forward FCF Yield 估值

状态：resolved (2026-09-12)

`backend/app/engines/fcf_yield.py:100-105` 在 forward FCFE 缺失时回退到 `snapshot.fcf_ttm`。虽然标记 `historical_proxy`、质量 LOW 并发出 warning，随后仍按目标 FCF yield 计算 Low/Base/High 价格。该 TTM FCFE 可能包含历史净借款，形成融资现金流永久资本化旁路。

后续方案：只接受真正 forward FCFE 或明确 forward bridge；`fcf_ttm` 仅展示/历史比较，否则返回 unavailable。

验收：`fcf_yield.py` 已移除 TTM 估值回退；相关回归与全量后端测试通过。

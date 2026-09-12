# S2（严重）：Forward FCFF 依赖单期 TTM 比率机械外推

状态：resolved (2026-09-12)

`backend/app/services/projections.py:473-640` 在缺少 forward 驱动时用 TTM EBITDA margin、D&A/Revenue、CapEx/Revenue、NWC/Revenue 和税率推导 forward FCFF；lineage 标为 `derived_historical`，live 报告也显示该来源。

后续方案：优先 forward/多期历史或行业可比驱动；无法验证时降低质量并明确限制。

验收：已实现 forward → 多期历史 → 行业可比 → 明确降级 TTM 的 lineage hierarchy，并补充缺失隔离与回归测试。

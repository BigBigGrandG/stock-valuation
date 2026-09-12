# 当前严重性复核（2026-09-12）

## 基线与证据

- Git 基线：`master`，HEAD `7aaec80`（工作区干净）。
- 全量测试：`.\.venv\Scripts\python.exe -m pytest -q`，`386 passed, 2 warnings`。
- 最新四标的 live 证据：`.scratch/fatal-three/live-validation-final.json`；此前复核报告：`.scratch/fatal-three/final-acceptance.md`。
- Composite 与上一轮 DCF fiscal-date 对齐问题已关闭，本记录不重复列入。

## 已确认并落盘

| 等级 | 编号 | 结论 |
| --- | --- | --- |
| 致命 | F1 | FCF Yield 在缺少 forward FCFE 时仍把 `snapshot.fcf_ttm` 作为估值输入。代码见 `backend/app/engines/fcf_yield.py:100-105`；虽降级为 LOW 并告警，仍会生成价格，故历史融资污染仍可绕过正常 bridge 进入估值。 |
| 严重 | S1 | NTM borrowing 期间未对齐。`backend/app/services/projections.py:791-793` 对 NTM 取 1Y，而 `backend/app/providers/yfinance_provider.py:761-763` 默认该字段 period 为 `FY1E`；一旦 provider 返回该字段，滚动 NTM FCFF 会与完整 FY borrowing 混用。当前 live 样本字段为空，属于已证实代码风险、尚未被当前数据触发。 |
| 严重 | S2 | Forward FCFF 的 EBITDA margin、D&A、CapEx、NWC、税率在缺少 forward 驱动时由单期 TTM 比率机械外推。代码在 `backend/app/services/projections.py:473-640` 明确标记 `derived_historical`；live 报告亦出现该 lineage（如 `live-validation-final.json:557`）。 |
| 严重 | S3 | 公司特异性参数缺失时，系统 fallback 倍数/yield/WACC 仍可直接产出可用价格。固定值定义于 `backend/app/config.py:14-26`；live 报告显示 `selection_layer: system` 及 `WACC lineage: fallback`。告警存在，但当前呈现仍容易把参考情景理解为公司特异性估值。 |
| 严重 | S5 | FY1 stub 金额仍按全年 FCFF × 剩余财政日比例，没有优先采用 `Full FY forecast − YTD actual`。代码见 `backend/app/engines/dcf.py:561-580,696`，live 报告记录公式及 `proration_factor`（如 `live-validation-final.json:5840-5854`）。时间点已对齐，但季节性/集中 CapEx 标的金额仍可能偏差。 |
| 严重 | S6 | DCF 价值对终值及 fallback WACC/g 的联合暴露仍高。live 报告中 Base TV 占比约 0.77（不同情景/标的约 0.74–0.82），同时 WACC lineage 为 fallback；这使大部分估值依赖未公司化的终值参数。该项是已量化的模型风险，不是声称 DCF 公式错误。 |

## 不记录（证据不足/属于显式建模政策）

**S4 高成长企业五年 fade horizon。** `backend/app/engines/dcf.py:49,867` 确实固定五年并在第 3–5 年衰减至 terminal growth，但这是当前明确的模型政策；现有代码、测试和四份 live 报告没有定义“必须按成长速度自动延长”的正确性契约，也不足以证明固定五年必然错误。因此本轮不把它写入问题清单。

## 当前清单

本轮确认：**1 个致命（F1）+ 5 个严重（S1、S2、S3、S5、S6）**。这些记录仅供后续处理，本轮未修改产品代码。

## 2026-09-12 修复进展

F1、S1、S2 已由 worker 完成实现并经主控验收；定向回归 25 passed，全量后端 405 passed，四标的 live 验证整体 `ok`。本次产品代码已修改，以上三项工单状态更新为 resolved；S3、S5、S6 仍待后续处理。

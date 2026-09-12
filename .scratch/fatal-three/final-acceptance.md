# 三项致命问题最终验收（2026-09-12）

## 结论

三项问题均已修复并通过主控整合验收。基线为 `master/68e98d4`（与
`origin/master` 一致）；工作区已有修改均保留，未执行 commit、push、clean、reset
或部署。Worker 使用 Codex / gpt-5.6-luna / max（运行时遥测按报告标记为未独立验证）。

## 修复摘要

1. Composite：移除公开 API/OpenAPI、前端和 Markdown 的综合估值及权重输出；四个模型仍独立返回 Low/Base/High，模型不可用不触发重分配。
2. Forward FCFE：`net_borrowing_ttm` 保持历史展示字段；Forward FCFE 仅接受用户覆盖或显式 provider forward borrowing，否则规范化为 0 并给出来源/警告；历史 TTM proxy 降级，不能伪装成高质量 forward。
3. DCF 时间轴：生产路径按 fiscal-year 端点建立期间；估值日在财年中间时 FY1 为剩余期间 stub/prorating，ACT/365 真实日期差用于折现和 TV；API/UI/Markdown 展示 start/end、t、factor、PV。DCF 不可用时 bridge 不泄露 FCFF forecasts。

## 主控复核命令

- `D:\workshop\stock-valuation\.venv\Scripts\python.exe -m pytest -q`：**386 passed, 2 warnings**，exit 0。
- `run_live_validation.py`（当前代码、live provider、四 ticker，输出 `live-validation-final.json`）：AMD、META、GOOG、NVDA 均 status=ok，overall_status=ok。
- `git diff --check`：exit 0（仅 CRLF 转换提示）。

## 四 ticker 结果（当前 live 复核）

| Ticker | Forward borrowing | Historical TTM borrowing | FCFE bridge | FCF Yield | DCF | Composite |
|---|---:|---:|---:|---|---|---|
| AMD | 0 | 0 | 8,307,719,165 | available | available | absent |
| META | 0 | 51,712,000,000 | -10,112,926,613 | unavailable | unavailable | absent |
| GOOG | 0 | 70,129,000,000 | 9,430,802,813 | available | available | absent |
| NVDA | 0 | unavailable | 231,561,566,276 | available | available | absent |

META 的 DCF 不可用且 `financial_bridge.dcf_forecasts=[]`；四 ticker 的 Forward
borrowing 均为 0，未将 TTM 借款带入 forward bridge。GOOG 的正 FCFE 来自其它
明确 forward/operating inputs，不是 TTM borrowing。

## Worker 证据

- Worker A：`.scratch/fatal-three/worker-a-report.md`
- Worker B：`.scratch/fatal-three/worker-b-report.md`、`worker-b-integration-report.md`
- Worker C：`.scratch/fatal-three/worker-c-report.md`、`worker-c-replay.json`
- 最终 bridge 隔离：`.scratch/fatal-three/final-bridge-isolation-report.md`
- 当前 live 原始输入/响应：`.scratch/fatal-three/live-validation-final.json`

未处理其它工单（05–08）；未调整 WACC、terminal growth 或模型参数以贴近旧结果。

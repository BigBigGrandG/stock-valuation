# 美股估值台（Next.js 前端）

这是 stock-valuation MVP 的中文桌面优先前端。它只负责查询 FastAPI、展示后端计算出的四套估值模型和 provenance，不在浏览器内进行估值数学计算。

## 启动

要求 Node.js 18+，并先启动仓库根目录的 FastAPI 服务（默认 `http://127.0.0.1:8002`）。

```powershell
cd frontend
Copy-Item .env.example .env.local
npm ci
npm run dev
```

打开 <http://localhost:3000>，搜索任意美股标的（如 `NVDA`, `AAPL`, `MSFT`, `KO`, `AVGO`, `TSM`）进入 `/valuation/[ticker]`。生产构建和本地运行：

```powershell
npm run typecheck
npm run lint
npm run build
npm run start
```

`NEXT_PUBLIC_BACKEND_URL` 是浏览器请求使用的 FastAPI 地址；如果 API 运行在其他主机或端口，请在 `.env.local` 中修改。后端需要允许 `http://localhost:3000` 或对应前端来源的 CORS。

## 页面能力

- 中文股票搜索与 `/valuation/[ticker]` 路由；默认接入真实美股实时数据源（yfinance），离线演示提供方支持显式选择 `AVGO`（`?provider=demo`）。
- 明确的 LIVE/DEMO 状态标签、数据质量提示、非实时与市场延迟声明，以及财报基准日和报价日期。
- 市盈率、EV/EBITDA、FCF 收益率、DCF 四张独立模型卡；每张卡展示情景值、公式、计算步骤、输入/假设来源、期间、日期和估算标记。针对银行（JPM）、保险（BRK.B）、亏损（RIVN）、外币 ADR（TSM）等特殊标的，未启用模型提供结构化原因隔离提示（如财务报表记账币种与交易币种不一致），而不盲目拒绝全站或编造汇率折算。
- DCF 的悲观/基准/乐观情景可展开查看五年 FCFF、逐年 PV、TV、PVTV、EV、股权价值、债务、现金、股数及每股价值。
- 覆盖控件发送嵌套 POST：`forward_pe.base`、`ev_ebitda.base`、`fcf_yield.base`、`dcf.wacc`、`dcf.terminal_growth` 和可选 `dcf.fcf_growth`。重置按钮调用默认单次 `GET /api/v1/valuation/{ticker}`（不带 `/reset` 后缀），清空所有 6 项输入控件并恢复系统默认估值。
- 完备的异常处理：支持 ETF 非普通股 422 友好提示、未知标的 404 及快捷恢复、429 频控面板、503 服务不可用面板，以及标的切换竞态防抖与旧请求报错隔离。
- 完整 Markdown 报告导出：在估值页面英雄卡右侧显式提供“⭳ 导出 Markdown”操作。将当前已完成的估值结果 100% 导出为独立可读的 UTF-8 Markdown 文件（命名形如 `{ticker}_valuation_{timestamp}.md`）。导出直接基于当前内存状态运算，**零额外发起后端网络请求**；完整覆盖元数据、数据质量、综合结论（MOS/上行空间/分类）、参数覆盖对比、四套模型明细与不可用隔离原因、DCF 三情景五年预测及折现桥梁、逐步推导过程与免责声明，且具备管道符/换行安全转义。

## API 约定

API 的 Decimal 值通常以 JSON 字符串返回。前端仅对返回值做格式化；稳定的 `input_metrics`、`assumption_metrics`、`projection_metrics` 优先展示，旧版响应的 `inputs`、`assumptions` 和 FCFF/PV 数组作为兼容回退。

示例覆盖请求：

```json
{
  "forward_pe": {"base": 18},
  "fcf_yield": {"base": 0.05},
  "dcf": {"wacc": 0.095, "terminal_growth": 0.035}
}
```

## 自动化测试与验证

```powershell
# 静态检查与生产构建 (在 frontend 目录下)
npm run typecheck
npm run lint
npm run build

# Markdown 导出格式器与转义单元测试 (在仓库根目录下)
node .scratch/markdown-export/test_export_formatter.js

# Markdown 导出浏览器端到端与零网络请求验证测试 (在仓库根目录下)
python .scratch/markdown-export/browser_test_export.py

# 底层 API 流式超时与取消契约测试 (在仓库根目录下)
node --experimental-strip-types .scratch/live-tickers/test_api_deep.mjs

# 浏览器端到端自动化验收测试 (在仓库根目录下，需先启动后端 8002 与前端 3000)
python .scratch/live-tickers/browser_acceptance.py
```


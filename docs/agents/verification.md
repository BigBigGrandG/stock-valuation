# Verification Guide

本指南定义如何按修改范围选择验证方式。目标是获得与改动直接相关、可复现的证据，而不是机械运行整套测试。

## Environment Baseline

- Backend: Python 3.12+，虚拟环境 `.venv`。
- Backend dependencies: `pyproject.toml` 与 `backend/requirements.lock`。
- Frontend: Next.js / React / TypeScript，位于 `frontend/`。
- Frontend dependencies: `frontend/package.json`。

## Standard Commands

### Backend offline tests

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/ -v
```

这些测试应在隔离的 demo/test provider 环境中运行，不应依赖生产数据。

### Live ticker verification

```powershell
.\.venv\Scripts\python.exe .scratch/live-tickers/verify_live.py
.\.venv\Scripts\python.exe .scratch/live-tickers/verify_special_tickers.py
```

仅在任务涉及真实 provider、ticker coverage、特殊公司类型或实时数据行为时运行。

### Frontend checks

```powershell
cd frontend
npm run typecheck
npm run lint
npm run build
cd ..
```

根据改动范围选择相关检查；纯后端改动不需要机械运行前端构建。

### Full-stack / E2E

```powershell
node --experimental-strip-types .scratch/live-tickers/test_api_deep.mjs
python .scratch/live-tickers/browser_acceptance.py
```

仅在任务影响前后端协议、流式行为、用户可见页面或端到端交互时运行。

## Scope Rules

- 纯 Markdown、规范或 Agent 指引变更：只做链接、结构、格式、终止换行等静态核验，不运行产品全套测试。
- 局部 backend 代码：优先运行相关单元/回归测试，再根据影响面决定是否扩大范围。
- frontend 代码：运行与改动相关的 typecheck、lint、build；用户交互变化再增加 E2E。
- provider / financial pipeline：增加真实 ticker 或特殊 ticker 验证，但不要把网络失败误判为业务逻辑正确性证据。
- API contract / full-stack behavior：增加 API integration 与浏览器验收。

## Evidence Rules

任何“PASS”“已修复”“已交付”都应有当前轮次实际执行的验证支撑。

任务报告至少说明：

- 实际运行的命令；
- 工作目录；
- PASS / FAIL / NOT RUN；
- 与失败相关的关键错误；
- 未执行验证的原因；
- 剩余风险或环境限制。

历史 `HANDOFF.md`、旧报告、旧日志或此前通过的测试只能作为历史证据，不能冒充当前轮验证。

涉及财务逻辑时，验证还应覆盖必要的数据链：

`source → normalizer/service → projection → valuation engine → API/export`

关键结果应能对应到适用的 period、as_of、currency、unit、source/source_type、confidence、is_estimated 和 unavailable_reason。

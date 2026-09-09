# Project Handoff

状态核对时间：2026-09-09 18:54–18:57，Asia/Shanghai（UTC+8）。工作区：`D:\workshop\stock-valuation`；Windows / PowerShell。

**禁止误删：当前 `master` 没有任何 commit，Git 索引为空，全部项目文件均为 untracked。`git diff` 为空不代表没有工作成果。不要运行 `git clean`、破坏性 reset、覆盖式脚手架或重新初始化项目。**

## 1. Objective

- 用户最终目标：输入任意美股 ticker，获取该公司真实行情、财务数据和适用的估值分析。NVDA 不应再返回“demo provider only supports AVGO”。不是增加几个白名单 ticker，也不是把 AVGO 数据改名复制。
- 当前阶段：已接通真实多 ticker 数据，正在完成财务输入正确性和前端交互的最终验收。Worker 最新两项任务均报告完成，但主控尚未验收；交接核查发现 ADR 拒绝问题，不能宣布需求完成。
- 当前规范：`.scratch/live-tickers/spec.md`；具体验收方法：`.scratch/live-tickers/coordinator-verification-plan.md`。旧 `.scratch/valuation-mvp/spec.md` 仅供查询仍有效的公式/UI 约束，其 AVGO-only 范围已被用户纠正。
- 缺失数据、亏损公司、不适用模型必须有明确原因；不保证每只股票四个模型都产生数字，不编造目标价。
- 不 commit / push。Worker 优先 Antigravity `gemini-3.8-flash-high`、Full Access。用户已授权任务范围内自主执行，不重复索要确认；仍遵守平台强制权限限制。

## 2. Current State

项目包含 FastAPI/Python 后端和 Next.js/React/TypeScript 中文前端，四种 Decimal 估值模型、综合估值、来源元数据、参数覆盖、重置、错误与取消处理已经实现。默认 provider 为 live yfinance，demo 需显式选择。

用户说明本轮因主控 hit usage limit 中断；额度恢复后交由下一任主控接手。额度事件本身未由工具验证，属于用户提供的背景。随后用户明确要求只生成此交接文件，完成后停止开发。

在交接核对时，后台 workers 已提交最新完成报告（前端 15:36，后端 15:41，本地时间）。主控只读取了报告、日志及必要局部代码，**没有重新运行最新完整测试，也没有完成最终代码/财务验收**。18:54 实测 `/health` 返回 `status=ok`，前端首页 HTTP 200；仅证明服务存活。

## 3. Completed

以下区分主控观察与 worker 证据，不把任务完成等同最终验收。

- 真实多股票基本链路：主控曾实际运行 `.venv/Scripts/python.exe .scratch/live-tickers/verify_live.py`，NVDA/AAPL/MSFT/AVGO/KO 均 PASS，返回不同公司/报价、非 demo 数据，模型 Decimal 复算和综合权重断言通过。该次执行早于最后两轮修正，不能代表最新版本全部通过。
- 后端最新 worker 提交了 `223 passed, 2 warnings in 1.22s` 的完整 pytest 日志；主控已读取日志头尾，确认收集 223 项及最终结果。证据：`.scratch/live-tickers/pytest_output.txt`、`backend-round2-report.md`。
- 后端新增真实 provider、缺失财务字段的模型隔离、来源类型、同列财报读取、异常映射等实现。局部代码核对确认这些实现存在；其全量正确性仍待验收。关键文件见第 7 节。
- 前端最新 worker 报告 typecheck/lint/build 退出码 0、6 项 API 深度测试及 11 组浏览器检查通过，保存了输出、响应和截图。证据：`.scratch/live-tickers/frontend-verification-final.md`、`test_api_deep.mjs`、`browser_acceptance.py`、`screenshots/`。主控已读报告，未重新执行最新脚本或逐张核对截图。
- 最终两项 worker 的 `worker_done` 已在 Orca 核实，消息已确认；已调用 `worker-release`。结果是 `retained / no_owned_resource / processAction=none`，可复用终端没有被关闭。
- 本次交接只进行状态读取、已完成任务的资源登记及创建此文件；未继续产品开发。

## 4. In Progress

### A. 后端最终主控验收（实现 task 已 completed，验收未完成）

- **Goal**：真实美股查询、来源可靠的估值输入、缺失/不适用模型隔离、真实接口证据。
- **Current state**：最新 worker 声称完成 Round 2；主控尚未接受“无剩余问题”。
- **Changed files**：最新报告列 `backend/app/providers/yfinance_provider.py`、`backend/tests/test_round2_acceptance.py` 和 `.scratch/live-tickers/` 的后端报告/日志；前一轮还改了 `providers/base.py`、`models/domain.py`、`services/valuation_service.py`、四个估值 engine 及相关测试。无 Git 基线可验证逐轮完整 diff。
- **已完成部分**：worker 记录 223 项离线测试、5 只核心股票、6 个特殊代码、NVDA/KO 原始字段对账。
- **尚未完成部分**：审查最新修正是否满足 `backend-round2.md` 和核验计划，特别是 ADR、财务币种、预测财年、超时及数据来源。
- **当前阻塞/错误**：确认 TSM 被 `_support_guard` 按总部国家拒绝，见第 9 节。没有已确认的最新失败 pytest；不是“没有缺陷”。
- **Orca**：task `task_1562fda510f2`，dispatch `ctx_d6e7e927e568`，terminal `term_d1452db2-3a82-4a67-b3ce-be459cd361d4`。task/dispatch completed；终端 connected、Antigravity、保留上下文。完成消息 `msg_e9acf11564ff`。
- **先读**：`.scratch/live-tickers/backend-round2.md` → `backend-round2-report.md` → `reconciliation_report.md`；只按疑点查看 provider、`_support_guard` 和新增测试。

### B. 前端最终主控验收（补验 task 已 completed，验收未完成）

- **Goal**：证明改参/重置请求次数与数值、真实 deadline、JSON 流取消、股票切换竞态、AAPL/MSFT 实际查询。
- **Current state**：worker 补交了明确断言与输出，已修正此前“sleep 后直接打印 PASS”的弱测试；最新证据未经过最终主控逐项检查。
- **Changed files**：`frontend/lib/api.ts`、`.scratch/live-tickers/test_api_deep.mjs`、`browser_acceptance.py`、`frontend-verification-final.md`；此前前端改动见第 7 节。
- **已完成部分**：报告列 6 项 API 深测和 11 组浏览器检查全通过；NVDA/AAPL/MSFT 当前证据 JSON 已落盘。
- **尚未完成部分**：检查断言是否真的覆盖清单；最后一次浏览器运行约 15:36，后端最终重启/验证约 15:38–15:41，最终组合版本联调仍需确认。
- **当前阻塞/错误**：未确认当前前端失败测试；最新声明“不再有任何工作”尚未获主控认可。
- **Orca**：task `task_ca954ac243af`，dispatch `ctx_d25b0ad729bc`，terminal `term_53f5a7d6-2b19-4cf1-ad03-d57cb257e0d5`。task/dispatch completed；终端 connected、Antigravity、上下文保留。完成消息 `msg_aaa1cbc6cd74`。
- **先读**：`.scratch/live-tickers/frontend-evidence-gap.md` → `frontend-verification-final.md`，再局部检查两份测试脚本和 `frontend/lib/api.ts`。

### C. 项目收尾

- `.scratch/live-tickers/issues/01-real-ticker-valuation.md` 仍是 `Status: ready-for-agent`，没有最终真实多 ticker 验收文件。
- README 的测试数量仍写 199；需要在最终验收后同步实际支持范围、限制和验证证据。
- 当前没有需继续运行的已知最新实现 dispatch；下一步是验收、针对确认问题创建新的有界 follow-up，而非重开整套开发。

## 5. Pending

1. **P0：修正/验收 ADR 与上市地判断**。TSM 的现存 422 是 `non_us / country=Taiwan`，不能当作正确的币种保护通过项。为“美国上市但非美国总部”加入正确回归；缺币种/ADR 单位信息时隔离相关模型，不能伪造转换。
2. **P0：审核预测期间与来源**。目前 provider 用最新年报年份加 1/2 标注 0y/+1y；核实是否真正与 vendor 预测财年对应。`info.forwardEps` 被命名 NTM 的依据仍未核实。
3. **P1：消费最新两份报告，逐项验收/回派缺口**，尤其网络等待是否有整体上限、资料日期/币种/每股单位一致性。
4. **P1：最终组合版本验证**，由 worker 执行主控认可的检查；确认无需重复的证据则直接采纳，不重跑全仓探索。
5. **P2：更新 README/问题状态、生成最终验收记录**。只有满足第 10 节标准才能关闭真实 ticker 需求；用户未授权提交，继续不 commit/push。

## 6. Key Decisions

| 决定 | 原因 / 排除方案 / 不应改变的约束 |
|---|---|
| 默认 live，yfinance 固定 1.7.0，七方法 provider 接口 | 已实证无需 API key 可获得真实数据；保留更换供应商的接缝。不接受有限 ticker 白名单、AVGO 克隆或失败时静默 fixture 回退。公开源覆盖/限流不保证，不能声称实时保证。 |
| 显式 demo：`DATA_PROVIDER=demo` 或 `?provider=demo` | 离线测试可重复；不能把测试模式当实际交付范围。`backend/tests/conftest.py` 用 setdefault 设置 demo。 |
| Python Decimal 负责估值，前端只展示/发请求 | 保持计算和精度单一来源。JSON Decimal 为字符串；不要将业务计算复制到 UI。 |
| 四模型 + 有效模型重新分配综合权重 | PE、EV/EBITDA、FCFE yield、FCFF DCF。缺输入或模型不适用时明确 unavailable，不强制产生四个数字。 |
| FCFE 与 FCFF 分离；禁止缺失字段补零 | FCFE=CFO−capex+net borrowing；FCFF=CFO+interest×(1−tax)−capex。若使用有依据的近似，必须标注，不能把近似标成实际/分析师一致预测。 |
| 倍数/增长/WACC 来源可追溯 | 当前 trailing PE/EV multiple 不等于历史 forward multiple；真实历史缺失时使用明确配置假设。衍生预测须标 derived、公式/原始增长/截断值/期间。 |
| 独立缓存类别和异步 API 包装同步计算 | 现有 TTL：quote 120s、statements 86400s、estimates 43200s、multiples 86400s；provider bundle 30s、并发上限默认 5；API `asyncio.to_thread`。完整线程安全、请求去重/网络总时限仍需核验，勿仅凭说明宣称保障。 |
| 同工作区按文件所有权协作 | 后端/前端 worker 各自负责对应目录；主控负责设计、核验策略、例外处理和验收。避免无必要 worktree 和并发覆盖。 |

保留的财务不变量：PE=EPS×multiple；EV 股权=(EBITDA×multiple−net debt)/shares；yield=FCFE/yield/shares；DCF 五年 FCFF 与终值折现，股权=EV−debt+cash。MOS=(fair value−price)/fair value，与 upside=(fair value−price)/price 不同。仅完整、正的 low/base/high 模型进入 composite，权重和为 1；WACC>永续增长率，后者上限 5%；严格拒绝非法 sparse override/非有限数。

## 7. Repository Changes

实测 `git status --short`：`.gitignore`、`.scratch/`、`AGENTS.md`、`README.md`、`backend/`、`docs/`、`frontend/`、`pyproject.toml`、`requirements.txt`、`uv.lock` 全为 `??`；本文件创建后另有 `?? HANDOFF.md`。

- **Tracked modified / deleted / staged：无**（`git ls-files` 无输出）。
- **Added：全部 untracked 项目文件**。以下是目的清单，按同目的文件合并；并非可从 Git 恢复的已提交版本。
- **`git diff --stat`：无输出，0 个 tracked diff**。无法给出相对 commit 的实际新增行数/逐轮删除记录；`git log -5 --oneline` 报 `fatal: your current branch 'master' does not have any commits yet`。已删除的未跟踪文件历史：Unknown。

| 文件/分组 | 用途与本阶段变化 |
|---|---|
| `backend/app/providers/yfinance_provider.py` | 真实行情/公司/财报/预期/倍数映射、日期/来源、缺失处理和并发/错误分类；主要剩余审核点。 |
| `backend/app/providers/base.py`, `avgo_fixture.py`, `__init__.py` | 七方法 provider 契约、原始数据类型、异常；显式 AVGO demo。 |
| `backend/app/models/domain.py`, `overrides.py`, `__init__.py` | Metric/快照/模型输出、可选现金债务、币种和来源、Decimal、严格覆盖参数。 |
| `backend/app/services/valuation_service.py`, `__init__.py` | Normalizer、`_support_guard`、FinancialDataService、TTL cache、ValuationService；ADR 非美国总部拒绝实际仍在此处。 |
| `backend/app/engines/forward_pe.py`, `ev_ebitda.py`, `fcf_yield.py`, `dcf.py`, `composite.py`, `__init__.py` | 确定性计算、公式/步骤/来源、金融/REIT 不适用规则、缺失输入隔离、综合权重。 |
| `backend/app/main.py`, `config.py`, `app/__init__.py`, `api/__init__.py` | HTTP API、错误响应、CORS、live/demo 选择和默认参数；同步工作移到线程。 |
| `backend/tests/test_live_and_mock_provider.py`, `test_acceptance_rejection_fixes.py`, `test_round2_acceptance.py` | live provider mock 与两轮验收缺陷回归。 |
| `backend/tests/test_forward_pe.py`, `test_ev_ebitda.py`, `test_fcf_yield.py`, `test_dcf.py`, `test_composite_classification.py` | 公式、精度、情景和分类测试。 |
| `backend/tests/test_api_integration.py`, `test_backend_acceptance_revisions.py`, `test_service_independent_acceptance.py`, `conftest.py`, `__init__.py` | API/服务/独立不变量回归、离线 demo 测试配置。 |
| `frontend/lib/api.ts` | 统一 HTTP/结构化错误、deadline 覆盖 body、取消、reset 单次 GET；最新将 fetch/reset 参数扩展为 signal 或 options。 |
| `frontend/lib/types.ts`, `format.ts` | 后端结构对应 TS 类型及中文格式。 |
| `frontend/app/page.tsx`, `app/valuation/[ticker]/page.tsx`, `app/globals.css` | 任意 ticker 搜索、真实/延迟标识、模型/假设/综合估值、错误与请求竞态保护。 |
| `frontend/components/DCFScenarios.tsx` | DCF 情景、五年预测/折现、来源展示。 |
| `frontend/app/layout.tsx`, `favicon.ico`, `public/*.svg` | 布局/元信息及现存静态资源；资源是否均使用：Not verified。 |
| `frontend/package.json`, `package-lock.json`, `tsconfig.json`, `next.config.ts`, `postcss.config.mjs`, `eslint.config.mjs`, `.gitignore` | Next 构建/类型/lint/依赖；eslint 忽略 `.next` 和 node_modules。 |
| `pyproject.toml`, `requirements.txt`, `uv.lock`, `backend/requirements.txt`, `backend/requirements.lock` | Python 项目、依赖与锁定；新增 yfinance。多个 lock/requirements 是否完全同步：Not verified。 |
| `.gitignore`, `backend/.env.example`, `frontend/.env.example`, 两级 `README.md` | 环境/启动/忽略配置。前端 env 示例为 `NEXT_PUBLIC_BACKEND_URL=http://127.0.0.1:8002`。 |
| `AGENTS.md`, `docs/agents/{issue-tracker,triage-labels,domain}.md` | 本地 issue/spec 规则；领域文档约定，未创建领域内容不能凭空推断。 |
| `.scratch/live-tickers/**` | 当前任务规范、复现/测试脚本、原始响应、截图和报告，务必保存。 |
| `.scratch/valuation-mvp/**` | 旧阶段公式/回归和 demo 验收证据；不用全文重读，不作为任意 ticker 完成证明。 |
| `HANDOFF.md` | 本次恢复开发状态文件。 |

**公共接口/依赖注意**：现金/总债务/净债务可为空；各 model 有 available/unavailable_reason；新增财务币种/来源信息；默认从 demo 切换 live；frontend fetch/reset options 签名已扩展。审查消费者兼容性。没有已知待执行 migration、部署、破坏性操作；未做全面迁移审计。不要为交接另行升级依赖。

## 8. Verification

本次交接不重新跑开发测试；下面标明原执行证据。除健康检查和旧版 live oracle 外，最新结果主要来自 worker 保存日志/报告。

| 状态 | 命令（相对根目录，注明 cwd） | 真实结果与证据 |
|---|---|---|
| PASS，worker 日志已读 | `.venv/Scripts/python.exe -m pytest -v` | 223 passed，2 warnings，1.22s；`.scratch/live-tickers/pytest_output.txt`。日志 rootdir 为项目根，Python 3.12.13；报告退出码 0。 |
| PASS，worker 报告 | `.venv/Scripts/python.exe .scratch/live-tickers/verify_live.py` | NVDA/AAPL/MSFT/AVGO/KO；退出码 0。最新 JSON 位于 `coordinator-live/`，15:38 写入。主控更早亲自运行同脚本通过；最新未重跑。 |
| PASS（仅脚本断言），验收有缺陷 | `.venv/Scripts/python.exe .scratch/live-tickers/verify_special_tickers.py` | 报告退出码 0，JPM/BRK.B/RIVN/TSM/SPY/INVALIDZZZZ；TSM 的错误通过判定不足，见第 9 节。 |
| PASS，worker 报告 | `.venv/Scripts/python.exe .scratch/live-tickers/generate_reconciliation.py` | 退出码 0，生成 NVDA/KO `reconciliation_report.md`；读报告确认有 raw 行/日期/标准化值，未审计脚本所有断言。 |
| PASS，worker 报告 | cwd `frontend`：`npm run typecheck` | 退出码 0；`frontend-verification-final.md` 第 5 项证据。 |
| PASS，worker 报告 | cwd `frontend`：`npm run lint` | 退出码 0，报告 0 errors/warnings。 |
| PASS，worker 报告 | cwd `frontend`：`npm run build` | 退出码 0，Next 生产路由输出已保存至报告。 |
| PASS，worker 输出已读 | `node --experimental-strip-types .scratch/live-tickers/test_api_deep.mjs` | 6 passed / 0 failed，退出码 0；本地 HTTP 流测试，缩短 deadline 注入测试选项，并非实际等待 45s。 |
| PASS，worker 输出已读 | `python .scratch/live-tickers/browser_acceptance.py` | 11 组检查、退出码 0；报告保存 stdout，`screenshots/` 和 `NVDA/AAPL/MSFT-verification-response.json`；该命令使用的 Python 绝对路径 Unknown。 |
| PASS，交接时实测 | `Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8002/health -TimeoutSec 5` | 18:54 `status=ok`，version 0.2.0，demo_tickers=[AVGO]。demo_tickers 字段本身不代表运行在 demo 模式。 |
| PASS，交接时实测 | `Invoke-WebRequest -UseBasicParsing http://127.0.0.1:3000 -TimeoutSec 5` | HTTP 200；未进行新的股票查询或 UI 测试。 |
| NOT RUN | 最后后端修改后的主控最终端到端/财务全量验收 | 不能引用早期/worker 通过作为已验收结论。 |

最新 pytest 无已确认 FAIL；两条依赖弃用警告分别是 Starlette TestClient 的 httpx 用法、AnyIO BlockingPortal alias，不是测试失败。开发阶段曾发现/退回真实缺陷（缺字段补零、跨年取数、假历史倍数、来源误标、reset 盲重试、弱测试），前两轮报告声称全部解决的结论曾被主控推翻。

## 9. Risks / Unknowns

1. **确认未解决：美国上市 ADR 被总部国家拒绝。** `coordinator-live/TSM.json` 保存 422：`error=unsupported_company_type, reason=non_us, detail=country=Taiwan`。`backend/app/services/valuation_service.py::_support_guard` 在 allow_all_equities 分支之前无条件检查 country，并在其后对 currency mismatch 整体抛错。报告把 TSM 描述成“非 USD 保护通过”，与实际 reason 不符。该快照不是美国上市地判断，也没有实现仅禁用受币种影响模型。
2. **预测财年未证实**：provider 约 648–661/824–829 行直接 `as_of.year + 1/+2`；尚未见确认 forecast fiscal end 的字段匹配。仅写出 FY 标签不能证明年报基期与 0y 预测相邻。需用滞后年报和非自然财年用例验证。
3. **forwardEps horizon 未证实**：provider 约 793–800 行把 summary fallback 标 NTM；本次只确认代码这样写，没有 primary-source 证明该字段是 NTM，不能据报告认定正确。
4. **网络总时限 Unknown**：bounded semaphore 和 history(timeout=10) 已看到；info/statement/estimate 仍调用 yfinance properties。依赖默认 timeout、整体请求上限、同 ticker 并发去重、bundle TTL 与类别缓存协作未完成审核。
5. **证据版本差异**：前端最终浏览器结果早于后端 Round 2 最后部署。`coordinator-live/` 核心 JSON 已被 worker 的最终运行覆盖；旧主控 oracle 输出不可冒充同一版本。最新 raw snapshots（文件名 `*-snapshot.json`）大多是凌晨 02:31 的旧版本；优先读 15:38 的 `coordinator-live/*.json`。
6. **质量/适用范围**：RIVN 无可用模型是可能且应解释的结果；ADR/股份类别的总股数与每 ADS 单位不能只靠文字说明证明。年度财报 vs TTM、当前 sharesOutstanding 近似不是 weighted-average diluted shares。原始数据/模型假设的可靠性仍是验收重点。
7. **测试证明强度**：最新脚本内容需抽查；不可凭报告中的“100% / no work remains”关 issue。TSM 就是“脚本 PASS 但业务不合格”的现有实例。
8. **环境**：Git 全局 ignore 读取偶有 Permission denied；Orca 沙箱调用常报 `CreateFile access denied` / `runtime_unavailable`，提升权限重试后可用，不能据此认定 Orca 停止。实际当前服务 PID、网络公网持续可用、依赖锁一致性、最终完整 UI 视觉质量：Not verified。

## 10. Resume Here

1. **第一个动作：恢复状态，勿重探仓库或启动新实现。** 读本文件第 4/8/9 节，然后执行 `orca status --json`、`orca orchestration run-current --json`。必要时按当前 CLI 帮助绑定现有 Run `run_67f9f97dae61`，不要重置任务库。读取两个指定 task 的 dispatch 和最新 inbox，判断自本快照后是否有新工作。
2. 读取 `backend-round2-report.md`、`frontend-verification-final.md`，对照各自任务清单，仅检查第 9 节所列局部代码/证据。两个 task 已 completed，不应再次发旧 dispatch 的生命周期消息。
3. **优先复用后端 terminal** `term_d1452db2-3a82-4a67-b3ce-be459cd361d4`，创建新的有界 follow-up：先复现 TSM/非美国总部但美国上市情形，修正上市地与币种处理，并检查 fiscal forecast 对齐。让 worker 写失败复现、修正和回归日志；不让主控重做已完成的全仓探索。
4. 优先复用前端验收 terminal `term_53f5a7d6-2b19-4cf1-ad03-d57cb257e0d5`：只有发现证据缺口或后端行为变化才安排补验。实际浏览器验收应覆盖至少 NVDA → AAPL → MSFT、BRK.B、错误恢复，按新数据决定模型是否可用，不要求四个全有数值。
5. 复用前先读脱敏 terminal tail、确认真正 idle，再 `task-create` → `dispatch --inject`；等待收到新 task 的有效 heartbeat/实际读取任务文档后才认为启动成功。旧终端曾“injected=true 但继续打印旧任务完成”，也曾 `agent_prompt_stalled` 后迟到执行；见第 12 节，不能重复派两个编辑同一目录的 worker。
6. Worker 修正后按第 8 节命令执行相关回归；需要全量时从根运行 `.venv/Scripts/python.exe -m pytest -v`。前端 `npm run typecheck`、`npm run lint`、`npm run build`（cwd frontend）；API 深度测试、live oracle、special tickers、browser acceptance。测试设置 demo，实际 API 必须 live；不要让外部 `DATA_PROVIDER=live` 污染普通 pytest。
7. 若服务不在运行，仅让 worker 在确定无旧进程后恢复：后端 cwd `backend`，`..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8002`；前端 cwd `frontend`，`npm start`。前端 build-time `NEXT_PUBLIC_BACKEND_URL=http://127.0.0.1:8002`。不盲杀全部 Node/Python/终端。
8. **Acceptance Criteria**：五只核心股票真实、不同公司/来源且有适用模型；财务数据同期间/币种/股数基础；衍生预测来源和财年可靠；ADR 不因总部国家被错误拒绝；缺失数据只影响必要模型且理由准确；SPY/无效代码/未知代码/429/503 行为正确；四模型财务不变量和覆盖隔离保持；改参/重置/超时/取消/切换的可执行断言通过；最终运行版本与证据一致。全部满足才更新 issue 为 resolved、写最终验收记录并进入交付阶段。

常用精确查询：

```powershell
orca orchestration dispatch-show --task task_1562fda510f2 --json
orca orchestration dispatch-show --task task_ca954ac243af --json
orca orchestration check --json
orca orchestration task-list --json
git -c safe.directory=D:/workshop/stock-valuation status --short
```

不要把前述 `task-list` 的历史 blocked/failed 任务当成当前开发阻塞：`task_091dc40100ec`、`task_f91cfef3c677` 是旧 MVP 遗留 blocked，`task_08c956238f6f` 是旧验收失败任务，后续已有替代任务。

## 11. Coordinator Guidance

- **Coordinator**：planning + architecture + delegation + exception handling + verification + synthesis。明确核验方法/预期/证据格式，由 worker 执行；主控检查结果、局部代码和财务推理，不把 worker 自报通过当验收。
- **Antigravity worker**：repo exploration + implementation + testing + debugging + execution。优先 `gemini-3.8-flash-high`，Full Access。当前两个可复用会话由 `agy --model gemini-3.8-flash-high --dangerously-skip-permissions` 启动。
- 必须用 Orca 任务/dispatch 协作，不用其他 subagent 系统替代现有 provenance。先消费已有报告/测试/changed files，再拆有界任务；无需重读整个聊天或旧 issue 树。
- 环境 `C:/Users/Wayne/.agents/skills/computer-use/SKILL.md`，Orca 内置 `orca skills get orchestration` / `orca skills get orca-cli` 可恢复操作指南。按必要范围读取；不要每次全文重新探索。
- 只有新任务才新建 dispatch；旧完成 IDs 不可重用为 worker_done。完成后 release 或立即复用；`no_owned_resource` 表示保留会话，不等于进程关闭，也不要求关闭用户终端。
- 终端输出可能含 `dcap_` capability，**不得写进 HANDOFF、报告或用户输出**；读 tail 时过滤该行。Orca 失败可能已执行，按工具给出的 `request-show` / `--retry-request` 恢复，勿盲目重复 mutation。
- 用户不希望反复确认，但主控 Full Access 不能凭用户偏好自行解除平台沙箱；遇真实权限错误按工具机制提权。后台服务新进程使用隐藏窗口；不发外部消息、不 commit/push。

## 12. Critical Context

- **最终目标从来不是 AVGO demo。** 原来 demo 验收已通过仍被用户否定；现在不得退回 demo 范围。旧历史消息中“MSFT 404 正确”只属于旧范围。
- **当前真正工作：验收最新 workers + 修正 TSM/财年等确认或待证问题，不是从零实现。** 当前 issue 仍开放。
- Run：`run_67f9f97dae61`；Orca runtime 在核对时为 `a5496e16-235b-4665-a336-430ef4968c56`；workspace ID：`389b22e8-d758-4be2-8add-5b72f65c0a55::D:/workshop/stock-valuation`。旧主控 terminal：`term_f0e07e30-f040-409f-b9f1-62582f658b45`；下一任以自己的真实身份绑定，勿伪造 sender。
- Backend 最新有效完成 dispatch `ctx_d6e7e927e568`；Frontend 最新有效完成 dispatch `ctx_d25b0ad729bc`。本次 release 均 retained/no_owned_resource；会话可复用，启动后的存活情况需再查。
- 失效/被放弃 dispatch：`ctx_8309c644be3d`、`ctx_43b77e016c47`（prompt stalled）；`ctx_524ffe406826`（新任务 capability 缺失/无效）；`ctx_d7d70352e271`（新 prompt 未实际执行）。不要从它们恢复生命周期权限。曾向旧终端下发 STOP/idle 以防交叉编辑；不要重新启动旧实现任务。
- 最新 completion delivery `delivery_ec16aa8353c8` 已 ACK。之前 worker-list 的 `unsupervised` 标签不等于未执行；以具体 task/dispatch completed、worker_done 和落盘证据共同判断。
- 服务：API `http://127.0.0.1:8002`，UI `http://127.0.0.1:3000`；原主控保留 Orca page `7f76fcf2-cec5-46ea-884d-75d20a66efa2`（当前是否仍可用 Unknown）。
- Python `.venv`：3.12.13（pytest 日志确认）；Node 曾为 24.18.0（本轮交接未重查）。Python deps 以 pyproject 为准；Next 15.4.3，React ^19，eslint-config-next 15.3.4；是否要统一版本属于后续有证据的维护，不要无故升级。
- `coordinator-live/TSM.json` 是实际国家误拒绝证据。**不要把“TSM 返回任何 422”当正确验收。**
- 没有 commit 可回退，没有最终多 ticker 验收完成记录。本文件是交接快照，不是交付成功声明。

## 13. Final Acceptance & Closeout Status (2026-09-10)

核对完成时间：2026-09-10 00:38（Asia/Shanghai，UTC+8）。工作区：`D:\workshop\stock-valuation`。

**权威性说明**：本节（第 13 节）是关于本项目最终验收与交付状态的最新权威记录，其效力覆盖并优先于前述历史交接记录（第 10~12 节）。历史记录中关于 TSM 422 拒绝（保留于 `.scratch/live-tickers/tsm-rejection-before.json` 作为历史对照）已在 Round 3 中被正式修正并经验收闭环，不再构成系统的现存缺陷。

### 状态摘要：全量验收通过，真实多 Ticker 需求已交付关闭

后序轮次（Round 3）修正与最终联合验收已全部完成，第 10 节验收准则（1~9）100% 达成。本阶段不再遗留任何阻塞性财务缺陷或交互断言漏洞。

1. **TSM 与 ADR 判定已完全修复并验证**：
   - 彻底移除了原按总部国家盲目拒绝的逻辑，以真实交易所（`NYQ`/纽交所）上市地证据为准。
   - TSM 返回 HTTP 200，获得真实 USD 报价（最新捕获数据见 `TSM-verification-response.json`），预期每 ADS EPS 为 `$16.93 USD`，Forward P/E 模型正常计算（基准 `$338.60`，权重 1.0000）。
   - 由于财务报表货币为 TWD，报表类模型（EV/EBITDA, FCF yield, DCF）被安全且准确地隔离禁用（明确标明“记账币种与交易币种不一致，不进行未经审计的汇率折算”），杜绝编造汇率折算。
   - 证据：`.scratch/live-tickers/tsm_raw_capture.json`、`TSM-verification-response.json`、截屏 `15_tsm_adr.png`。历史拒绝证据存档于 `tsm-rejection-before.json`。
2. **财年预测与对齐验证**：
   - `_verify_forecast_alignment` 强制匹配 upstream `nextFiscalYearEnd` 时间戳，剔除盲目 `year+1` 投射；严格支持 MSFT（6月30日年结）、NVDA（1月浮动年结），并对年报基准日距下一财年结束日非相邻（<180天或>450天，非距今日历天数）实施严格阻断。
3. **真实资源边界与请求预算**：
   - 采用 `threading.BoundedSemaphore(5)` 并绑定 future 完成回调释放；使用 `ContextVar[_RequestBudget]` 统一全链路超时时间，超时与缓存年龄彻底解耦，503/429 映射准确。
4. **全套自动化与端到端测试（明确区分离线与在线）**：
   - 后端 Pytest 离线测试全量通过：**250 passed, 0 failed in 4.35s**（在离线 demo provider 隔离环境中执行）。
   - 独立在线 API Oracle 验证通过：`verify_live.py`（5 只核心美股）、`verify_special_tickers.py`（6 只特殊/边界标的）在运行中的 live API 上全量通过。
   - 前端静态检查：`typecheck` 0 错误，`lint` 0 错误/警告，`build` 成功。
   - 底层 API 深度测试：`test_api_deep.mjs` 6/6 通过（含毫秒级模拟超时、流式解码主动中止、重置无 `/reset`、429/503 单次请求无重试）。
   - 浏览器端到端全量验收：`browser_acceptance.py` 14/14 检查全量通过，保存 18 张全流程截屏与 6 份核心标的生产响应 JSON。
5. **归档与关闭记录**：
   - 最终验收报告：`.scratch/live-tickers/final-acceptance.md`
   - 前端最终验收报告：`.scratch/live-tickers/frontend-final-acceptance.md`
   - 后端最终验收报告：`.scratch/live-tickers/backend-final-acceptance.md`
   - 需求工单状态：`.scratch/live-tickers/issues/01-real-ticker-valuation.md` 已置为 `Status: resolved`。
   - 说明：验收严格受限于上述记录的自动化与端到端检查。当前工作区文件完整保存但未建 Git commit 基线，严禁运行 `git clean` 或破坏性 reset。

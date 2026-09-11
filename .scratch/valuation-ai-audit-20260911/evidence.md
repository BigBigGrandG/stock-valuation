# AI 估值审计核验证据文档 (Audit Evidence)

**审计基线**：Git master 分支 `11b0495`（MVP版本）  
**审计时间**：2026-09-11（Asia/Shanghai）  
**执行角色**：Orca Dispatched Worker (`term_770d787d-9a20-480a-b8ea-a7db3d870491`)  
**协调员终端**：`term_6023c84b-1b9c-4190-9243-bc262cb85488`  
**关联任务**：`task_33586c7752e1` / `ctx_6e452dc1493f`（修订返工）  
**核验目标**：独立核验 `ai_comment/20260910.md` 中提出的 2 个致命问题与 5 个严重问题，对齐四份原始估值报告、当前后端源码实现及外部一手财报核查事实，严格区分客观事实与主观评定，实施严谨财务建模与证据校准。

---

## 1. 核心数学验算与模型分歧证据 (Mathematical Recalculations)

### 1.1 META 剔除 EV/EBITDA 敏感度与重归一化复算

在 META 估值报告 (`C:/Users/Wayne/Downloads/META_valuation_20260910_233228.md`) 中：
- 报告现价：$651.71
- 四模型单项公允价值：
  - `forward_pe`: $663.40 (有效权重 33.33%)
  - `ev_ebitda`: $1,153.86 (有效权重 26.67%)
  - `fcf_yield`: $729.80 (有效权重 18.18%)
  - `dcf`: $686.70 (有效权重 21.82%)
- 报告综合基准值：**$811.36**，得出预期上涨空间 **+24.50%**，安全边际 **+19.68%**（评定为“低估”）。

**复算验算**：
1. **AI 评论所述的“当前权重简单重归一化”**：
   - 剔除 `ev_ebitda` 后的现存模型有效权重之和为：0.3333 + 0.1818 + 0.2182 = 0.7333。
   - 权重重归一化：
     - $W_{pe} = 0.3333 / 0.7333 \approx 45.452\%$
     - $W_{fcf} = 0.1818 / 0.7333 \approx 24.792\%$
     - $W_{dcf} = 0.2182 / 0.7333 \approx 29.756\%$
   - 综合价值：
     $$P = 663.40 \times 0.45452 + 729.80 \times 0.24792 + 686.70 \times 0.29756 = \mathbf{\$686.80}$$
   - 对应现价 $651.71 的预期上行空间：
     $$	ext{Upside} = (686.80 - 651.71) / 651.71 = \mathbf{+5.38\%}$$
   - **结论**：AI 评论正文提及的“约 $687、+5.4% upside”与算术重归一化结果完全吻合。
2. **若按底层引擎原生规则（维持 40% 现金流上限）重新推导**：
   - 初始选定权重：$w_{pe}=0.25, w_{fcf}=0.25, w_{dcf}=0.30$（有效模型总选定权重 0.80）。
   - 现金流组原始和 $0.55 / 0.80 = 68.75\% > 40\%$，触发上限：现金流组合计 40%，非现金流组（P/E）占 60%。
   - 有效权重：$W_{pe}=0.60, W_{fcf}=(0.25/0.55)\times 0.40 \approx 18.1818\%, W_{dcf}=(0.30/0.55)\times 0.40 \approx 21.8182\%$。
   - 计算结果：
     $$P = 663.40 \times 0.60 + 729.80 \times 0.181818 + 686.70 \times 0.218182 = \mathbf{\$680.56}$$
   - 对应现价 $651.71 的预期上行空间：**+4.43%**。
- **重要边界警示**：无论 $686.80 还是 $680.56，仅属于“剔除单个离群模型后的敏感性测试数学推导”，**绝不可直接作为平台认证的“合理公允价值”或给用户的投资建议**。

---

### 1.2 四份报告最大模型与最小模型估值比值 (Max/Min Ratio)

各报告单模型公允价值（基准情景）提取自四份原始报告第 1.1~3.4 节：

| 标的代码 | Forward P/E | EV/EBITDA | FCF Yield | DCF | 报告价格 | 最大值 (Max) | 最小值 (Min) | Max / Min 比值 | 离散极差 [(Max-Min)/Min] | AI 原文对应描述 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **GOOG** | $332.20 | $407.42 | $213.12 | $208.42 | $327.11 | $407.42 (EV) | $208.42 (DCF) | **1.9548x** | **+95.48%** | 提及接近门槛 (差近一倍) |
| **META** | $663.40 | $1,153.86 | $729.80 | $686.70 | $651.71 | $1,153.86 (EV) | $663.40 (PE) | **1.7393x** | **+73.93%** | 明确识别 EV 异常离群 |
| **AMD** | $264.60 | $141.37 | $141.09 | $209.68 | $507.58 | $264.60 (PE) | $141.09 (FCF) | **1.8754x** | **+87.54%** | PE 与 EV 差近一倍 |
| **NVDA** | $263.80 | $186.51 | $112.10 | $199.05 | $218.17 | $263.80 (PE) | $112.10 (FCF) | **2.3533x** | **+135.33%** | 原文列式 2.35倍 |

**事实核验结论**：
1. 四家公司的最大/最小模型比值均显著超过 1.50x（GOOG 1.95x, META 1.74x, AMD 1.88x, NVDA 2.35x）。
2. 在模型分歧显著的情况下，直接机械加权合成单一公允价值（如 NVDA 四模型离散却恰好合成 $201.48，与现价 $218.17 偏差仅 -7.65% 并打上合理估值标签），未充分提示底层模型间关于增长率、倍数与贴现率的假设分歧。

---

## 2. 全部 7 项高等级问题逐项核验明细 (Fact vs Severity Distinction)

### 【致命问题 1】所谓“Forward EBITDA / FCFE / FCFF”仍然不是真正的前瞻预测

- **裁定状态**：`confirmed`（事实完全确认，缺陷属实）
- **报告位置证据**：
  - AMD 报告：第 148 行（EBITDA $7.275B × 1.40 = $10.185B，clamped to 40.0%）；第 200 行（FCFE $8.226B × 1.40 = $11.516B）；第 249 行（FCFF $6.84B × 1.40 = $9.57B）。
  - NVDA 报告：第 148 行（EBITDA $144.552B × 1.40 = $202.373B）；第 200 行（FCFE $96.676B × 1.40 = $135.346B）；第 249 行（FCFF $96.90B × 1.40 = $135.65B）。
- **源码行号证据**：
  - `backend/app/providers/yfinance_provider.py` L727-736, L969-985：EBITDA/FCFE/FCFF 直接绑定 `re_est.growth` 或 `ee.growth` 并强行截断在 `[-20%, +40%]`。
  - `backend/app/services/projections.py` L165-263：`derive_request_projections()` 对历史财务科目机械乘以同一截断增长率。
  - `backend/app/engines/dcf.py` L111-131, L438-449：DCF Year 3~5 继续单倍率滚动。
- **事实与财务建模核验**：
  - **合规事实澄清**：系统并非未披露来源或恶意编造，代码及报告中均明确标注了 `source_type = derived` 以及推导公式。
  - **核心财务缺陷**：在缺少明细卖方一致预期时，系统将营业额或 EPS 的单一前瞻增速直接作为 EBITDA、FCFE 和 FCFF 的共同增速。在财务学中，即使假设常数 EBITDA Margin，EBITDA 的增长率在数学上也恒等于 Revenue 增长率（即 `EBITDA_t = Rev_t * Margin = Rev_0*(1+g)*Margin = EBITDA_0*(1+g)`）。因此“指标使用相同增长率”本身并不必然非法；真正的建模缺陷在于**缺少对资本开支（CapEx）、净营运资本变动（ΔNWC）、净借款（Net Borrowing）和折旧摊销（D&A）等各科目的独立前瞻假设驱动，导致现金流转化率脱离经营周期**。
- **外部事实限制与隔离**：
  - AMD 2026 Q2 Adjusted EBITDA 单季达 $3.315B、半年 $6.061B，但 Adjusted EBITDA 包含公司自定义非 GAAP 调整项，不能在未做逐项会计对账前直接等同于 vendor 的 GAAP EBITDA；不能把单季或半年实际值简单线性年化来否定全年预期，核验关键在于建模缺乏细分项目驱动。

---

### 【致命问题 2】系统仍然使用旧年报做估值基准，而最新季度已经存在

- **裁定状态**：`confirmed`（事实完全确认，属于系统级数据链路 Bug）
- **报告位置证据**：
  - 四份报告基本信息表（第 13 行）：`财务报表统计口径：年报回退 (ANNUAL_FALLBACK)`；
  - 数据提醒（第 22 行）：`Financial inputs are stale (oldest age 253 days / NVDA 222 days)`；
  - 输入明细表：资产负债表与现金流量表基准日均为 `2025/12/31`（NVDA 为 `2026/01/31`）。
  - **官方最新季度日期修正**：NVIDIA 为 **2026-07-26**，Alphabet/Meta 为 **2026-06-30**，AMD 为 **2026-06-27**；供应商月末标签不等于实际财务截止日。
- **源码行号证据**：
  - `backend/app/providers/yfinance_provider.py` L220-236, L337-360：
    - `_TickerBundle.__init__` 初始化属性仅声明了：`_bs`, `_cf`, `_fin`, `_ee`, `_re`；
    - 但在 `get_quarterly_balance_sheet()`（L339）、`get_quarterly_cashflow()`（L348）和 `get_quarterly_financials()`（L358）中，却调用了：
      `self._fetch_property("_qbs", ...)`、`self._fetch_property("_qcf", ...)`、`self._fetch_property("_qfin", ...)`。
    - `backend/app/providers/yfinance_provider.py` L258：
      `_fetch_property` 执行 `cached = getattr(self, prop_name)`，由于实例未声明 `_qbs`/`_qcf`/`_qfin`，抛出 `AttributeError: '_TickerBundle' object has no attribute '_qcf'`。
    - 外层的 `try...except Exception: return None` 静默捕获了此 AttributeError，导致在当前默认 live 模式下新建 bundle 走季度路径时，**所有季度接口恒定返回 None**！
  - `backend/app/providers/statement_aggregator.py` L128-136, L193-197, L440-444：
    - 季度表入参为 None，`verify_consecutive_quarters()` 校验失败，聚合器被迫触发 `ANNUAL_FALLBACK`。
- **作用边界精确定位**：
  - 此问题专门发生在**默认 live 模式下通过新建 `_TickerBundle` 访问未缓存季度属性的代码路径**。
  - 在离线 demo 模式（`DATA_PROVIDER=demo`）、显式 mock/fixture 注入环境、或仅查询年度报表的路径下不受此 AttributeError 影响；
  - 同时需明确：即使上市公司官方发布了最新 10-Q，也不必然代表公开数据源（如 Yahoo Finance）在任意时刻都能提供连续完整 4 个季度且必需科目（CFO、CapEx、EBITDA）齐全的数据；当上游季度数据客观缺失或断档时，系统触发 `ANNUAL_FALLBACK` 属于合法的韧性保护机制。

---

### 【严重问题 1】公司特异化倍数完全没有实现，全量走 Fallback

- **裁定状态**：`confirmed`（事实完全确认）
- **报告位置证据**：
  - 四份报告第二节“估值假设与情景参数”第 67~70 行：P/E (18/20/22)、EV/EBITDA (18/22/26)、FCF Yield (5.5%/5.0%/4.5%)、WACC (12%/10%/8%) 全量标注 `Configured fallback`。
  - META 报告第 135 行：22x EV/EBITDA 乘以推导前瞻 EBITDA 得出 $1,153.86 公允价值。
- **源码行号证据与真实逻辑澄清**：
  - `backend/app/providers/yfinance_provider.py` L1074-1094 (`get_historical_multiples`)：
    - 深入审查源码发现，该函数在第 1088 行**直接硬编码返回 `None`**：
      ```python
      return {
          "historical_forward_pe": None,
          "historical_ev_ebitda": None,
          "period": "historical",
          "as_of": as_of_date,
          "source": f"Yahoo Finance multiples ({bundle.query_symbol})",
      }
      ```
    - 此前关于“代码尝试提取历史中位数”的描述不准确：源码在 L1085-1087 明确注释说明当前 `trailingPE` 和 `enterpriseToEbitda` 不代表历史前瞻倍数，在缺乏时序数据库时直接返回 `None`。因此系统压根没有在运行时进行动态历史中位数提取。
  - `backend/app/config.py` L14-23, L63-88：全局硬编码唯一定义。
  - `backend/app/services/valuation_service.py` L1056-1070：直接注入静态默认值。
- **财务判断边界**：
  - 22x EV/EBITDA 对于某些高成长科技企业并不必然在财务上完全脱离实际，但将其作为全局无差别的单一 fallback 赋给不同行业标的，确实缺乏行业特异性支持。

---

### 【严重问题 2】DCF 虽然修正了年份，却依然没有实现“growth fade”

- **裁定状态**：`confirmed`（事实完全确认）
- **报告位置证据**：
  - GOOG 报告第 360-362 行：Year 3~5 FCFF 增速固定为 23.64%，终值增长率突变为 3.00%。
  - META 报告第 360-362 行：Year 3~5 FCFF 增速固定为 26.49%，终值突变为 3.00%。
  - NVDA 报告第 360-362 行：Year 3~5 FCFF 增速固定为 30.00%（上限截断），终值突变为 3.00%。
- **源码行号证据**：
  - `backend/app/engines/dcf.py` L438-449：在 5 年预测循环中，Year 3~5 均使用静态单一的 `growth_rate` 递推：`value = previous * (1 + growth_rate)`。
- **建模分析**：
  - 预测期末与永续期之间存在增速断崖。与其他条件相同且逐年降低增速的路径相比，本路径第5年现金流更高，终值对该假设高度敏感；这不证明它相对真实未来必然偏高。两阶段DCF本身可以合法使用，需补充路径依据与敏感度。

---

### 【严重问题 3】系统“发现”Terminal Value 危险，但没有让这个发现影响结果

- **裁定状态**：`partial`（事实部分确认：警示存在且未调权重属实，但权重控制属于候选风控策略）
- **报告位置证据**：
  - 四份报告第 23 行及第 280 行：GOOG (78.6%)、META (79.2%)、AMD (80.2%)、NVDA (80.2%) 均触发了 TV/EV > 70% 或 > 80% 的高敏感度警示。
  - 综合估值中 DCF 权重依然为固定的 **21.82%**。
- **源码行号证据**：
  - `backend/app/engines/dcf.py` L622-632：仅将警告存入 `warnings` 文本列表。
  - `backend/app/engines/composite.py` L48-58, L129-150：综合引擎未读取 `warnings` 或 `tv_ratio` 对权重进行动态抑制。
- **财务严谨性澄清**：
  - 终值占比较高反映了企业价值更多取决于长期永续现金流，不能断言模型“失去了 DCF 意义”；
  - 警示信息未进入综合加权决策属于控制闭环缺失，AI 提出的阶梯式降权规则属于一种备选风控策略，需经策略校准，而非已批准硬门槛。

---

### 【严重问题 4】GOOG 的 NTM EPS 仍然包含巨额一次性/非经营收益

- **裁定状态**：`unproven` / `needs-info`（一次性收益存在属实，但“是否污染了 NTM EPS”尚缺乏 vendor 口径证据）
- **报告位置证据**：
  - GOOG 报告第 105 行、117 行：`NTM day-weighted blend: 30.7% FY1 (20.60) + 69.3% FY2 (14.85) = $16.61`。
  - FY1 EPS ($20.60) 显著高于 FY2 EPS ($14.85)。
- **源码行号证据**：
  - `backend/app/providers/yfinance_provider.py` L895-931：直接采用 yfinance `earnings_estimate.loc["0y", "avg"]`。
  - `backend/app/services/projections.py` L120-135：直接对两个年度值进行日历线性插值。
- **一手事实核验与证据限制**：
  - Alphabet 2026-06-30 10-Q 原文中，Q2 确实存在其他收益净额约 $98B（权益证券未实现增值净额约 $99B）。
  - **关键待证点**：卖方分析师对 Alphabet FY2026 的一致预期（$20.60）是否为已剔除非经常性损益的 Adjusted/Non-GAAP 经营性口径，目前缺乏 vendor 明细披露证据。在未取得确定口径前，不可将“EPS 受到污染”作为已证实的事实 Bug。

---

### 【严重问题 5】Bull 情景同时向三个方向放松（高成长 × 低资本成本 × 高永续）

- **裁定状态**：`partial`（事实确认，属于情景参数校准问题）
- **报告位置证据**：
  - NVDA 报告第 234~236 行、第 256~264 行：Base EV $4.75T ($199.05) -> Bull EV $9.23T ($384.50)。
  - META 报告第 234~236 行：Base $686.70 -> Bull $1,315.74。
- **源码行号证据**：
  - `backend/app/config.py` L21-26：`DEFAULT_DCF_WACC = ScenarioValues(low=0.12, base=0.10, high=0.08)`；`DEFAULT_DCF_TERMINAL_GROWTH = ScenarioValues(low=0.03, base=0.03, high=0.04)`。
  - `backend/app/engines/dcf.py` L66-74：Bull 情景同时选取最高增长率、最低贴现率和最高永续增长率。
- **宏观与财务理论框架校准**：
  - 美国财政部 2026-09-09 官网 10 年期国债收益率为 **4.83%**。
  - 在情景分析中，乐观情景同时假定更高成长、更低资本成本和更高终值增速属于常见的情景构建方法，并不属于程序代码 Bug。
  - 严谨的 WACC 建模必须基于 **CAPM 权益成本（$K_e = R_f + \beta \times \text{ERP}$）与市场价值资本结构下的税后债务成本（$K_d \times (1 - T)$）加权框架**，不能脱离 Beta 与资本结构凭空断言“WACC 必须保底 8.5%~9.0%”；核心数学约束依然为 $WACC > g$ 且分母差额不应过窄导致数值膨胀。

---

## 3. 离线季度缺字段诊断验证 (Reproducible Offline Diagnostics)

为证实 `_TickerBundle` 在当前源码下因类属性缺失导致季度表访问抛出 AttributeError 的确定性事实，执行以下离线诊断（无需网络请求，无需修改代码）：

```powershell
# 离线诊断命令；必须在 D:/workshop/stock-valuation/backend 目录运行
d:\workshop\stock-valuation\.venv\Scripts\python -c "from app.providers.yfinance_provider import _TickerBundle
b = _TickerBundle('TEST', 'TEST')
for name in ('_qbs', '_qcf', '_qfin'):
    try:
        getattr(b, name)
        print(f'{name}: exists')
    except AttributeError as e:
        print(f'{name}: missing -> {e}')
"
```

**真实控制台输出 (Actual stdout)**：
```text
_qbs: missing -> '_TickerBundle' object has no attribute '_qbs'
_qcf: missing -> '_TickerBundle' object has no attribute '_qcf'
_qfin: missing -> '_TickerBundle' object has no attribute '_qfin'
```
**进程退出码 (Exit Code)**：`0`。

**实证结论**：`_TickerBundle` 实例确实未初始化 `_qbs`, `_qcf`, `_qfin` 属性，使得后续在 `_fetch_property` 中执行 `getattr(self, prop_name)` 时确定性抛出 AttributeError，并被外层 `except Exception: return None` 抑制，从而确证了 live 路径下季度表接口恒定返回 None 的根因。

---

## 4. 文件 SHA256 审计与修订追踪记录 (Audit File Hashes & Revisions)

以下为 Worker 中间版本记录，主控后续修正了公式转义、AMD日期及定级措辞，不再代表最终文件校验值。用于锁定原始输入的SHA256见第5节。

| 文件路径 | 初始交付版本 SHA256 | 返工修订版本 SHA256 | 修订要点 |
| :--- | :--- | :--- | :--- |
| `evidence.md` | `2446C2E85217AB68BC8B5F13581053F55BE3B3EA3C99E64D6E628DC7F00289C8` | `[Updated in place]` | 纠正历史倍数代码行号及无历史提取事实；限定 live 季度回退路径；消除造假指控并改用财务驱动解释；删除主观动机；补充 CAPM 框架及离线诊断输出。 |
| `spec.md` | `30BEF9A01131BA0A3A0BFCA320E6CB1A6C54130A6856C77B627EDC2B3949AA4C` | `E7378E9110BF63A0D11936E55049BC6A1B2842677F85484E9F02EDD8FCDD4C89` | 将所有门槛调整为待校准候选；工单状态按规则标记为 needs-triage；补充 CAPM 规范及 TTM 期间标签重新对齐规范。 |
| `issues/01-synthetic-forward-metrics.md` | `5A6BE52D2158F752AC70141803CAEBA75D8FEA47B87D21D1F4DC94C90263BE8A` | `50730828896CCEB08CE2E83F0964A36D3347EAC205FDBC1CBE7F7A654A355EF9` | 消除“算法造假”用语，改为细化财务驱动科目；不机械禁止相同增速；保护 FCFE/FCFF 隔离。 |
| `issues/02-quarterly-fallback-bundle-bug.md` | `E956A82148F86D7523BFA1230531E9A460CA214E72B30A74D1E7B3EF4AE9D330` | `6651DDD5833B48C9AEB420560A1E61D29D076D0EF224A071C679CC5CB938491F` | 限定为 live 路径未声明属性 Bug；修正 NVDA 日期为 2026-07-26；验收标准以完整 fixture 为条件并保留合法回退。 |
| `issues/03-company-specific-multiples.md` | `C28ACF90D155EBE767F77A953BAB168F33CCEA20285CD58929635CE05358D7F6` | `2746ED22658B6659F6DB3A977395706F1DCBD3DA6710A9430ABEDD640355EB50` | 修正为当前函数直接返回 None 的事实；去除非法性断言；不设静态行业白名单。 |
| `issues/04-dcf-growth-fade.md` | `B9C3072C9EB4FAA1611775F8A8CE856516C2DBBC2DF07C50437175A360956AE6` | `402B2E73820B293CF2469E5E17A46E7F5E865B53968C2F309048E26F942B5426` | 删除“为确定性所以固定增速”等主观动机断言，纯粹从财务建模角度表述 fade down 方案。 |
| `issues/05-tv-sensitivity-weight-gate.md` | `4E3F2DCA12582ED7BF9ECF88934FC8667BE9FA57DF734307B50AB65D3B512977` | `91943ADA15978136A3808919A986F762551528F5968A4ADDC623CCE78F93B1B3` | 调整为 Status: needs-triage；删除高贴现率正常现象与失去 DCF 意义断言；降权作为待评估候选。 |
| `issues/06-goog-eps-one-off-normalization.md` | `29B2CCE08AA7B04F7780E40C332367A670892F85B09AC940CE75CD979247B294` | `86F507CE6F490F82A2977E3C3CBD3AEE2CC1E9FE8B07CAC1E3DD1ECDA3DA7F2E` | 维持 needs-info；保留未证实判断，强调 vendor 预测口径待查。 |
| `issues/07-bull-scenario-relaxation.md` | `6F726C13168582FED581264625B720440B1A17B71F26DB386703C22BCE8B0002` | `81D0123CCC155B650E146FE902AFB344102F666F6F8AA8429882263DBE2C81C5` | 调整为 Status: needs-triage；删除无依据的硬编码下限；引入 CAPM 及税后债务资本结构框架。 |
| `issues/08-model-disagreement-gate.md` | `25C2F722FB9DE1AB4D11A8E5E045E399784D957DC7613E773FA613C8BBB21C06` | `4D2038F375CD9967DB12B60862E6360C18A7A8755659F95CE4E54ABCD1A2321F` | 将 1.50x 熔断明确标示为待校准候选策略，作为附属决策门禁工单保留。 |

## 5. 主控最终复核与原始输入锁定

最终裁定以 [review.md](review.md) 为准；外部官方链接与口径限制也集中于该文件。七项中四项核心事实成立、两项部分认可、一项污染指控未证实；工单01由原AI的fatal调整为high，季度链路工单02保留fatal。

主控在 `D:/workshop/stock-valuation/backend` 运行以下离线诊断，退出码0（不修改产品）：

```powershell
..\.venv\Scripts\python.exe -c 'from app.providers.yfinance_provider import _TickerBundle; b=_TickerBundle("TEST", "TEST"); print({n:hasattr(b,n) for n in ("_qbs","_qcf","_qfin")}); print([b.get_quarterly_balance_sheet(),b.get_quarterly_cashflow(),b.get_quarterly_financials()])'
```

```text
{'_qbs': False, '_qcf': False, '_qfin': False}
[None, None, None]
```

主控Decimal算术复核：META现有权重剔除EV后重归一化为686.795036138…；按现金流组上限重算并使用引擎四位有效权重为680.555580。均仅为敏感度。

原始输入SHA256（主控使用PowerShell Get-FileHash计算，Downloads文件保留原处）：

| 文件 | SHA256 |
| --- | --- |
| C:/Users/Wayne/Downloads/GOOG_valuation_20260910_233253.md | 4204E2B5A738B082E18BDBBBEB74315689A26233C7F1908366E487FB148CBD34 |
| C:/Users/Wayne/Downloads/META_valuation_20260910_233228.md | D796114160A8D5CA75C7E5745E3C93402DE3E73F3D7D5BC095F3B700D2D79D71 |
| C:/Users/Wayne/Downloads/AMD_valuation_20260910_233208.md | 4341C167CEC976BB0B8253070522D9FE321EF62CE1EC4C67E0C75BCABEC6F59B |
| C:/Users/Wayne/Downloads/NVDA_valuation_20260910_233148.md | 811679D5061F6AFC6752DD7B4400D7A79F179002AAA6A9894F8143A79904185C |
| ai_comment/20260910.md | E66BB2EB1D3351224FC1890E03613279204398373B5E74DC126F541B7C72DAF5 |

未运行完整pytest、前端检查、build或实时估值重算；无需为文档审计重复产品全测。只保留相关离线缺陷诊断和算术证据。

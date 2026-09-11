# 估值引擎缺陷与审计实施规范 (Valuation Audit Specification)

**规范状态**：Draft Specification (Candidate Proposals for Review)  
**归属目录**：`.scratch/valuation-ai-audit-20260911/spec.md`  
**关联任务**：`task_33586c7752e1` / `ctx_6e452dc1493f`  
**执行纪律**：Execution: deferred_by_user（本阶段纯审计建单与方案规范化，严禁修改产品代码，不跑整套产品测试，不 commit/push）。

---

## 一、架构整改原则与系统目标

针对 `ai_comment/20260910.md` 披露的 2 个致命问题与 5 个严重问题，本规范确立下一阶段重构的核心原则：
1. **数据真实与契约完整**：修复默认 live 模式下新建 bundle 属性声明缺陷，恢复季度滚动（TTM）与资产负债表点时间（PIT）数据的提取路径；同时保留上游数据客观缺失或断档时的合法年报回退。
2. **预测溯源与财务逻辑驱动**：规范前瞻财务指标生成机制，显式标记 `derived` 来源，并引入细分财务驱动（Margin、CapEx、营运资本与净借款口径），禁止表面上仅做同增速禁止的粗暴限制。
3. **行业与公司特异化基准（无静态白名单）**：支持任意美股标的，按 GICS 行业或有效历史中位数构建分层参数基准，避免全局使用单一 fallback 假设。
4. **财务动态感知与衰减建模**：DCF 引擎引入预测期末向永续增长率平滑衰减机制（Growth Fade），消除末期断崖。
5. **决策门禁与分歧提示机制（候选策略）**：评估模型离散度监测与终值敏感度与加权控制的闭环联动规则，作为待校准候选策略供评审决策。
6. **财务期间精确对齐**：当报表口径由年度回退转换为真实 TTM 时，严格重新计算对应前瞻期间标签与日历权重，严禁将 TTM 基础错标为 FY 期间。

---

## 二、问题分类矩阵与工单清单 (Issues Inventory)

| 工单编号 | 工单文件 | 缺陷主题 | 裁定分类 | 初始状态 | 执行标记 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Issue 01** | `issues/01-synthetic-forward-metrics.md` | 致命1：前瞻指标缺乏细分财务科目驱动 | `confirmed` | `ready-for-agent` | `deferred_by_user` |
| **Issue 02** | `issues/02-quarterly-fallback-bundle-bug.md` | 致命2：Live 路径季度属性未声明致年报回退 | `confirmed` | `ready-for-agent` | `deferred_by_user` |
| **Issue 03** | `issues/03-company-specific-multiples.md` | 严重1：全量使用单一硬编码 Fallback 倍数 | `confirmed` | `ready-for-agent` | `deferred_by_user` |
| **Issue 04** | `issues/04-dcf-growth-fade.md` | 严重2：DCF 缺失预测期末至永续期增长率平滑衰减 | `confirmed` | `ready-for-agent` | `deferred_by_user` |
| **Issue 05** | `issues/05-tv-sensitivity-weight-gate.md` | 严重3：终值敏感度警示未进入加权闭环（候选策略） | `partial` | `needs-triage` | `deferred_by_user` |
| **Issue 06** | `issues/06-goog-eps-one-off-normalization.md` | 严重4：GOOG NTM EPS 一次性收益污染待证实 | `unproven` | `needs-info` | `deferred_by_user` |
| **Issue 07** | `issues/07-bull-scenario-relaxation.md` | 严重5：Bull 情景三向同时放松与宏观资本结构校准 | `partial` | `needs-triage` | `deferred_by_user` |
| **Issue 08** | `issues/08-model-disagreement-gate.md` | 附属：模型分歧提示与熔断门禁（候选策略） | `confirmed` | `needs-triage` | `deferred_by_user` |

---

## 三、各模块整改架构规范

### 1. 真实季度数据提取规范 (`_TickerBundle`)
- 修复 `_TickerBundle.__init__`，补充 `self._qbs = None`, `self._qcf = None`, `self._qfin = None` 属性声明。
- 规范异常处理：`_fetch_property` 仅安全捕获上游网络与超时异常，严禁捕获并抑制 AttributeError。
- **验收标准**：
  - 在提供完整 4 季度离散财报测试 fixture 的条件下，系统成功提取最新季度 PIT 现金与债务，产出 4 季度滚算 TTM 报表，`statement_basis` 返回 `TTM`，`annual_fallback` 为 `False`。
  - 当上游季度数据客观缺失、断档或不满足 4 季度连续性时，系统保留合法的 `ANNUAL_FALLBACK` 机制。

### 2. 前瞻财务指标构建规范 (`projections.py`)
- 保持 FCFE 与 FCFF 口径严格隔离：FCFE 用于 FCF Yield 模型，FCFF 用于 DCF 模型。
- 细化前瞻驱动科目建模：
  - EBITDA 优先通过 `Revenue_Est × Normalized_EBITDA_Margin` 建模；
  - 自由现金流推导应建立独立的 CapEx、营运资本变动（ΔNWC）、税后利息与净借款驱动假设，并在元数据中真实披露推导公式与期间标签。
  - 期间对齐：当基期由年度转为 TTM 时，前瞻期间必须重新对齐为当前时点的 NTM 或下一财年，严禁直接错标为旧的 `FY`。

### 3. 公司/行业特异化倍数配置规范 (`config.py` & `valuation_service.py`)
- 保持任意美股支持，不建立静态有限股票白名单。
- 建立分层倍数仲裁架构：
  - Level 1: 公司有效历史 3~5 年中位数（过滤离群值）；
  - Level 2: 公司所属行业（按 GICS 分类或上游行业标签）动态映射；
  - Level 3: 保守系统兜底 Fallback。

### 4. DCF 增长率衰减 (Growth Fade) 建模规范 (`dcf.py`)
- 实施平滑衰减模型：
  - Year 1~2：采用显式前瞻预测增速 $g_1, g_2$；
  - Year 3~5：增速逐年按线性插值平滑递减至永续增长率 $g_{terminal}$：
    $$g_t = g_2 - \frac{t - 2}{5 - 2} \times (g_2 - g_{terminal})$$
  - 避免末期断崖，并在预测明细表中公开呈现衰减轨迹。

### 5. 资本成本 (WACC) 与情景分析规范
- 摒弃无理论依据的固定下限假设，建立基于经典 CAPM 与资本结构的贴现率框架：
  - 权益资本成本：$K_e = R_f + \beta \times \text{ERP}$；
  - 加权平均资本成本：$WACC = \frac{E}{V} K_e + \frac{D}{V} K_d (1 - T)$；
  - 确保 $WACC > g_{terminal}$，对极小利差进行宏观敏感度风险警示。

### 6. 综合决策门禁候选策略规范 (`composite.py`)
- **终值占比提示与加权联动（候选提案）**：
  - 评估当 $TV / EV > 70\%$ 或 $> 80\%$ 时对 DCF 权重实施阶梯式缩减或标记为敏感性参考的策略，需经进一步校准。
- **模型分歧门禁（候选提案）**：
  - 评估计算各有效模型最大公允价值与最小公允价值比值（Ratio）；
  - 当分歧显著（如 Ratio 达到特定阈值）时，评估输出模型冲突预警或区间展示的交互策略。

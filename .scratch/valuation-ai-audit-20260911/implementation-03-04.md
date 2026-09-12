# 03/04 实施契约（2026-09-12）

## Goal

用户已授权修复03公司/行业针对性倍数和04DCF增长衰减，覆盖这两项原 deferred_by_user 状态。01/02已验收，保持其不变量；05—08不实施。基线 master / d0a7d62（与 origin/master 一致），主控启动时工作区干净。禁止commit/push。

## Scope / Ownership

单一 Worker 端到端负责所需 backend 配置/provider/仲裁/service/engines、frontend 类型/编辑/展示/Markdown、回归测试和证据。共用默认假设/API/export，故本轮不拆并行 Worker。主控负责财务裁决和验收；Worker 不另派 Worker。产物 implementation-report-03-04.md、verification/03-04/，仅更新03/04为进行中/待验收，不提前resolved。保留历史审计/01-02验收/工作流文档，不顺便改WACC、综合权重、EPS一次性调整等其他问题。

## Constraints / 主控裁决

### 03 参数选择和来源

1. 在现有 provider/normalizer 到默认 assumptions 的真实入口建立按指标独立的选择器：有效用户覆盖优先；可验证公司历史基准优于行业基准，再降至明确系统兜底。P/E、EV/EBITDA 分别决策，不要求同一级。FCFE yield 仅有同口径可信基准才差异化，否则原明确兜底加提示；本次不改变WACC政策。
2. 公司历史前瞻倍数必须有历史时点当时可得预测及价格/EV匹配，不准以当前预测回填历史、不准 trailing PE 冒充历史 forward PE、不准现在的市价倍数直接作为目标公允倍数。3—5年覆盖、样本量、正值/有限、异常过滤和时效要求须明确、可测试；没有数据明确不可用，不造时间序列。
3. 行业支持任意ticker，依据实际上游行业/sector标签，不设股票白名单。允许使用版本化、可更新的公开行业数据快照作为行业基准，必须有可核实来源、采集日、样本/统计方法、指标口径、币种/期间/估算属性，不能将配置假设标为实时动态基准。实际查阅一手资料并保存来源依据；网络运行需有界缓存/预算，不为每个请求无界抓取整个行业。
4. 找不到可比行业前瞻数据时，可以明确命名且有依据的行业估值假设层作为降级（与观测历史/动态基准分开）；但不能凭空为几个行业填写数值宣布解决。若现有公开源无法建立有效差异化层，在普通技术调查后用 Orca question 给主控具体方案/限制，不悄悄退化为只添加空接口且仍全量全局fallback。
5. 不同指标口径必须匹配（尤其运营EBITDA与标准EBITDA、FCFE与公司FCF yield不同），不兼容数据拒绝或明确保守降级。未知行业、缺失/过期/异常值均可审计降级，Level3必须在API/UI/Markdown提示参数特异性不足。保留真正模型不适用隔离，倍数选择不使银行/ADR等重新可用。
6. 低/中/高场景用公开分位数或清晰披露的配置spread生成，保持排序，spread不得假装统计结果。实际选中的每个参数显示公司/行业/系统/用户来源层级、基准值、样本/日期/口径及降级原因。覆盖合并/reset/股票切换不得使用全局可变对象串数据。

### 04 DCF fade 财务契约

1. 保持01/02前两年独立FCFF资格、缺任一期/非正隔离，不用历史FCFF重开生产退路。第3—5年的默认行为改为每个scenario线性收敛：g_t = g_start + ((t-2)/3)*(g_terminal-g_start)，t=3,4,5；g5精确等于该scenario永续率，Year6 = Year5*(1+g_terminal)。
2. g_start 使用当前引擎经来源选择、情景化和合法增长上下界处理后的起始率（默认来源FY1→FY2，可按现有显式增长覆盖作为起点），必须披露原始g2、有效起点和截断依据。保持现有覆盖请求可解析；旧dcf.fcf_growth覆盖定义为衰减起点，而非默认关闭fade。若提供constant模式只能显式opt-in并明确旧假设，非必要不新增模式。
3. g_start低于terminal时线性上升收敛，不强制所有轨迹递减；相等保持常量，负增长合法时同样收敛，禁止超调/非有限值。WACC>terminal、现有terminal上限保持。不要在插值后再截断导致g5不等terminal；若用户配置造成边界冲突须明确校验/解释。
4. PV/终值/sensitivity/情景图表/Markdown全部使用同一条有效轨迹。敏感性改变terminal时轨迹需按该terminal重算，不能正文fade而矩阵仍constant；前端不重复业务计算。逐年展示实际增长、FCFF、折现值及起点/终点/公式，不能仅改图表标签。

## Acceptance / 验证与证据

- 使用 diagnosing-bugs：已知审计根因，省略猜测性假设探索；先为真实路径编写并运行失败回归，再修复。保护旧测试有用不变量，解释旧常数结果断言的必要更新，不删除/skip失败换绿。
- 03：受控provider输入穿透normalizer/service/API，覆盖公司历史/行业/系统三级、用户覆盖、每指标独立降级；至少不同实际行业分类和未知行业，不限定特定四ticker；时效/异常/样本不足/口径不兼容有断言；证明默认结果实质使用选定参数，缓存/reset/股票切换不串数据。
- 04：精确Decimal验证g3/g4/g5、各年FCFF/PV/终值及价格；高增长/低于terminal/相等/负增长/覆盖/非法参数/敏感性轨迹；前两年输入不改变。保持综合排序与各模型不适用语义。
- 保存一份可复算数值例子及 source -> normalizer -> assumptions/projection -> engine -> API/export 链路。完整backend离线回归，frontend typecheck/lint/build及相关真实浏览器参数编辑、重置、切换和导出断言；只以真实退出码和原始日志报告。
- 对GOOG/META/AMD/NVDA及至少两个不同行业边界做有界live验证或明确历史live payload回放，保存原始输入与新响应，逐个列来源层级、fade轨迹、适用性。不要求所有模型都有值；网络失败与代码失败区分，不用demo冒充live。
- 完成报告列基线、实际provider/model、changed files、Acceptance PASS/FAIL/NOT RUN、命令/cwd/退出码、来源与数据限制。普通实施自主推进，重大未决财务政策使用question。完成有效worker_done后停下；主控验收前不关闭工单。

## 调度

Run: run_8822723e20ee；Task: task_e657b5846821；Dispatch: ctx_ef7ff6adc26d；Terminal: term_0c021f51-dd0a-4c3e-be46-b6a6d5049106。Orca 启动回执确认实际 codex / gpt-5.6-luna / max；主控 term_a2585170-f25e-4baf-aaa1-fd67e12d718a。仅为调度标识，不包含凭据。

沿用户此前“后续使用Codex Luna max”的明确指令启动新会话（旧worker已归档释放）；本次不声称Antigravity当前仍额度不足，当前额度未探测。用户要求主控仅剩等待时停下，不影响Worker端到端自主执行。

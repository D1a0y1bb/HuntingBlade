# HuntingBlade Challenge Strategy Layer Phase 1 设计

**日期**：2026-04-07  
**项目**：HuntingBlade  
**目标**：在现有显式控制面的基础上，新增一层正式的 `Challenge Strategy Layer`，把“单题当前处于哪个求解阶段、下一步应该尝试什么、为什么要 bump / broadcast / 暂缓”从隐式 prompt 经验，升级为可审计、可测试、可演进的结构化控制对象。

---

## 1. 背景

截至当前主线，HuntingBlade 已经完成了三件关键基础工作：

1. 共享 `coordinator_loop` 已成为统一控制主循环。
2. `azure / codex / claude` provider 已收缩为 advisor-only 适配层。
3. `Working Memory / Knowledge Store / Policy Engine` 已作为显式控制面接入运行链路。

当前主骨架已经清晰：

```text
poller -> coordinator_loop -> policy_engine -> coordinator_core -> swarm -> solver
```

但系统仍然存在一个明显的中间缺口：

`Working Memory` 已经能提炼 trace，`Policy Engine` 也已经能产出动作，但两者之间还缺一层真正表达“单题策略状态”的正式对象。

换句话说，系统现在已经有：

- 状态事实：平台状态、swarm 状态、结果状态
- 记忆材料：失败假设、开放假设、已验证发现、可复用知识
- 可执行动作：spawn / bump / broadcast

但还没有：

- “这道题现在大致处于侦察、利用、验证、收尾中的哪一步”
- “这次 bump 是延续既有思路，还是切换策略方向”
- “哪些 knowledge 是当前阶段应该读的，哪些暂时不该打扰 solver”
- “什么时候不应该 bump，而应该先等新证据”

因此，当前最值得推进的不是新的 provider 或新的架构名词，而是把 `Challenge Strategy Layer` 做成显式的一等公民。

---

## 2. 要解决的问题

### 2.1 当前问题

当前 `Policy Engine` 的决策方式仍然偏“规则直接出动作”：

1. 有未解题且没有 active swarm，就 `spawn`
2. 某题长时间无进展且有 `open_hypotheses`，就 `bump`
3. 有可命中的 knowledge，就 `broadcast`

这对 Phase 1 很合适，但长期会遇到三个上限：

1. **策略语义缺失**
   `open_hypotheses[0]` 只说明“有个可试方向”，不说明“为什么现在该试它”。

2. **bump 质量不稳定**
   当前 bump 主要依赖停滞时间和开放假设，无法区分“还在有效探索”与“已经进入错误方向反复试探”。

3. **控制叙事与代码边界不一致**
   README 已经能讲 `Plan + Memory + Knowledge + Tools`，但代码里真正显式的“Plan/Strategy”对象还不存在。

### 2.2 目标问题

我们需要一个最小但正式的策略层，回答以下问题：

1. 这道题当前处于哪个求解阶段？
2. 当前主策略是什么？是侦察、验证、利用、还是收尾？
3. 下一步最值得执行的动作是什么？
4. 这次 bump / broadcast 的理由是否能结构化记录？
5. 新证据到来时，策略状态如何更新？

---

## 3. 设计目标

1. 新增 `ChallengeStrategyState`，作为单题正式策略对象。
2. 新增“策略归纳”步骤，把 `Working Memory` 和运行态汇总为策略摘要。
3. 让 `Policy Engine` 消费 `StrategyState`，而不是直接消费零散字符串列表。
4. 让 advisor prompt 消费“策略摘要”，不再只读 memory summary。
5. 保持改动边界可控，不引入递归 coordinator、不引入新的常驻顶层模型。

---

## 4. 非目标

Phase 1 明确不做以下事情：

1. 不引入“递归式双引擎”或 coordinator of coordinators。
2. 不重写 solver 内部 ReAct 执行循环。
3. 不引入跨比赛持久化知识库或向量检索。
4. 不一次性把所有启发式规则替换成 LLM 规划器。
5. 不做大规模 `deps` 解耦重构。

---

## 5. 方案比较

### 方案 A：继续扩张现有 `PolicyEngine` 规则

做法：

- 继续在 `PolicyEngine` 里增加更多 if/else 与启发式
- 增加更多 memory 字段
- 不新增独立的 strategy 对象

优点：

- 实现成本最低
- 最快能继续堆功能

缺点：

- 策略语义继续隐式化
- `PolicyEngine` 会越来越像“大型条件分发器”
- 无法沉淀清晰的“单题策略状态”

### 方案 B：为每道题增加一个常驻 Planner LLM

做法：

- 每个 challenge 周期性调用一个 planner 模型
- planner 直接输出阶段、策略、下一步动作

优点：

- 产品叙事强
- 规划表达能力上限高

缺点：

- 成本和复杂度显著上升
- 在当前阶段会过早引入不稳定因素
- 不利于测试和回归

### 方案 C：新增显式 `StrategyState` + 轻量 `Strategy Reducer`

做法：

- 新增结构化策略对象
- 用现有 runtime state、working memory、knowledge match 归纳出策略状态
- 让 policy 和 advisor 都消费这一层

优点：

- 最符合当前代码基线
- 风险可控，回归清晰
- 真正补上“Plan/Strategy”这一层

缺点：

- 需要新建一套数据模型与 reducer 逻辑
- 短期内还不是“智能规划器”，更接近显式策略归纳器

**结论**：采用方案 C。  
这是当前性价比最高的推进方向，也是最适合作为下一阶段主线的工作。

---

## 6. 目标架构

Phase 1 的目标形态如下：

```text
Platform Facts / Runtime State
    -> Working Memory Refresh
    -> Strategy Reducer
    -> ChallengeStrategyState
    -> Policy Engine
    -> Actions
    -> Action Executor
    -> Swarm / Solver Runtime
    -> Trace / Results / Findings
    -> Working Memory Refresh
```

相比当前架构，唯一新增的正式层就是：

```text
Working Memory -> Strategy Reducer -> ChallengeStrategyState -> Policy Engine
```

这层的作用不是“替代 policy”，而是给 policy 一个更稳定、更有语义的输入面。

---

## 7. 核心设计

### 7.1 新增对象：`ChallengeStrategyState`

建议新增模块：

- `backend/control/strategy_state.py`

建议结构：

```python
@dataclass
class ChallengeStrategyState:
    challenge_name: str
    stage: str
    goal: str
    active_hypothesis: str
    supporting_evidence: list[str]
    blocked_reasons: list[str]
    next_actions: list[str]
    confidence: float
    last_transition_reason: str
```

#### 字段语义

- `stage`
  当前阶段，建议第一版只允许有限枚举：
  - `recon`
  - `exploit`
  - `verify`
  - `finalize`
  - `blocked`

- `goal`
  当前阶段的明确目标，例如：
  - “确认输入点与攻击面”
  - “验证格式化字符串偏移”
  - “构造可提交 flag”

- `active_hypothesis`
  当前最值得推进的主假设，不是所有候选假设的堆叠。

- `supporting_evidence`
  支撑当前策略判断的证据摘要，来源于 memory / trace / results。

- `blocked_reasons`
  当前阻塞因素，例如：
  - “连续 3 次 bump 没有新证据”
  - “provider 建议为空且 memory 未更新”
  - “只看到失败提交，没有新的利用路径”

- `next_actions`
  策略层推荐的下一步动作摘要，不是直接的执行对象。  
  例如：
  - “继续验证 offset 7”
  - “广播 category knowledge”
  - “暂缓 bump，等待新证据”

- `confidence`
  策略层对当前阶段归纳的信心，范围 `0.0 ~ 1.0`

- `last_transition_reason`
  阶段切换理由，例如：
  - “从 recon 转 exploit：出现 candidate finding 并指向明确利用面”
  - “从 exploit 转 blocked：长时间停滞且未产生新 evidence”

### 7.2 新增模块：`Strategy Reducer`

建议新增模块：

- `backend/control/strategy_reducer.py`

职责：

1. 读取 `CompetitionState / ChallengeState / SwarmState`
2. 读取 `ChallengeWorkingMemory`
3. 归纳出当前 `ChallengeStrategyState`

这个 reducer 必须是：

- 无副作用的
- 可测试的
- 规则优先的

Phase 1 不让 LLM 直接生成 `StrategyState`。  
原因很简单：这层是未来所有 planner / advisor / policy 的基座，必须先可回归。

### 7.3 阶段判定规则

第一版只做最小阶段机：

#### `recon`

判定条件：

- 只有少量零散发现
- 还没有清晰可执行利用假设
- 尚未进入明确验证动作

典型信号：

- `open_hypotheses` 很少或为空
- 只有 artifacts，没有 candidate exploit

#### `exploit`

判定条件：

- 存在明确主假设
- 最近有新 evidence 或新指导
- solver 仍在有效探索

典型信号：

- 有高质量 `open_hypotheses`
- 有与利用方向对应的 artifacts / findings

#### `verify`

判定条件：

- 已进入“验证结果/构造 flag/确认提交格式”的阶段

典型信号：

- 已出现强利用证据
- 已接近 `submit_flag` 或围绕 flag correctness 反复验证

#### `finalize`

判定条件：

- 题目已确认 solved，或进入确定性收尾路径

#### `blocked`

判定条件：

- 长时间停滞
- 多次 bump 无新 evidence
- memory 中重复噪声较多

### 7.4 `PolicyEngine` 的改造方式

现有 [backend/control/policy_engine.py](/Users/d1a0y1bb/Desktop/HuntingBlade/backend/control/policy_engine.py) 不直接废弃，而是改造成“消费策略状态”的调度器。

改造原则：

1. `PolicyEngine` 负责做执行级决策
2. `StrategyReducer` 负责做策略级归纳
3. 不能让 `PolicyEngine` 再自己反推策略语义

#### 当前

```text
WorkingMemory -> PolicyEngine -> BumpSolver
```

#### 目标

```text
WorkingMemory -> StrategyReducer -> StrategyState -> PolicyEngine -> BumpSolver
```

#### 具体变化

- `BumpSolver` 不再默认使用 `open_hypotheses[0]`
- 而是优先使用 `strategy.active_hypothesis`
- 如果 `stage == blocked` 且 `confidence` 很低，policy 可以选择“不 bump”
- `BroadcastKnowledge` 应优先发生在：
  - `stage == recon` 且 category knowledge 明显匹配
  - 或 `stage == blocked` 且 knowledge 可能帮助切换方向

### 7.5 Advisor 输入面的改造

现有 advisor 已经是 provider-neutral suggestion layer，这是好基础。

下一步不是让 advisor 更强，而是让 advisor 看见更好的输入。

建议在 advisor context 中新增：

- `strategy_summary`

示例：

```text
stage=exploit
goal=验证格式化字符串偏移并获取 canary 泄漏
active_hypothesis=Try format string offset 7
supporting_evidence=['candidate finding: possible format string in echo handler']
blocked_reasons=[]
next_actions=['继续验证 offset 7', '若失败则切换到 offset 9']
confidence=0.78
```

这样 advisor 读到的是“当前策略状态”，而不是一堆零散 memory 条目。

---

## 8. 数据流与更新时机

Phase 1 的刷新顺序建议如下：

1. `coordinator_loop` 刷新 runtime snapshot
2. 增量读取 trace，更新 working memory
3. 对每个 active challenge 调用 `StrategyReducer`
4. 将结果写入 `deps.runtime_state` 的独立 strategy map，或 `deps.strategy_store`
5. `PolicyEngine` 基于 strategy state + knowledge 生成 actions
6. 若 advisor 存在，将 `strategy_summary` 一并传入 advisor context

建议新增存储：

- `deps.strategy_states: dict[str, ChallengeStrategyState]`

不建议把策略对象直接塞回 `ChallengeWorkingMemory`，因为两者职责不同：

- `Working Memory` 是材料层
- `Strategy State` 是解释层

---

## 9. 失败处理与边界

### 9.1 Reducer 失败策略

如果 reducer 本轮无法可靠归纳策略：

- 不抛出中断主循环的异常
- 回退到保守策略：
  - `stage = recon`
  - `confidence = 0.0`
  - `next_actions = []`

### 9.2 防止策略层成为“第二个巨石模块”

Phase 1 必须克制：

1. 不在 reducer 中直接调用 provider
2. 不在 reducer 中直接执行动作
3. 不让 reducer 管理全局并发

策略层只回答一件事：

> “这道题现在最合理的策略解释是什么？”

### 9.3 避免过度产品化叙事先行

文档或 README 可以在实现后更新为：

`Platform State -> Memory -> Strategy -> Policy -> ReAct Solver`

但在代码层没有落地前，不要提前宣称“递归式双引擎”。

---

## 10. 测试设计

Phase 1 至少需要以下测试：

### 10.1 Reducer 单元测试

覆盖：

1. 从零散 artifacts 归纳为 `recon`
2. 从可执行主假设归纳为 `exploit`
3. 从高质量利用证据归纳为 `verify`
4. 从长期停滞归纳为 `blocked`

### 10.2 Policy 集成测试

覆盖：

1. `strategy.active_hypothesis` 驱动 bump
2. `blocked` 状态下 policy 选择抑制 bump
3. `recon` 状态下优先广播知识而不是无脑 bump

### 10.3 Advisor 输入测试

覆盖：

1. advisor context 包含 `strategy_summary`
2. strategy summary 只含当前 challenge 的摘要
3. provider adapter 不直接生成策略状态，只消费现成 summary

---

## 11. 指标与验收

Phase 1 不要求立刻显著提升解题率，但必须能带来以下可观测收益：

1. **bump 质量提升**
   - 指标：bump 后产生新 evidence 的比例上升

2. **无效 bump 降低**
   - 指标：连续无新增 evidence 的重复 bump 次数下降

3. **控制面可解释性增强**
   - 指标：日志或调试输出中能看到 `stage / goal / active_hypothesis / reason`

4. **后续重构抓手形成**
   - 指标：后面 Capability Packs 与 Runtime Decomposition 可以直接消费 strategy state

Phase 1 完成的判定标准：

1. `StrategyState` 已进入共享控制面主链路
2. `PolicyEngine` 已优先使用 strategy 输入
3. advisor prompt 已接到 `strategy_summary`
4. 有完整单测与集成测试覆盖主要状态流转

---

## 12. 分阶段落地建议

### Phase 1A：先落数据模型与 reducer

内容：

- 新增 `ChallengeStrategyState`
- 新增 `StrategyReducer`
- 补 reducer 测试

### Phase 1B：接入 policy

内容：

- 让 `PolicyEngine` 消费 strategy state
- 改造 bump / broadcast 判定
- 补 policy flow 测试

### Phase 1C：接入 advisor summary

内容：

- advisor context 添加 `strategy_summary`
- 更新 provider adapter 测试

这个拆分的好处是：

- 每一步都能单独验证
- 不会一次性把控制面全部翻新
- 与当前刚落地的 memory/knowledge/control 主线天然衔接

---

## 13. 推荐结论

现在最该推进的工作，不是新 provider，不是递归式多层 planner，也不是先做大规模 runtime 解耦。

**最应该推进的是：**

> `Challenge Strategy Layer Phase 1`

原因很明确：

1. 它正好补在当前架构最空的一层。
2. 它能同时服务解题率、稳定性和架构叙事三条主线。
3. 它能把当前已经存在的 `Memory / Knowledge / Policy` 真正串成一个更完整的控制闭环。

下一步如果进入 implementation planning，应直接围绕以下主题展开：

> 把 `Working Memory -> Strategy State -> Policy Actions` 变成共享控制面的正式主链路

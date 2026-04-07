# HuntingBlade Capability Packs / Tool Contracts Phase 1 设计

**日期**：2026-04-07  
**项目**：HuntingBlade  
**目标**：在现有 `Plan/Control -> Swarm -> Solver/ReAct` 主骨架之上，把 solver 侧“题目需要什么能力、运行时能提供什么能力、这些能力最终如何暴露为工具与提示”的隐式逻辑，升级为显式的 `Capability Packs / Tool Contracts` 装配层，为后续稳定性重构、provider 适配收口和更高阶策略演进打下统一执行面。

---

## 1. 背景

截至当前主线，HuntingBlade 在控制面已经完成了第一阶段关键收口：

1. `coordinator_loop` 已成为统一控制主循环。
2. `Working Memory / Knowledge Store / Policy Engine / Strategy Layer` 已作为显式控制对象接入协调链路。
3. provider coordinator 已逐步从“业务控制器”收缩为“推理适配器”。

当前主骨架已经可以清晰表达为：

```text
Platform State
    -> Working Memory
    -> Strategy Layer
    -> Policy Engine
    -> Coordinator Actions
    -> Swarm
    -> Solver Runtime
    -> Trace / Findings / Results
```

但随着策略层第一阶段落地，系统新的主要短板已经从“控制面缺少显式策略”转移到了“执行面缺少显式能力边界”。

当前 solver 侧仍然存在三个明显问题：

1. **工具集是平铺装配的**
   `backend/agents/solver.py` 中 `_build_toolset()` 仍然直接拼接 `bash / read_file / write_file / list_files / submit_flag / web_fetch / webhook_create / webhook_get_requests / check_findings / notify_coordinator / view_image`。
   这意味着系统真正表达的是“有哪些工具函数”，而不是“solver 拥有哪些能力”。

2. **prompt 仍承担运行时能力适配**
   `backend/prompts.py` 当前通过 `has_named_tools=True/False` 来切换提示语义。这说明 prompt 不只是“描述任务”，还在承担“当前 runtime 有什么工具契约”的职责。

3. **provider/runtime 差异仍泄漏到业务路径**
   当前 named-tools runtime 与 bash-only runtime 的差异，仍散落在：
   - `backend/agents/solver.py`
   - `backend/agents/codex_solver.py`
   - `backend/agents/claude_solver.py`
   - `backend/prompts.py`

换句话说，控制面已经开始显式化，但执行面依然是“平铺工具 + prompt 分叉 + provider 例外逻辑”的组合。

这会带来四个中期问题：

1. 新增能力时，需要同时修改多个 solver 与 prompt 分支。
2. provider 差异不容易被隔离，后续 runtime 兼容性重构成本高。
3. policy/strategy 虽然更显式了，但无法基于统一的能力语义推理“这类题适合给 solver 什么能力”。
4. 对外可以讲 `Plan + Memory + Tools`，但代码里还没有真正显式的 `Capabilities` 层。

因此，在策略层第一阶段之后，最值得推进的不是新的 planner 名词，也不是立即做大规模 runtime 重构，而是先把 **`Capability Packs / Tool Contracts`** 做成执行面的一等公民。

---

## 2. 要解决的问题

### 2.1 当前问题

当前系统在执行面上的问题本质上是“能力语义缺位”：

1. `solver` 只能表达“把这些工具给模型”，不能表达“这道题需要哪些能力”。
2. `prompt` 只能用布尔分叉表达“有没有 named tools”，不能表达“当前 runtime 如何提供某项能力”。
3. `codex_solver`、`claude_solver`、主 `solver` 都有自己的一套工具暴露方式，但没有共享的能力契约层。
4. “图片题怎么分析”“web 题如何做 OOB”“没有 named tool 时怎么做 flag 提交”等逻辑，同时散落在 prompt 和 runtime 里。

### 2.2 目标问题

Phase 1 需要回答以下问题：

1. 题目侧如何显式描述“需要什么能力”？
2. 运行时侧如何显式描述“能以什么方式提供这些能力”？
3. 同一项能力如何在不同 runtime 下映射成不同的工具暴露方式？
4. solver 如何只消费“已装配好的能力结果”，而不自己承担 provider 差异判断？
5. prompt 如何回到“任务与能力说明”本身，而不是继续承担复杂运行时分叉？

---

## 3. 设计目标

1. 新增显式 `Capability Model`，让能力成为独立于具体工具的一等公民。
2. 新增 `ChallengeProfile` 与 `RuntimeProfile`，分别表达题目需求与运行时约束。
3. 新增 `Capability Packs` 机制，用统一模板组合 solver 所需能力。
4. 新增 `Tool Contracts`，把能力映射为当前 runtime 下实际暴露的工具与提示片段。
5. 让 `solver.py`、`codex_solver.py`、`claude_solver.py` 共享同一套能力描述入口。
6. 让 `prompts.py` 不再以 `has_named_tools` 这种布尔值作为核心控制面。
7. 保持 Phase 1 为“最小闭环迁移”，不引入新的顶层规划器，不重做 coordinator 主循环。

---

## 4. 非目标

Phase 1 明确不做以下事情：

1. 不引入新的“递归式双引擎”或多层 coordinator。
2. 不重写 `backend/agents/coordinator_loop.py` 主循环。
3. 不重写现有具体工具实现，如 `bash`、`web_fetch`、`submit_flag`、`view_image`。
4. 不做能力使用效果的闭环学习，不把能力结果回灌到 policy。
5. 不做动态工具热插拔。
6. 不做长期记忆、跨比赛知识库或向量检索。
7. 不一次性完成 `deps` 大拆分或所有 provider runtime 的彻底统一。

---

## 5. 方案比较

### 方案 A：显式 `Capability Packs / Tool Contracts` 装配层

做法：

- 新增能力模型、题目画像、运行时画像、能力 pack、工具契约与 assembler。
- solver 不再自己拼平铺工具表，而是消费装配结果。
- prompt 不再使用 `has_named_tools` 作为主分叉，而是消费能力片段。

优点：

- 与现有主线最兼容，改动边界清晰。
- 能同时改善求解质量、provider 适配与维护性。
- 是后续 runtime 重构和更高阶 planner 演进的稳定基础。

缺点：

- 需要引入一层新的抽象和装配流程。
- 初期会有新旧装配逻辑并存的过渡期。

### 方案 B：直接推进更强的递归 planner / 多层 orchestrator

做法：

- 在现有策略层之上继续叠更强的 planner。
- 让 planner 直接决定题目子任务、工具策略甚至多轮执行路径。

优点：

- 产品叙事强。
- 理论上对复杂任务有更高上限。

缺点：

- 现阶段属于“把更复杂的调度压在还不够干净的执行平面上”。
- 失败归因和调试成本会迅速上升。
- 如果能力层没有显式建模，planner 的决策边界会继续模糊。

### 方案 C：先做大规模 runtime / deps 拆分

做法：

- 优先拆 `CoordinatorDeps`、runtime state 和 provider 适配层。
- 暂时保留 solver 侧平铺工具与 prompt 分叉。

优点：

- 对稳定性和维护性有直接帮助。

缺点：

- 无法先解决当前 solver 侧最直接的能力语义问题。
- 会把“能力建模”继续推迟，导致执行面与控制面长期失衡。

**结论**：采用方案 A。  
当前阶段最值得推进的是显式 `Capability Packs / Tool Contracts`，而不是继续向上叠 planner，也不是立刻做大规模 runtime 大拆。

---

## 6. 目标架构

Phase 1 目标形态如下：

```text
Challenge Meta / Distfiles / Connection Info
    -> ChallengeProfile

Solver Runtime / Provider / Vision Support / Tool Exposure Mode
    -> RuntimeProfile

ChallengeProfile + RuntimeProfile
    -> CapabilityPlanner
    -> Capability Packs
    -> ToolContractAssembler
    -> ResolvedCapabilities
    -> Solver Runtime
        -> toolset / dynamic tools / prompt fragments
```

这层新增的不是新的顶层控制器，而是执行面里的正式装配链路：

```text
ChallengeProfile + RuntimeProfile
    -> Capability Packs
    -> Tool Contracts
    -> ResolvedCapabilities
```

它的职责是把“能力语义”从具体工具和 provider 差异中剥离出来。

---

## 7. 核心抽象

### 7.1 `ChallengeProfile`

建议模块：

- `backend/capabilities/challenge_profile.py`

职责：

- 从 `ChallengeMeta + distfiles + connection_info` 提炼题目所需能力。
- 只描述题目特征，不描述 provider 和 runtime。

建议字段：

```python
@dataclass(frozen=True)
class ChallengeProfile:
    challenge_name: str
    category: str
    has_images: bool
    has_connection_info: bool
    connection_kind: str | None
    needs_binary_analysis: bool
    needs_web_fetch: bool
    needs_oob_hooks: bool
    needs_flag_submission: bool
```

说明：

- `has_images` 用于决定是否需要图片分析相关能力。
- `connection_kind` 可以先使用有限枚举，例如 `web / tcp / other / none`。
- `needs_binary_analysis` 可以由题型和附件特征共同判断。
- `needs_oob_hooks` 第一阶段可以保守推导，不必追求复杂静态分析。

### 7.2 `RuntimeProfile`

建议模块：

- `backend/capabilities/runtime_profile.py`

职责：

- 描述当前 solver runtime 能如何提供能力。
- 这是 provider/runtime 兼容差异的正式入口。

建议字段：

```python
@dataclass(frozen=True)
class RuntimeProfile:
    runtime_name: str
    supports_named_tools: bool
    supports_dynamic_tools: bool
    supports_vision: bool
    prefers_bash_only: bool
```

说明：

- 主 `solver` 可表达为 named-tools runtime。
- `codex_solver` 可表达为 dynamic-tools runtime。
- `claude_solver` 可表达为 bash-only runtime。
- `supports_vision` 是能力暴露条件之一，但不等于“必须暴露视图工具”。
- Phase 1 中当前三类 runtime 的能力暴露模式应保持互斥，即同一个 runtime 不同时走 named-tools 与 bash-only 语义。

### 7.3 `CapabilitySpec`

建议模块：

- `backend/capabilities/specs.py`

职责：

- 定义最小能力单元。
- 能力先于工具存在，工具只是能力的一种暴露方式。

建议首批能力枚举：

```python
class CapabilitySpec(str, Enum):
    SHELL_EXEC = "shell.exec"
    FILESYSTEM_READ = "filesystem.read"
    FILESYSTEM_WRITE = "filesystem.write"
    FILESYSTEM_LIST = "filesystem.list"
    FLAG_SUBMIT = "flag.submit"
    NETWORK_WEB_FETCH = "network.web_fetch"
    NETWORK_WEBHOOK_OOB = "network.webhook_oob"
    VISION_INSPECT_IMAGE = "vision.inspect_image"
    COORDINATION_FINDINGS = "coordination.findings"
    COORDINATION_NOTIFY = "coordination.notify"
    BINARY_ANALYSIS = "binary.analysis"
```

说明：

- `BINARY_ANALYSIS` 在第一阶段更多用于 prompt capability fragment，不一定直接对应一个独立工具。
- `FLAG_SUBMIT` 与具体 `submit_flag` 工具解耦，便于 bash-only runtime 走命令式提交。

### 7.4 `CapabilityPack`

建议模块：

- `backend/capabilities/packs.py`

职责：

- 把若干能力组合成可复用模板。
- solver 不直接拼能力，而是通过 pack 组合得到能力集合。

建议首批 pack：

- `core_local_pack`
  - `shell.exec`
  - `filesystem.read`
  - `filesystem.write`
  - `filesystem.list`
  - `flag.submit`

- `web_pack`
  - `network.web_fetch`

- `oob_pack`
  - `network.webhook_oob`

- `vision_pack`
  - `vision.inspect_image`

- `coordination_pack`
  - `coordination.findings`
  - `coordination.notify`

- `reverse_pack`
  - `binary.analysis`

### 7.5 `ToolContract`

建议模块：

- `backend/capabilities/contracts.py`

职责：

- 把某项能力映射为“当前 runtime 下实际如何暴露”。
- 它既负责工具暴露，也负责 prompt 里的能力说明片段。

建议结构：

```python
@dataclass(frozen=True)
class ToolContract:
    capability: CapabilitySpec
    tool_functions: tuple[object, ...] = ()
    dynamic_tool_specs: tuple[dict[str, object], ...] = ()
    prompt_fragments: tuple[str, ...] = ()
```

说明：

- named-tools runtime 可通过 `tool_functions` 暴露实际函数。
- dynamic-tools runtime 可通过 `dynamic_tool_specs` 暴露 JSON-RPC 动态工具。
- bash-only runtime 即使没有 named tool，也可以通过 `prompt_fragments` 表达如何完成该能力。

---

## 8. 统一装配结果

建议新增统一结果对象：

```python
@dataclass(frozen=True)
class ResolvedCapabilities:
    challenge_profile: ChallengeProfile
    runtime_profile: RuntimeProfile
    capabilities: frozenset[CapabilitySpec]
    tool_functions: tuple[object, ...] = ()
    dynamic_tool_specs: tuple[dict[str, object], ...] = ()
    prompt_fragments: tuple[str, ...] = ()
    capability_summary: str = ""
```

作用：

1. solver 统一消费一个装配结果，而不是自己做 provider 分叉。
2. prompt 统一消费 `prompt_fragments`，而不是自己判断 `has_named_tools`。
3. 新能力上线时，只要更新 capability 层与对应 contract，不必同步修改多个 solver 分支。
4. `tool_functions` 与 `dynamic_tool_specs` 的产出顺序应稳定，便于测试断言和后续审计。

---

## 9. 模块设计与落点

### 9.1 新增模块

建议新增目录：

```text
backend/capabilities/
    __init__.py
    assembler.py
    challenge_profile.py
    contracts.py
    packs.py
    runtime_profile.py
    specs.py
```

各模块职责如下：

- `challenge_profile.py`
  - 题目画像提炼

- `runtime_profile.py`
  - runtime 能力暴露方式描述

- `specs.py`
  - `CapabilitySpec`、`ResolvedCapabilities` 等数据模型

- `packs.py`
  - pack 定义与选取规则

- `contracts.py`
  - capability 到 tool exposure / prompt fragments 的映射

- `assembler.py`
  - 输入 `ChallengeProfile + RuntimeProfile`
  - 输出 `ResolvedCapabilities`

### 9.2 现有模块迁移点

#### `backend/agents/solver.py`

当前问题：

- `_build_toolset()` 直接拼工具函数
- solver 自己知道 `view_image` 是否可用

Phase 1 调整：

- 删除平铺工具装配职责
- 改为构建 `RuntimeProfile` 并调用 assembler
- 使用 `ResolvedCapabilities.tool_functions` 生成 `FunctionToolset`

#### `backend/agents/codex_solver.py`

当前问题：

- `SANDBOX_TOOLS` 是硬编码动态工具列表
- prompt 通过 `has_named_tools=True` 走 named-tool 语义

Phase 1 调整：

- `SANDBOX_TOOLS` 改为由 `ResolvedCapabilities.dynamic_tool_specs` 派生
- `baseInstructions` 中的工具说明由 capability summary 生成

#### `backend/agents/claude_solver.py`

当前问题：

- bash-only 语义主要靠 `sandbox_preamble + build_prompt(..., has_named_tools=False)` 表达
- runtime 差异主要存在于 prompt 文案

Phase 1 调整：

- 明确使用 bash-only 的 `RuntimeProfile`
- 通过 assembler 产出 bash-only prompt fragments
- 移除 `has_named_tools=False` 这种业务布尔分叉

#### `backend/prompts.py`

当前问题：

- `build_prompt()` 同时承担任务描述与运行时能力适配
- `has_named_tools` 成为核心分叉控制项

Phase 1 调整：

- `build_prompt()` 接收 `ResolvedCapabilities` 或 `prompt_fragments`
- 任务描述保留在 prompt builder
- runtime 能力分叉迁出到 capability contract 层

---

## 10. 运行时映射示例

### 10.1 图片分析能力

能力语义：

- `vision.inspect_image`

在不同 runtime 下的映射：

1. 主 `solver` named-tools runtime
   - 暴露 `view_image`
   - prompt 片段强调“先调用 `view_image`”

2. `codex_solver` dynamic-tools runtime
   - 暴露动态工具 `view_image`
   - prompt 片段强调“先使用 image inspection tool”

3. `claude_solver` bash-only runtime
   - 不暴露 named tool
   - prompt 片段改为“使用 `exiftool` / `steghide` / `strings` / `xxd` via bash”

### 10.2 flag 提交能力

能力语义：

- `flag.submit`

在不同 runtime 下的映射：

1. 主 `solver`
   - 暴露 `submit_flag` 工具

2. `codex_solver`
   - 暴露动态工具 `submit_flag`

3. `claude_solver`
   - 通过 bash 命令 `submit_flag '<flag>'` 表达
   - 实际由 hook 拦截并调用内部提交逻辑

### 10.3 Web OOB 能力

能力语义：

- `network.webhook_oob`

在不同 runtime 下的映射：

1. named-tools / dynamic-tools runtime
   - 暴露 `webhook_create`
   - 暴露 `webhook_get_requests`

2. bash-only runtime
   - prompt 片段只描述使用 webhook.site/curl 的方式

---

## 11. Phase 1 迁移范围

### 11.1 本阶段做什么

1. 新增 capability 装配层。
2. 把 solver、codex_solver、claude_solver 的能力入口统一。
3. 把 prompt 的运行时能力分叉迁出。
4. 用最小迁移替换现有平铺工具装配方式。

### 11.2 本阶段不做什么

1. 不改变 solver 主执行循环。
2. 不改变 tool tracing、loop detection、cost tracking 等现有执行机制。
3. 不改变 coordinator policy 决策逻辑。
4. 不尝试让 capability 与 strategy 直接联动。
5. 不引入新 provider。

---

## 12. 落地顺序

建议按以下顺序推进：

### 第 1 步：引入纯数据模型与 assembler

先新增：

- `ChallengeProfile`
- `RuntimeProfile`
- `CapabilitySpec`
- `CapabilityPack`
- `ToolContract`
- `ResolvedCapabilities`
- `CapabilityAssembler`

此时先不改 solver，只补单元测试。

### 第 2 步：迁移 prompt 组装链路

- 让 `build_prompt()` 支持消费 capability fragments
- 保持现有提示语义基本不变
- 移除 `has_named_tools` 在 prompt 里的主控制职责

### 第 3 步：迁移主 `solver.py`

- 用 assembler 产出的 `tool_functions` 替代 `_build_toolset()` 内硬编码列表
- `use_vision` 的行为改为由 capability 装配结果决定

### 第 4 步：迁移 `codex_solver.py`

- 动态工具列表从 assembler 结果派生
- prompt 能力说明来自 capability summary / fragments

### 第 5 步：迁移 `claude_solver.py`

- bash-only runtime 显式化
- 将 `has_named_tools=False` 迁移为 bash-only contract 片段

### 第 6 步：清理遗留逻辑

- 删除重复 prompt 分叉
- 删除不再需要的工具暴露硬编码
- 收敛命名与测试

---

## 13. 测试策略

Phase 1 以单元测试为主，最小集成测试为辅。

### 13.1 单元测试

建议覆盖：

1. `ChallengeProfile` 提炼
   - 有图片附件时能正确识别 `has_images`
   - 有 `connection_info` 时能正确识别连接类型
   - reverse/web/crypto 等题型能导出合理需求

2. `RuntimeProfile`
   - named-tools runtime
   - dynamic-tools runtime
   - bash-only runtime
   - vision on/off

3. `CapabilityPack` 选择
   - web 题包含 `network.web_fetch`
   - 图片题包含 `vision.inspect_image`
   - reverse 题包含 `binary.analysis`

4. `ToolContractAssembler`
   - 不同 runtime 下 tool exposure 正确
   - prompt fragments 正确
   - `capability_summary` 稳定可断言

5. prompt 回归
   - 删除 `has_named_tools` 后，关键提示语仍能正确出现

### 13.2 最小集成测试

建议只做两类：

1. named-tools / dynamic-tools 场景
   - 断言最终工具列表和 prompt capability fragments 符合预期

2. bash-only 场景
   - 断言不会暴露 named tools
   - 断言 prompt 正确转为 bash 指引

第一阶段不要求昂贵的长跑实战回归。

---

## 14. 回滚策略

这次要做成“装配链路可回滚”，而不是一次性大替换。

建议方式：

1. 先引入 capability assembler，再逐步替换调用方。
2. 在迁移初期，允许旧逻辑保留短暂对照期。
3. 不同时重写 tools、solver loop、prompt 三大块。

回滚点应该明确：

1. 如果 capability 装配结果有问题，只需回滚 assembler 接入。
2. 如果 prompt fragments 有问题，只需回滚 prompt 组装迁移。
3. 工具实现本身保持不动，因此不会牵动 sandbox/tool tracing 等稳定链路。

---

## 15. 验收标准

### 15.1 架构验收

1. `has_named_tools` 不再是核心控制面。
2. capability 成为显式模型，runtime 差异通过 contract 表达。
3. solver 只消费装配结果，而不是自己判断 provider/tool 差异。

### 15.2 代码验收

1. 新增 `backend/capabilities/` 目录及其数据模型、pack、contract、assembler。
2. `solver.py` 的工具装配复杂度下降。
3. `prompts.py` 不再直接编码 runtime 分叉语义。
4. `codex_solver.py`、`claude_solver.py`、主 `solver.py` 至少共享同一套能力描述入口。
5. `build_prompt()` 不再要求以 `has_named_tools` 作为主装配参数。

### 15.3 行为验收

1. 现有 named-tools 场景不退化。
2. bash-only 场景不退化。
3. 图片分析、webhook、flag 提交等关键能力仍能正确出现在对应 runtime 下。
4. 现有测试通过，并新增 capability 层测试。

### 15.4 维护性验收

1. 新增一种能力时，改动集中在 capability 层。
2. 新增一种 runtime 时，主要通过 `RuntimeProfile + ToolContract` 扩展，而不是复制 solver 逻辑。

---

## 16. 与后续路线的关系

完成本阶段后，下一步的优先级建议为：

1. `Runtime / Control State Decomposition`
2. `Capability 使用反馈 -> Strategy / Policy` 的轻度闭环
3. 更高阶的 planner / 递归 orchestrator / 产品叙事包装

原因是：

- 当前控制面第一阶段已经补上；
- 执行面能力边界补齐后，runtime 拆分才有稳定抓手；
- 如果在能力层尚未显式化前继续推进更强 planner，会把复杂度继续堆到隐式执行逻辑上。

---

## 17. 结论

策略层第一阶段完成之后，HuntingBlade 当前最应该推进的不是“更炫的 planner 名词”，而是先把执行面的能力抽象收口。

`Capability Packs / Tool Contracts Phase 1` 的价值在于：

1. 让 solver 能力成为显式对象，而不是平铺工具集合。
2. 让 runtime/provider 差异收敛到 contract 层，而不是继续散落在业务代码与 prompt 里。
3. 为后续稳定性重构和更高阶策略演进提供统一执行平面。

这一步不追求一次性做大，而是用最小闭环把“能力语义”正式立起来。  
这是当前阶段最稳、也最有后续放大价值的演进方向。

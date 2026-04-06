# HuntingBlade 自动收尾、环境释放与 Writeup 输出设计

**日期**：2026-04-06  
**项目**：HuntingBlade  
**目标**：为整场自动解题流程补齐三项运行期能力：

1. 全部题目解出后的可配置退出策略  
2. 环境题在平台确认解出后的自动释放  
3. 可选的统一中文 writeup 草稿输出

---

## 1. 背景

当前项目已经具备以下基础能力：

1. 支持 `claude`、`codex` 和 `none` 三种整场模式
2. 支持凌虚赛事 CTF 接入、自动拉题、自动起 swarm
3. 支持环境题自动预热与连接信息刷新
4. 支持按题目目录运行单题模式
5. 已经为每个 solver 生成结构化 trace 日志

但在实际跑整场时暴露出三个明显的缺口：

1. **所有题目都已经解出后，主循环不会主动退出**
   - 现在的行为是持续等待新事件，适合“随时可能上新题”的赛场
   - 但如果用户只是想把当前题单跑完，这种无限等待会让任务显得没有结束

2. **环境题提交正确后没有及时释放环境**
   - 已解题目的 swarm 会自动停掉
   - 但平台侧环境仍可能继续占用名额和资源
   - 这在凌虚这类存在环境限制的平台上会直接影响后续使用体验

3. **解出后没有统一的题解产物**
   - 当前系统只有结果摘要、控制台输出和 trace JSONL
   - 用户需要自己从 metadata、trace、solver 总结里手动拼 writeup
   - 对批量复盘、沉淀知识库和赛后整理都不友好

因此，本次设计要把“整场求解”的生命周期补完整，让它从“会跑”升级到“会收尾、会清场、会产出”。

---

## 2. 设计目标

本次设计目标如下：

1. 为整场模式新增“全部已解后退出”的显式策略，避免只能依赖 `Ctrl+C`
2. 对需要环境的题目，在**平台确认提交成功后**自动释放环境
3. 提供统一的中文 Markdown writeup 草稿输出，支持独立目录归档
4. 三种整场模式 `claude` / `codex` / `none` 共享同一套生命周期行为
5. 优先复用现有结果、trace、metadata 和平台客户端，不引入无必要的大重构
6. README 中补齐这三项能力的最新使用说明

---

## 3. 非目标

本次设计明确不做以下事项：

1. 不改变 solver 的核心解题策略
2. 不引入新的大模型专门负责生成 writeup
3. 不修改现有单题模式的核心运行方式
4. 不把“环境释放”扩展成复杂的环境编排系统
5. 不顺带重构整套结果存储为完整数据库或 run session 系统
6. 不在 `--no-submit` 下自动释放环境

---

## 4. 用户确认的约束

本次方案按以下已确认偏好收口：

1. **全解后的退出策略要同时支持两种模式**
   - 立即退出
   - 空闲一段时间后退出

2. **环境释放只在平台确认提交正确后触发**
   - 不因为 solver 自己“认为解出”而释放
   - 不因为 `--no-submit` 而释放

3. **writeup 生成时机要同时支持两种模式**
   - 平台确认提交成功后生成
   - 即使 `--no-submit`，只要本次求解得出有效结果，也允许生成

4. **writeup 产物要是完整中文草稿**
   - 不只是几行摘要
   - 至少包含题目信息、环境/附件、思路、关键步骤、结果状态

---

## 5. 方案选择

### 方案 A：分别在各模块里打补丁

做法：

- 在 `coordinator_loop` 里硬塞退出条件
- 在 Lingxu client 里直接追加 `release`
- 在 swarm 完成后临时拼一个 Markdown 文件

优点：

- 改动快
- 表面上能满足需求

缺点：

- 结果状态、平台动作、产物生成会继续散落在多个模块
- 后续新增别的平台或别的输出产物时会迅速失控
- 测试边界不清晰

### 方案 B：补齐运行期能力边界

做法：

- 主循环负责退出策略
- 平台协议负责环境释放能力
- 结果对象负责记录 solve / submit / cleanup 状态
- 独立 writeup 模块负责产物生成

优点：

- 结构清晰，能与现有 `none` 模式和共享 event loop 自然结合
- 便于未来给更多平台复用
- 测试可以按职责拆开

缺点：

- 比方案 A 多一层结果与接口整理

### 方案 C：引入完整的 run session 编排层

做法：

- 为每次整场运行创建独立 session 目录和状态模型
- 所有 solve、cleanup、writeup、summary 都围绕 session 组织

优点：

- 长期演进空间最好

缺点：

- 这次需求会被做大
- 实现与验证成本明显超出当前目标

**选型**：采用方案 B。  
原因：它在不扩大需求范围的前提下，把退出、释放、产出三件事都落到稳定边界上，适合当前代码结构，也最利于后续平台扩展。

---

## 6. 核心设计

### 6.1 全解后的退出策略

退出策略新增为整场模式的显式 CLI 配置：

- `--all-solved-policy wait|exit|idle`
- `--all-solved-idle-seconds N`

默认建议：

- `--all-solved-policy wait`
- `--all-solved-idle-seconds 300`

三种策略语义如下：

1. `wait`
   - 保持现状
   - 全部题目解出后继续等待新题或新事件

2. `exit`
   - 当以下条件同时成立时立即退出主循环：
     - `known_challenges == known_solved`
     - `active_swarms == 0`

3. `idle`
   - 当全部已解且无活跃 swarm 时进入“空闲观察期”
   - 若 `N` 秒内没有出现新题、没有重新起 swarm，则退出

空闲计时器的重置条件：

1. 出现新题
2. 新起一个 swarm
3. 已知题目集合发生变化导致“不再是全部已解”

实现位置：

- 统一放在共享主循环 [coordinator_loop.py](/Users/d1a0y1bb/Desktop/HuntingBlade/backend/agents/coordinator_loop.py)

这样 `claude`、`codex`、`none` 三种整场模式都继承相同行为，不再需要每个 coordinator 自己重复实现。

### 6.2 环境释放能力

环境释放不应由 solver 自己决定，而应作为平台能力，由“确认提交成功后的统一收尾路径”触发。

平台协议扩展一项新能力：

- `release_challenge_env(challenge_ref: Any) -> None`

协议语义：

1. 仅处理平台侧环境释放
2. 对不支持环境的题目或平台可直接 no-op
3. 调用失败不影响题目 solve 成功结果，只记录告警

平台实现：

1. `ctfd`
   - no-op

2. `lingxu-event-ctf`
   - 调用：
     - `POST /event/{event_id}/ctf/{challenge_id}/release/`
   - 该接口在凌虚前端源码和后端路由中都已存在
   - 参考：
     - 前端调用 [ctfDetail.js](/Users/d1a0y1bb/Documents/未整理资源集散中心/凌虚-网络安全竞赛平台/凌虚竞赛平台/system/project/web_competition/src/js/ScoreCenter/eventDetails/Topic/Ctf/ctfDetail.js#L142)
     - 后端路由 [urls.py](/Users/d1a0y1bb/Documents/未整理资源集散中心/凌虚-网络安全竞赛平台/凌虚竞赛平台/system/project/event_app/urls.py#L209)
     - 后端实现 [env.py](/Users/d1a0y1bb/Documents/未整理资源集散中心/凌虚-网络安全竞赛平台/凌虚竞赛平台/system/project/event_app/views/env.py#L117)

触发条件严格限定为：

1. 本题 `requires_env_start == true`
2. 本次提交结果为：
   - `correct`
   - `already_solved`
3. 本次运行不是 `--no-submit`

不触发释放的场景：

1. solver 只是在本地推断拿到了 flag
2. `--no-submit`
3. 提交失败或状态不明确
4. 平台题目本身不需要环境

为了避免重复释放，同一 challenge 在本次运行内应做一次性去重。

### 6.3 结果状态模型扩展

当前 `deps.results` 只记录较薄的一层：

- `flag`
- `submit`

本次需要把它扩展为更适合运行期收尾与产物输出的结构，至少包含：

- `flag`
- `solve_status`
- `submit_status`
- `submit_display`
- `confirmed`
- `winner_model`
- `findings_summary`
- `log_path`
- `writeup_path`
- `env_cleanup_status`
- `env_cleanup_error`

设计原则：

1. 不要求这次引入复杂的 dataclass 持久化模型
2. 但至少要把结果字段统一起来，避免 writeup 模块再去反查多个运行时对象
3. 单题模式和整场模式都应尽量共享同一份结果语义

### 6.4 Writeup 输出能力

writeup 采用**模板化中文 Markdown 草稿生成**，本次不新增额外 LLM 调用。

理由：

1. 稳定
2. 成本低
3. 易测试
4. 现有 metadata、winner、trace 已经足够支持第一版高质量草稿

CLI 设计：

- `--writeup-mode off|confirmed|solved`
- `--writeup-dir PATH`

语义如下：

1. `off`
   - 默认关闭，不生成任何题解文件

2. `confirmed`
   - 仅在平台确认提交成功后生成

3. `solved`
   - 只要本次求解得到有效解题结果就生成
   - 即使当前是 `--no-submit` 也允许输出草稿

默认目录建议：

- `writeups/<platform>-<event-id-or-local>/`

例如：

- `writeups/lingxu-event-ctf-198/echo.md`
- `writeups/ctfd-local/example-challenge.md`

文件命名规则：

1. 使用 challenge slug
2. 保证同目录下稳定可覆盖
3. 不把模型名拼进文件名，避免一题多稿造成混乱

### 6.5 Writeup 内容结构

每个 Markdown 草稿采用统一中文模板，至少包含以下章节：

1. 题目基本信息
   - 题目名
   - 分类
   - 分值
   - 平台
   - 赛事 ID / 平台题目 ID

2. 附件与环境信息
   - 本地题目目录
   - 附件目录
   - connection info
   - 是否需要启动环境

3. 最终结果
   - 是否确认解出
   - flag
   - 提交结果
   - 是否执行了环境释放

4. 解题思路摘要
   - 来自 `winner.findings_summary`

5. 关键步骤与命令
   - 从 trace 中抽取最后若干条关键 `tool_call` / `tool_result`

6. 关键证据
   - 例如样本文件、参数、利用点、数学突破口、关键输出

7. 复现备注
   - 若为 `--no-submit`，明确写出“未自动提交，需人工确认”
   - 若环境释放失败，明确写出“平台环境可能仍处于占用状态”

### 6.6 Writeup 数据来源

writeup 模块优先复用已有数据，不自行猜测：

1. 题目信息来自：
   - `metadata.yml`

2. 最终结果来自：
   - `SolverResult`
   - `deps.results`

3. 思路摘要来自：
   - `winner.findings_summary`

4. 执行轨迹来自：
   - `winner.log_path`
   - trace JSONL

trace 的抽取策略保持保守：

1. 只摘取最近若干条关键事件
2. 不照搬整份 trace
3. 以“便于人工接着复盘”为目标，而不是完整流水账

### 6.7 单题模式与整场模式的对齐

本次能力主要面向整场模式，但 writeup 输出不应只服务于 coordinator。

因此建议：

1. 单题模式也复用同一 writeup 生成器
2. 单题模式可以后续再暴露相同或简化版 CLI 选项
3. 本次实现优先保证整场模式闭环，不强求把单题 CLI 一次改满

---

## 7. 错误处理策略

### 7.1 退出策略

1. `idle` 模式下如果 `--all-solved-idle-seconds <= 0`，CLI 直接报错
2. 主循环退出应被视作正常完成，而不是异常

### 7.2 环境释放

1. 释放失败只记录 warning
2. 不回滚已确认的 solve 结果
3. 最终 summary 和 writeup 中都要能看到失败状态

### 7.3 Writeup 生成

1. writeup 生成失败不影响主流程返回成功
2. 但要在结果中记录失败原因
3. 控制台 summary 需要提示“题解未成功写出”

---

## 8. 测试要求

### 8.1 主循环退出测试

新增测试覆盖：

1. `wait` 模式下全解后不退出
2. `exit` 模式下在“全部已解且无活跃 swarm”时退出
3. `idle` 模式下在空闲超时后退出
4. `idle` 模式下新题出现会重置空闲计时

### 8.2 平台释放测试

新增测试覆盖：

1. Lingxu 平台在确认提交成功后调用 `release`
2. `--no-submit` 下不会调用 `release`
3. 非环境题不会调用 `release`
4. `release` 失败只记状态，不破坏 solve 成功

### 8.3 Writeup 测试

新增测试覆盖：

1. `writeup-mode=off` 不生成文件
2. `writeup-mode=confirmed` 只有确认提交后才生成
3. `writeup-mode=solved` 在 dry-run 下也能生成
4. 输出目录、文件名和中文章节结构正确
5. `--no-submit` 产物中包含“未自动提交”提示

### 8.4 CLI 测试

新增或更新 CLI 测试覆盖：

1. 新选项在 `--help` 中可见
2. 帮助文本为中文
3. 选项组合能正确进入配置对象

---

## 9. README 更新要求

README 需要新增专门章节，至少包含：

1. 全解后的退出策略说明
2. 环境题自动释放规则
3. writeup 自动输出的命令示例
4. `--coordinator none` 与上述能力的组合示例
5. 明确说明：
   - `--no-submit` 不会自动释放环境
   - `--writeup-mode solved` 可用于 dry-run 赛后整理

建议给出至少三条中文示例命令：

1. 全解后立即退出
2. 全解后空闲 5 分钟退出
3. dry-run + 生成 writeup 草稿

---

## 10. 验收标准

满足以下条件即可验收：

1. 整场模式支持 `wait`、`exit`、`idle` 三种全解后策略
2. `claude`、`codex`、`none` 三种模式行为一致
3. Lingxu 环境题在平台确认提交正确后会自动释放环境
4. `--no-submit` 下不会自动释放环境
5. 支持把已解题目输出为统一目录下的中文 Markdown writeup 草稿
6. `confirmed` 与 `solved` 两种 writeup 生成时机都可配置
7. 相关测试通过，README 补齐最新用法

---

## 11. 实施边界总结

本次设计不是去“重写整场架构”，而是补齐以下三条最关键的运行期闭环：

1. **会结束**：全部已解后不再只能无限等待  
2. **会清场**：确认解出后及时释放平台环境  
3. **会留档**：统一产出中文 writeup 草稿

这三件事完成后，HuntingBlade 的整场自动解题流程会从“求解器集合”升级成一条更完整的“比赛运行流水线”。

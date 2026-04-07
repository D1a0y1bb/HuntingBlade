# HuntingBlade Azure Responses Solver 与 `.env` API 总控设计

**日期**：2026-04-07  
**项目**：HuntingBlade  
**目标**：把现有 `azure/...` solver 从 Chat Completions 升级到 Responses API，并新增一个只依赖 `.env` 的 `--coordinator azure` 总控后端，避免整场模式再依赖本机 Codex/Claude 配置。

---

## 1. 背景

当前项目里，API 型 solver 的 `azure/...` provider 仍然走的是 Pydantic AI 的 `OpenAIModel`，也就是 Chat Completions 路径。实际运行日志已经证明这一点：

- 请求地址落在 `POST /v1/chat/completions`
- solver 在第 0 步就触发 `Exceeded maximum retries (1) for output validation`
- `Broken (0 steps, $0)` 说明模型还没真正进入有效的工具调用回合

与此同时，用户已经确认：

1. 本机 Codex 总控正常，不代表 `.env` 里的 Azure 通道正常，因为两者不是同一条网关配置。
2. 用户的目标不是继续依赖本机 Codex 配置兜底，而是“只走 `.env` 里的 Azure 那条通道”。
3. 希望一次性做好，而不是继续维持“solver 走 API，coordinator 走本机工具”的混合状态。

因此，本次改动不能只修文案或只改默认参数，而要同时解决两个问题：

1. `azure/...` solver 必须改走 Responses API。
2. 整场模式必须新增一个 `.env only` 的 API 总控实现。

---

## 2. 设计目标

1. 保留现有 `azure/...` 规格，不新增新的 provider 前缀，让用户现有命令尽量不变。
2. `azure/...` 对应的 Pydantic AI model 切到 `OpenAIResponsesModel`。
3. 新增 `--coordinator azure`，该总控只使用 `.env` 中的 Azure 配置，不读取本机 Codex/Claude 配置。
4. 总控继续复用现有 `coordinator_loop` / `coordinator_core` / `poller` / `ChallengeSwarm`，不复制第二套赛事循环。
5. CLI、README、测试一起更新，让 `.env only` 路径成为可验证、可发现、可维护的正式能力。

---

## 3. 非目标

1. 不移除现有 `claude` / `codex` / `none` 协调器。
2. 不引入新的 provider 名称，例如 `azure-responses/...`。
3. 不重写 solver 的整体 prompt、tool 集合或 swarm 生命周期。
4. 不把所有 OpenAI-compatible provider 都强制切到 Responses；本次范围只覆盖用户明确指定的 `azure/...`。

---

## 4. 方案比较

### 方案 A：把现有 `azure/...` 直接升级为 Responses，并新增 `--coordinator azure`

优点：

- 用户现有命令基本不变
- 语义最符合“Azure 这条 `.env` 通道就是主 API 通道”
- solver 与 coordinator 都能走同一套 `.env` 配置

缺点：

- `azure` provider 的运行时语义从 Chat Completions 变成 Responses，属于行为升级
- 需要补测试，避免影响已有 `zen` / `google` / `bedrock`

### 方案 B：新增 `azure-responses/...`，保留原 `azure/...`

优点：

- 兼容性最保守
- 老行为完全不变

缺点：

- 用户认知成本高
- 需要同时维护两套 provider 语义
- 不符合用户“不要绕，直接适配现有 Azure 通道”的要求

**选型**：采用方案 A。  
原因：用户已经明确批准按 A 设计并落地，且目标是 `.env only` 正式通路，不是继续保留历史兼容壳层。

---

## 5. 核心设计

### 5.1 `azure/...` solver 改走 Responses API

`backend/models.py` 中：

- `azure` provider 的 model 实现从 `OpenAIModel` 改为 `OpenAIResponsesModel`
- `azure` provider 的 settings 从 `OpenAIModelSettings` 改为 `OpenAIResponsesModelSettings`

默认设置采取稳妥策略：

- `max_tokens=128_000`
- `openai_reasoning_effort='medium'`
- `openai_reasoning_summary='auto'`
- `openai_truncation='auto'`

这样做的目的：

1. 明确走 Responses API，而不是继续发 `/chat/completions`
2. 对 GPT-5.4 / GPT-5.4-mini 这类 reasoning 模型使用更符合 Responses 语义的参数
3. 避免启用部分网关不兼容的 `previous_response_id` 续聊写法，优先保证兼容性

### 5.2 `zen/...` 先维持原状

虽然 `zen` 也是 OpenAI-compatible provider，但本次不是用户需求重点，也没有现成失败证据。

因此本次只把 `azure` 切到 Responses，`zen` 暂时继续保留现状，避免把“修 Azure 通道”扩大成“整体 provider 重构”。

后续如果需要，可再以独立需求把 `zen` 迁移到 Responses。

### 5.3 新增 `--coordinator azure`

CLI 中把 `--coordinator` 的可选值从：

- `claude`
- `codex`
- `none`

扩展为：

- `claude`
- `codex`
- `azure`
- `none`

语义定义：

- `claude`：本机 Claude SDK 总控
- `codex`：本机 Codex App Server 总控
- `none`：无总控整场模式
- `azure`：Pydantic AI API 总控，只吃 `.env` 里的 Azure 配置

### 5.4 Azure 总控的实现边界

新增模块：`backend/agents/azure_coordinator.py`

实现方式：

1. 复用 `build_deps()` 获取 `CoordinatorDeps`
2. 用 Pydantic AI `Agent` 构建一个轻量 coordinator agent
3. 通过一组工具函数调用 `coordinator_core`：
   - `fetch_challenges`
   - `get_solve_status`
   - `spawn_swarm`
   - `check_swarm_status`
   - `submit_flag`
   - `kill_swarm`
   - `bump_agent`
   - `broadcast`
   - `read_solver_trace`
4. 在 `run_event_loop()` 里把事件消息持续喂给该 agent

这个 coordinator 不依赖：

- `codex app-server`
- Claude SDK
- 本机 Codex 全局配置文件

它只依赖：

- `.env` 中的 `AZURE_OPENAI_ENDPOINT`
- `.env` 中的 `AZURE_OPENAI_API_KEY`

### 5.5 `--coordinator-model` 的 Azure 归一化

为兼容现有 CLI 使用习惯，Azure 总控允许两种写法：

- `--coordinator-model gpt-5.4`
- `--coordinator-model azure/gpt-5.4`

归一化规则：

1. 未传时默认使用 `azure/gpt-5.4`
2. 传裸模型名时自动补成 `azure/<model>`
3. 传完整 spec 时必须以 `azure/` 开头，否则报错

这样可以保证 `--coordinator azure` 始终走 Azure 通道，而不是悄悄落到别的 provider。

### 5.6 Azure 总控的输出策略

协调器不是“必须产出结构化最终对象”的 agent，它的核心职责是：

1. 收事件
2. 调工具
3. 给出文本回合收尾

因此 Azure 总控不使用严格的 `output_type=FlagFound` 这一类结构化终态，而是让 agent 的最终输出保持普通文本，避免把 solver 上的严格 output validation 问题复制到 coordinator。

换句话说：

- solver 仍保留原有结构化终态，因为它需要明确 flag 产出
- coordinator 只要能稳定完成工具调用即可，不要求额外结构化对象

### 5.7 事件循环与状态复用

Azure 总控不会新建赛事循环，而是继续复用：

- `backend/agents/coordinator_loop.py`
- `backend/agents/coordinator_core.py`

因此以下行为保持一致：

1. 启动前校验平台访问
2. poller 定时拉题与同步已解状态
3. 初始自动为未解题起 swarm
4. 新题出现时自动 materialize 并起 swarm
5. 平台判定已解后自动停掉 swarm
6. 保留 `ctf-msg` 的 operator message HTTP 入口

---

## 6. 兼容性与风险

### 6.1 兼容性收益

1. 用户现有 `--models azure/gpt-5.4 --models azure/gpt-5.4-mini` 不需要改写。
2. `.env` 路径从 solver 到 coordinator 完整打通。
3. 不再要求本机存在 `codex` 或 Claude SDK 才能使用“带总控”的整场模式。

### 6.2 主要风险

1. 某些网关虽然声明支持 Responses，但对 `previous_response_id`、reasoning 参数或 tool calling 兼容不完整。
2. `azure/...` 语义升级后，可能影响现有依赖 Chat Completions 行为的隐含假设。
3. 新 coordinator 如果把事件消息历史无限累积，可能导致上下文膨胀。

### 6.3 风险控制

1. 先用测试锁定 `resolve_model()` / `resolve_model_settings()` 的 provider 类型与关键参数。
2. Azure 总控复用现有工具面，避免引入新的协调器指令协议。
3. coordinator 使用普通文本输出而非严格结构化输出，降低网关兼容风险。
4. 默认不启用 `openai_previous_response_id`，避免在兼容性不足的网关上触发二次请求 400。

---

## 7. 测试策略

### 7.1 单元测试

新增或扩展测试，覆盖：

1. `azure/...` 返回 `OpenAIResponsesModel`
2. `resolve_model_settings("azure/...")` 返回 `OpenAIResponsesModelSettings`，并包含关键 Responses 参数
3. CLI `--help` 中出现 `azure` coordinator
4. `_run_coordinator()` 在 `azure` 模式下进入新的 Azure coordinator 分支
5. `run_azure_coordinator()` 复用共享事件循环
6. Azure 总控的模型归一化规则正确

### 7.2 回归测试

至少运行：

- `uv run pytest -q`
- `uv run ctf-solve --help`

必要时再做定向 smoke：

- 确认 `azure/...` 不再发 `/chat/completions`

---

## 8. 验收标准

满足以下条件即可验收：

1. `azure/...` solver 运行时解析为 Responses model，而不是 Chat Completions model。
2. `ctf-solve --coordinator azure ...` 可以在没有本机 Codex/Claude 的情况下启动整场协调器。
3. Azure 总控只依赖 `.env` 中的 Azure 配置。
4. 现有 `claude` / `codex` / `none` 协调模式不回归。
5. README 能明确说明 `.env only` 的 Azure solver + Azure coordinator 使用方式。

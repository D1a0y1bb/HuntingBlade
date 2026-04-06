# 凌虚赛事 CTF 接入设计

**日期**：2026-04-06  
**项目**：HuntingBlade（CTF Agent Fork）  
**目标**：在不破坏现有 CTFd 工作流的前提下，为 HuntingBlade 增加“凌虚竞赛平台赛事 CTF”接入能力，使协调器能够从凌虚平台拉取赛事 CTF 题目、准备解题材料、对环境型题目取地址，并向平台提交 flag。

---

## 1. 背景

HuntingBlade 当前的竞赛平台接入实现高度依赖 CTFd：

- 平台客户端集中在 [backend/ctfd.py](../../../backend/ctfd.py)
- 轮询逻辑在 [backend/poller.py](../../../backend/poller.py)
- 协调器在 [backend/agents/coordinator_core.py](../../../backend/agents/coordinator_core.py) 中调用平台客户端拉题、判定已解题和提交 flag

现有实现假设平台具有下列特征：

- 统一的 HTTP API
- 可通过 token 或 CTFd 风格登录态访问
- 题目列表与题目详情结构接近 CTFd
- 附件可直接下载
- 已解状态可通过单独接口查询
- 提交 flag 时使用“题目名 -> 题目 ID”映射

凌虚竞赛平台的“赛事 CTF”链路与上述假设明显不同：

- 登录方式为 Django session + CSRF，而不是纯 token
- 赛事入口为 `/event/<event_id>/ctf/...`
- 题目包含环境型、外链型、附件型三种题目类型
- 题目包含 `FLAG` 模式和 `check` 模式两种答题模式
- 环境型题目通常需要先 `run`，再通过 `addr` 获取连接信息
- 题目状态和用户可见性受赛事报名、审核、战队状态等权限控制

如果直接在现有 `CTFdClient` 中加入大量凌虚平台分支，会导致：

- 平台逻辑高度耦合
- 登录/认证流程混杂
- 题目拉取和环境准备语义变得模糊
- 后续扩展 `train`、`AWD`、`CFS` 时成本继续上升

因此，本设计采用“最小平台适配层 + 独立凌虚客户端实现”的方案，但只接入 **凌虚赛事 CTF** 这一条业务线，不做大规模多平台框架化重构。

---

## 2. 设计目标

本功能的设计目标如下：

1. 保留现有 CTFd 工作流不变，继续支持当前 `ctf-solve` 对 CTFd 平台的运行方式。
2. 新增“凌虚赛事 CTF”接入能力，使协调器可以直接以平台为题目来源运行。
3. 把平台差异收敛在平台客户端实现中，不让 solver、swarm、prompt 层直接依赖凌虚平台细节。
4. 对环境型题目增加“解题前准备（preflight）”能力，在 solver 启动前拿到真实连接地址。
5. 本地落地结构保持与现有系统兼容，仍使用 `metadata.yml + distfiles/` 作为 solver 输入。
6. 在 v1 中明确限制不支持项，避免实现阶段引入隐含复杂度。

---

## 3. 非目标

本设计明确不覆盖以下内容：

- 不支持凌虚平台的 `train` 作训 CTF
- 不支持 `AWD`
- 不支持 `CFS`
- 不支持一次运行同时连接多个赛事
- 不支持自动完成验证码登录
- 不支持自动从账号密码换取 session
- 不支持 `check` 模式题目的自动求解
- 不支持对凌虚平台做通用插件系统抽象
- 不处理凌虚平台后台管理接口

---

## 4. 范围定义（V1）

### 4.1 支持范围

V1 只支持 **凌虚平台赛事 CTF** 的下列子集：

- 赛事入口：`/event/<event_id>/ctf/...`
- 题目类型：
  - 环境型
  - 外链型
  - 附件型
- 答题模式：
  - `FLAG` 模式

### 4.2 不支持范围

V1 对下列情况只识别、不求解：

- `answer_mode = 2` 的 `check` 模式题

处理策略为：

- 题目在平台列表中仍可被识别
- 本地 metadata 中标记为 unsupported
- 协调器不为其创建 swarm
- 日志中明确说明“因 check 模式被跳过”

---

## 5. 用户使用方式

V1 的使用方式以“已有有效浏览器登录态”为前提。

用户流程如下：

1. 用户先在浏览器中登录凌虚平台并进入目标赛事。
2. 用户从浏览器导出当前站点 Cookie，至少包含：
   - `sessionid`
   - `csrftoken`
3. 用户通过 CLI 指定：
   - 平台类型
   - 平台根地址
   - 赛事 ID
   - Cookie 文件路径
4. 程序启动时校验 Cookie 是否有效、用户是否有赛事访问权限。
5. 校验通过后，协调器开始拉取赛事 CTF 题目并调度求解。

推荐 CLI 形式如下：

```bash
uv run ctf-solve \
  --platform lingxu-event-ctf \
  --platform-url https://match.example.com \
  --lingxu-event-id 42 \
  --lingxu-cookie-file .secrets/lingxu.cookie \
  --max-challenges 10 \
  --no-submit \
  -v
```

---

## 6. 总体架构

### 6.1 设计原则

本次设计遵循以下原则：

- 上层协调器只依赖“平台能力契约”，不依赖具体平台协议
- CTFd 与凌虚平台分别实现，不互相污染
- 题目落地格式继续使用已有 `metadata.yml + distfiles/`
- 需要平台特有流程的逻辑尽量前移到“拉题”或“preflight”阶段
- 对 solver 来说，输入仍然是一个标准化后的本地题目目录

### 6.2 逻辑分层

本次功能新增后的系统分层如下：

1. CLI / 配置层  
负责解析 `--platform`、`--platform-url`、`--lingxu-event-id`、`--lingxu-cookie-file` 等参数，并创建具体平台客户端。

2. 平台抽象层  
定义一个很薄的平台客户端契约，只暴露协调器真正需要的少量能力。

3. 平台实现层  
包括：
- CTFd 平台实现
- 凌虚赛事 CTF 平台实现

4. 题目落地层  
把平台返回的数据统一转换为本地题目目录结构。

5. Preflight 层  
在 swarm 启动前处理环境型题目的地址准备。

6. 协调器 / Swarm / Solver 层  
继续使用现有机制，不直接理解底层平台是 CTFd 还是凌虚。

---

## 7. 平台抽象设计

### 7.1 最小平台契约

新增一个薄接口，命名可为 `CompetitionPlatformClient`，供协调器和 poller 使用。

建议包含以下能力：

- `fetch_challenge_stubs()`
  - 返回当前赛事可见题目的轻量列表
  - 用于 poller 比较新题与已知题

- `fetch_solved_names()`
  - 返回当前用户或当前战队已解题名称集合
  - 用于 poller 比较已解状态

- `fetch_all_challenges()`
  - 返回完整题目列表或足够生成本地题目目录的数据

- `pull_challenge(challenge, output_dir)`
  - 将单道题落地为本地目录
  - 返回落地后的题目目录路径

- `submit_flag(challenge_ref, flag)`
  - 提交 flag
  - `challenge_ref` 不应再只依赖题目名，应允许使用平台题目 ID 或 metadata 中的稳定标识

- `prepare_challenge(challenge_dir)`
  - 可选预处理接口
  - 对环境型题目执行 `run -> addr` 并更新本地 metadata

- `close()`
  - 关闭底层 HTTP client

### 7.2 兼容旧实现

现有 [backend/ctfd.py](../../../backend/ctfd.py) 保留，但逐步从“唯一平台客户端”调整为“平台实现之一”。  
这样现有 CTFd 路径不需要重写上层业务逻辑，只需要被统一纳入平台抽象。

---

## 8. 凌虚赛事 CTF 平台实现设计

### 8.1 平台标识

新增平台类型：

- `lingxu-event-ctf`

该平台类型只表示“凌虚平台的赛事 CTF 前台链路”，不表示整个凌虚平台。

### 8.2 认证模型

V1 不做自动登录，而是使用用户提供的浏览器登录态。

输入形式：

- `--lingxu-cookie-file`
  - 文件内容为原始 Cookie 串
- 或 `--lingxu-cookie`
  - 命令行直接传 Cookie 串

客户端职责：

- 从 Cookie 串中解析 `csrftoken`
- 所有写操作自动带 `X-CSRFToken`
- 请求中保持 Cookie 头
- 使用 session 风格访问凌虚平台 API

V1 启动时必须做如下校验：

1. Cookie 中是否包含 `sessionid`
2. Cookie 中是否包含 `csrftoken`
3. 是否能访问目标赛事 CTF 列表接口
4. 是否已报名该赛事
5. 是否有权限访问赛事 CTF 接口

若任一失败，则启动直接中止。

### 8.3 赛事入口

只使用赛事 CTF 相关接口：

- 题目列表：`/event/<event_id>/ctf/`
- 题目详情：`/event/<event_id>/ctf/<tpk>/info/`
- 题目开启：`/event/<event_id>/ctf/<tpk>/begin/`
- 环境启动：`/event/<event_id>/ctf/<tpk>/run/`
- 环境地址：`/event/<event_id>/ctf/<tpk>/addr/`
- flag 提交：`/event/<event_id>/ctf/<tpk>/flag/`

### 8.4 题目列表语义

列表接口返回的是“赛事中的题目实例（CompetitionCTF）”，而不是题库中的原始题目。  
因此本地 metadata 必须保存两类信息：

- 展示层信息：
  - 题目名
  - 分类
  - 分值
- 平台引用信息：
  - `event_id`
  - `platform_challenge_id`（即赛事题目实例 ID）
  - `platform = lingxu-event-ctf`

后续所有提交动作必须优先使用 `platform_challenge_id`，而不是题目名。

### 8.5 已解状态语义

凌虚平台可通过题目列表字段 `is_parse` 判断当前用户或当前战队是否已解题。  
因此 `fetch_solved_names()` 的实现逻辑应为：

- 拉取 `/event/<event_id>/ctf/`
- 过滤 `is_parse = true`
- 返回对应题目名称集合

V1 中不单独设计更底层的“已解详情接口”。

---

## 9. 题目落地设计

### 9.1 目标

保持现有 solver 输入格式不变：

```text
challenges/<slug>/
├── metadata.yml
└── distfiles/
```

### 9.2 metadata 字段映射

凌虚题目详情字段应映射为以下 metadata 结构：

- `name`
  - 使用赛事题目名
- `category`
  - 使用题目分类
- `description`
  - 使用题目详情中的 `desc`
- `value`
  - 使用当前赛事中的题目分值
- `connection_info`
  - 外链型题目：使用 `link_path`
  - 环境型题目：初始可为空，在 preflight 阶段补写
  - 附件型题目：一般为空
- `tags`
  - 如果列表接口或详情接口不能稳定提供，则允许为空
- `solves`
  - 使用 `parse_count`

新增平台扩展字段：

- `platform: lingxu-event-ctf`
- `platform_url`
- `event_id`
- `platform_challenge_id`
- `test_type`
- `answer_mode`
- `requires_env_start`
- `unsupported_reason`

### 9.3 附件处理

附件型题目详情中的 `attachment` 字段会返回媒体路径。  
客户端需：

- 拼接为平台完整 URL
- 用当前登录态下载附件
- 写入 `distfiles/`

如果附件下载失败：

- 不生成完整题目目录
- 或将题目标记为 `materialization_failed`
- 协调器不为其启动 swarm

### 9.4 题目目录命名

题目目录仍使用 slug，但必须避免因重名题导致覆盖。  
推荐命名规则：

- `<slug>-<platform_challenge_id>`

例如：

- `sql-injection-137`
- `easy-rev-204`

这样可以保证：

- 同名题不会互相覆盖
- 本地目录名稳定可追踪

---

## 10. 环境型题目的 Preflight 设计

### 10.1 问题

现有系统默认题目一旦落地，本地 metadata 就已经包含足够的连接信息。  
凌虚平台的环境型题不满足这个前提，因为需要：

1. 启动环境
2. 获取环境地址
3. 把地址写入 metadata

### 10.2 设计

新增“题目 preflight”阶段，在 swarm 启动前执行：

- 如果题目是外链型：
  - 直接返回成功

- 如果题目是附件型：
  - 直接返回成功

- 如果题目是环境型：
  - 若 metadata 已有 `connection_info`，直接返回成功
  - 若 metadata 未有 `connection_info`：
    1. 调用 `begin`（如需要）
    2. 调用 `run`
    3. 调用 `addr`
    4. 将连接信息写回 `metadata.yml`
    5. 返回成功

### 10.3 失败策略

Preflight 失败时：

- 不启动 swarm
- 在日志中记录 `preflight_failed`
- 保留失败原因
- 后续协调器轮询新事件或下一次调度时允许重试

### 10.4 连接信息格式

对环境型题目，`addr` 接口返回的数据结构需要被归一化为 prompt 可直接使用的文本。  
本地 `connection_info` 应尽量转换为 solver 能直接执行的形式，例如：

- `nc host port`
- `http://host:port`
- 多端口场景下的多行文本

如果 `addr` 返回内容较复杂，则统一写入结构化补充字段，并在 `connection_info` 中写一段清晰摘要。

---

## 11. 提交流程设计

### 11.1 提交引用

现有 CTFd 逻辑使用“题目名 -> 题目 ID”的方式提交。  
凌虚平台接入后，提交必须依赖 metadata 中的：

- `event_id`
- `platform_challenge_id`

### 11.2 提交行为

提交路径：

- `/event/<event_id>/ctf/<platform_challenge_id>/flag/`

提交体：

- `{"flag": "<candidate>"}` 或与前端一致的 JSON 结构

### 11.3 返回状态归一化

凌虚平台的提交结果需要被映射到现有 `SubmitResult` 风格：

- 正确：`correct`
- 已解：`already_solved`
- 错误：`incorrect`
- 其他：`unknown`

展示文案统一为 solver 易理解的英文或中英混合摘要，避免影响现有 solver 行为。

---

## 12. CLI 与配置设计

### 12.1 新增 CLI 参数

建议新增以下参数：

- `--platform`
  - 取值：
    - `ctfd`
    - `lingxu-event-ctf`

- `--platform-url`
  - 平台根地址

- `--lingxu-event-id`
  - 凌虚赛事 ID

- `--lingxu-cookie`
  - 原始 Cookie 串

- `--lingxu-cookie-file`
  - Cookie 文件路径

### 12.2 配置优先级

优先级设计为：

1. CLI 参数
2. `.env`
3. 默认值

### 12.3 配置校验

当 `--platform lingxu-event-ctf` 时，必须校验：

- `platform_url` 存在
- `lingxu_event_id` 存在
- `lingxu_cookie` 或 `lingxu_cookie_file` 至少存在一个

否则 CLI 启动直接失败。

---

## 13. Poller 调整设计

### 13.1 当前问题

现有 [backend/poller.py](../../../backend/poller.py) 默认假设平台客户端具备 CTFd 风格能力。  
为了兼容凌虚平台，需要把 poller 调整为面向平台抽象工作。

### 13.2 调整方案

Poller 不再关心具体平台类型，只调用：

- `fetch_challenge_stubs()`
- `fetch_solved_names()`

轻量题目对象至少需要包含：

- `name`
- `id`
- 可选 `category`
- 可选 `value`

Poller 内部仍保留现有语义：

- 发现新题
- 发现新解出题
- 定时比较差异

---

## 14. 协调器集成设计

### 14.1 现有行为

协调器当前在 [backend/agents/coordinator_core.py](../../../backend/agents/coordinator_core.py) 中：

- 拉取题目
- 本地不存在则落地题目目录
- 启动 swarm

### 14.2 调整后行为

对凌虚平台接入后，协调器行为改为：

1. 通过平台客户端获取题目列表
2. 若本地不存在该题目录，调用 `pull_challenge()`
3. 若题目 metadata 标记为 unsupported，则跳过
4. 若题目需要 preflight，则先调用 `prepare_challenge()`
5. preflight 成功后再启动 swarm
6. preflight 失败则记录状态并跳过本轮

这样协调器只新增一层“preflight 调度”，不需要理解凌虚平台细节。

---

## 15. 日志与可观测性

为便于后续联调，建议新增以下日志事件：

- `platform_login_validated`
- `platform_login_failed`
- `challenge_materialized`
- `challenge_materialization_failed`
- `challenge_skipped_unsupported`
- `challenge_preflight_started`
- `challenge_preflight_failed`
- `challenge_preflight_succeeded`
- `platform_submit_attempt`
- `platform_submit_result`

这些日志至少需要包含：

- 平台类型
- `event_id`
- `platform_challenge_id`
- 本地 challenge 目录
- 错误信息（如果失败）

---

## 16. 错误处理策略

### 16.1 启动期错误

以下错误在程序启动时直接终止：

- Cookie 缺失
- Cookie 中没有 `sessionid`
- Cookie 中没有 `csrftoken`
- 平台地址不可达
- 赛事 ID 无效
- 当前登录态无权访问赛事 CTF 接口

### 16.2 拉题期错误

以下错误在单题层面失败，不终止整场：

- 题目详情获取失败
- 附件下载失败
- metadata 写入失败

处理方式：

- 记录失败日志
- 跳过该题
- 允许后续重试

### 16.3 Preflight 期错误

以下错误视为可重试失败：

- 环境启动失败
- 取地址失败
- 地址格式无法解析

处理方式：

- 本轮不启动该题 swarm
- 不影响其他题
- 保留失败信息，下一轮允许重试

### 16.4 提交期错误

提交错误不应导致整个协调器退出。  
需要统一映射为 solver 可理解的提交结果文本。

---

## 17. 测试策略

### 17.1 单元测试

单元测试覆盖以下内容：

- Cookie 解析逻辑
- CSRF 头构造逻辑
- 题目字段映射到 metadata 的逻辑
- 题目目录命名逻辑
- unsupported 题目识别逻辑
- 连接信息归一化逻辑

### 17.2 Mock 集成测试

使用 mock HTTP 服务覆盖以下闭环：

1. 拉题列表
2. 拉题详情
3. 下载附件
4. 环境型题 `run`
5. 环境型题 `addr`
6. 提交正确 flag
7. 提交错误 flag
8. 登录态失效

### 17.3 人工冒烟测试

至少准备一个真实凌虚测试赛事，覆盖：

- 外链题
- 环境题
- 附件题
- check 题（验证跳过）

人工验证以下结果：

- 能正常列题
- 能正常落地本地目录
- 能对环境题拿到连接地址
- 能正确提交 flag
- 错误 flag 被识别为错误
- check 题不会被错误送入 swarm

---

## 18. 渐进式落地顺序

建议按以下顺序实施：

1. 引入平台抽象层，但先只迁移 CTFd 现有逻辑
2. 加入凌虚平台配置和启动期校验
3. 实现凌虚题目列表与已解状态获取
4. 实现题目详情落地和附件下载
5. 实现环境型题目的 preflight
6. 实现 flag 提交
7. 接入协调器主循环
8. 增加测试和日志完善

这样做可以保证每一步都可验证，不需要一次性重构所有路径。

---

## 19. 关键设计决策总结

本设计做出的关键决策如下：

1. 不把凌虚逻辑硬塞进 `CTFdClient`，而是新增最小平台适配层。
2. 不做大而全的平台框架，只接入“凌虚赛事 CTF”。
3. V1 不自动处理验证码登录，使用用户提供的浏览器 Cookie。
4. V1 明确跳过 `check` 模式题。
5. 提交 flag 使用平台题目实例 ID，而不是题目名。
6. 为环境型题目增加 preflight 阶段，负责 `run -> addr -> metadata 更新`。
7. solver 仍只消费本地 challenge 目录，不直接感知平台差异。

---

## 20. 预期收益

完成该功能后，HuntingBlade 将获得以下能力：

- 可直接接入凌虚平台的赛事 CTF
- 不必手工把题目复制/转换到本地后再运行
- 对环境型题目可自动拿到连接地址
- 与现有 solver / swarm 体系保持兼容
- 后续如需接入 `train`、`AWD`、`CFS`，将拥有更清晰的扩展边界

---

## 21. 后续扩展方向（不纳入本次实现）

以下方向不属于本次实现，但设计上已为其留出空间：

- 支持浏览器账号密码 + 验证码自动登录
- 支持 `train` 作训 CTF
- 支持 `check` 模式题自动触发与结果消费
- 支持 AWD / CFS 单独适配
- 支持平台能力注册表
- 支持多赛事并行监听


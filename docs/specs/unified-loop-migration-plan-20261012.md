# JobHunterAgent：统一 Loop 架构迁移实施计划

日期：2026-10-12。状态：待实施。本轮只编写计划，没有修改运行代码、迁移用户数据库或运行收费测试。

后续任务总入口见 [优化收尾、统一迁移与 LinkedIn MCP 实施总纲](execution-roadmap-linkedin-mcp-20261012.md)。其中 R1 对应本方案 M0，R2–R5 对应 M1–M7；迁移完成后再执行 R6 来源链路回归、R7 LinkedIn MCP 测试、R8 默认策略与 R9 开源交付。本文件继续作为迁移细则，不增加第二条实施路线。

## 1. 目标与执行顺序

最终只保留一个自主决策内核：`agent_runtime/loop_engine.py::AgentLoop`。Career、投递、旧 Session 以及未来需要自主决策的子任务，都通过领域 Host 使用这个内核。任务启动、预算、取消、恢复和执行所有权也逐步收敛到统一执行服务。历史接口可以继续作为兼容入口，但不能继续维护另一套决策循环。

确定性步骤仍由代码推进：解析简历、分析 JD、评分、材料校验、索引、生成报告等，作为统一执行层的有类型工作流/作业运行；不为每一步增加一次路由模型调用。单次结构化生成通过共同的模型调用与计量边界执行。这里的“统一”是执行契约和决策内核统一，不是所有业务状态表合并，也不是强迫每个函数调用一次 LLM。

推荐顺序：**既有 optimization 收尾并冻结 → 公共执行契约 → Session 迁移 → 旧分析与材料工作流迁移 → 多任务调度收敛 → Career/投递/面试生命周期收敛 → 在途任务清理 → 删除旧执行路径。**

关联文档：

- `integrated-optimization-execution-plan-20261012.md`：P0–P9 优化主计划，继续负责功能、质量和性能验收。
- `integrated-handoff-claude-to-codex-20261012.md`：当前交接线索；实施前重新核对源码和证据，不能把交接声明直接当成通过证明。
- `opt-v3-stage-1b-treg-ab.md`、`treg-ab-execution-handoff-20261012.md`：已有 Treg 能力、配置和试验约束。本计划迁移其执行归属，不重新做一次接入。

本计划补充上述文档的架构收敛要求，不重开已经完成的优化阶段，不覆盖其他会话正在维护的文件。发现冲突时，先记录当前实现与证据，更新阶段范围，禁止同时修改同一组 Loop/上下文代码后混合归因。

## 2. 当前代码核对与迁移范围

以下是静态阅读结论；不代表已完成运行验收。开始实施时需按最新提交复核。

| 当前入口/模块 | 当前性质 | 最终处理 |
|---|---|---|
| `task_loop.py`、`task_host.py`、`career/service.py` | Career 已使用通用 AgentLoop；外层还有线程、恢复和事件管理 | 保留领域 Host，生命周期委托统一执行服务，不重写 Career 决策循环 |
| `auto_apply/agent.py`、`runner.py`、`loop.py` | `DecisionRunner` 经 `ApplicationHost` 使用通用 AgentLoop；投递生命周期另行管理 | 保留 Host、页面校验、确认和浏览器线程约束；逐步迁移调度与恢复 |
| `sessions/coordinator.py`、`tools/loop.py` | Session 有独立决定/工具调用路径及领取、版本、事件逻辑 | 新增 SessionHost，使用通用 AgentLoop；旧 Coordinator 变薄兼容层，最终删除旧决定循环 |
| `tools/model_adapter.py` | 自建消息转换；当前转换未保留完整停止/非法调用信息，非法 JSON 可能降成空参数 | 统一响应规范，保留截断、非法参数和 provider 元数据；先补回归再迁移 |
| `custom_agent/loop.py`、`main.py`、`api/services/run_service.py` | 固定步骤、事务状态、人工审核的旧分析运行器；仍有 CLI/API 入口 | 保留业务转换规则和证据处理，改为统一执行层的 AnalysisWorkflow；旧运行器退出生产路径 |
| `custom_agent/handlers.py`、FitAnalysis、ApplicationPackWorkflow | 共享领域处理、缓存、校验与有界修订 | 提取/复用为领域能力，不当作废代码删除，不增加自主规划循环 |
| `multi_agent/scheduler.py`、`job_workflow/plan.py`、`workers.py` | SQL 领取、有界并发、预算和固定 DAG | 提取可复用调度能力；DAG 作为业务计划保留；自主子任务使用同一个 AgentLoop |
| `multi_agent/model_usage.py` | 被多条调用路径使用的嵌套用量作用域 | 移入中立计量层，保留调用语义和历史账目；兼容 import 最后清理 |
| `interviewer/controller.py`、`mock_interview/controller.py`、`career/interview_queue.py` | 证据补全、模拟面试、持久 FIFO 和异步反馈 | 保留业务区别；调度、取消、模型计量统一，不能丢掉逐面试顺序和问题绑定 |
| `api/assistant_routes.py`、`assistant/projection.py` | 动作入口与跨表展示投影 | 动作转发统一执行服务，读投影继续支持历史数据；不另起模型决策器 |
| 历史 LangGraph/backend/workflow 标识 | 兼容历史记录，不能仅凭名称认定仍可执行 | 保留必要读兼容，移除可达旧运行分支；不要批量改写历史 provenance |

“没有从当前前端看到调用”不足以证明接口无用。删除前必须检查 API、CLI、启动注册、测试、文档、动态注册和导入引用。

## 3. 目标结构与责任边界

```text
Web / CLI / 兼容 API / 定时触发
                  │
          ExecutionService
   创建、幂等、领取、预算、取消、恢复、事件
                  │
       ┌──────────┴──────────┐
       │                     │
  通用 AgentLoop        确定性 Workflow / Job
       │                有界步骤 + 业务状态机
  领域 Host                  │
       └──────────┬──────────┘
         Capability / Domain Service
    搜索、抓取、分析、材料、面试、浏览器操作
                  │
       Model Gateway / HTTP / Browser
     共同计量、执行收据、资源所有权与取消
```

### 3.1 通用内核

- 保留实际类名 `AgentLoop`，不为统一命名新增第二个 `LoopEngine` 实现。
- 负责 observe → 请求组装 → 模型决定 → 参数校验 → Host 执行 → 持久化/让出工作线程；保留陈旧响应拒绝、上下文归档与无效响应保护。
- 明确定义 Host Protocol。基于现有方法：`active`、`revision`、`observe`、`invoke`、`progress`、`on_text`、`execute`、`action_error`、`after_action`、`persist`；`text_guard`、`validate_batch`、`image_message` 等可选能力要有显式契约或无副作用默认实现。
- `Turn` 的 snapshot、revision、tools、images、batchable、allowed_tools 和兼容工具语义保持可测试。当前标记 batchable 不等于已经真正并发执行，迁移不得顺便并发副作用工具。
- 循环 slice 用完表示 yield，不能误变成等待用户或任务成功；成功、失败、取消、等待用户、等待子任务必须明确区分。

### 3.2 领域 Host 与能力

- Host 负责领域状态投影、可用工具、完成标准、授权边界、结果校验和状态落库。各领域状态机可以独立存在。
- 所有工具执行经过共同能力执行契约，复用现有 ToolExecutor 的授权、幂等、MCP/skills 和来源约束；不能为了接入 Host 绕开旧保护。
- 同一个工具的 schema、说明和实际行为从同一能力定义生成。API-first 提示、工具说明、slim tools 不再分别维护相反规则；策略开关关闭时仍符合旧契约。
- Treg、招聘板 API、Crawl4AI/AnyAPI、浏览器都是数据/操作能力。默认 API 找候选，缺 JD 再抓取或浏览器核验；是否推荐仍取决于原有资格与证据标准。
- 领域层不依赖 `api.*` 路由函数。PDF 提取、公共结果转换、Workspace/Fit 业务服务移至中立服务模块，由 API 和 Host 共同调用。数据库 Base/模型的进一步拆分单独做，不混入行为切换。

### 3.3 执行与调度

- 一个逻辑 ExecutionService 管理执行记录和所有权；可有多个有界资源池。HTTP 并发、浏览器线程亲和、面试 FIFO、模型并发可分别限制，无需强制单线程。
- 复用现有 SQL claim、lease、heartbeat 和预算机制，先抽契约再迁表；禁止另外新建一个功能重叠的全能 scheduler 长期并存。
- 每个 execution 只能有一个有效 owner。以事务/CAS、lease epoch 和领域 revision 防止旧 worker 恢复后提交结果。领域写入和执行状态写入同库时同事务，跨边界使用持久收据/outbox 和幂等处理。
- 不能在 worker 中同步等待占用同一资源池的子任务，避免线程池耗尽；父任务保存 child reference 后让出，完成事件唤醒。
- 面试 resource key 以面试实例为边界，浏览器以实际会话/所有者为边界；不得拿用户 ID 当全部任务的全局串行锁。
- 定时提醒和启动恢复只负责 enqueue，不直接启动另一条模型循环。

### 3.4 模型、计量与资源

- 统一模型调用边界，兼容现有 provider，不引入新的供应商依赖。保留 finish/stop reason、非法 tool call、usage、缓存用量、provider request ID 和响应类型。
- 截断或非法参数必须作为无效结果处理，不能将损坏 JSON 转为 `{}` 后执行。重试次数与当前已验收政策一致，并逐次计费/计量。
- 一个 provider attempt 只有一个账目源；父任务聚合子任务账目，不重复记费。root budget 包含嵌套调用、验证、修订和失败尝试。
- 预算先预留，结束后结算；无 usage 的未知请求保留 unknown/pending，不按零费用释放。收费工具与模型预算分开，同时可在 root 展示汇总。
- 生命周期统一关闭 HTTP/Treg/模型客户端，取消待执行作业；浏览器在拥有它的线程关闭。补上 `CareerHarness.close()` 未关闭 Treg client 的路径，并验证重复关闭安全。
- 配置入口明确 `.env` 与进程环境变量优先级。迁移前盘点各 flag 当前读取方式，兼容调整要有单独测试；不改变用户 `.env` 值。Treg 继续开源用户自行配置 key，不做统一托管收费。

## 4. 状态与迁移协议

新增结构优先扩展现有任务存储；只有无法表达时再增加表。下面是所需语义，不要求机械创建同名表。

| 记录 | 必要信息 |
|---|---|
| Execution | ID、root/parent ID、kind、原领域对象引用、状态、runtime/schema version、revision、owner/lease epoch、时间、取消请求、停止原因、预算引用 |
| Step/Attempt | execution/step/attempt ID、幂等键、输入版本/摘要、调用状态、结果引用、provider/tool 收据、unknown 标记 |
| Event | execution ID、单调序号、事件 ID、领域事件引用、关联 attempt/child；投影消费可去重 |
| Legacy mapping | 旧表/旧 ID → execution ID 唯一映射、迁移版本、来源摘要、迁移结果；不能按旧 ID 字符串直接跨类型碰撞 |

迁移规则：

1. 先新增可空字段、映射与索引，提供 dry-run、备份恢复演练和可重跑迁移；只在副本验证，不在本任务直接迁移真实用户数据库。
2. 保留旧 API/CLI ID、审核 ID、候选身份、来源证据、材料版本、面试题/回答绑定、账目和 tool call ID。execution ID 用映射连接，不重新生成业务事实。
3. 历史已结束记录可保持原格式，由读适配器展示。无需把多年历史灌成新的对话上下文，也不要伪造它们由新内核运行。
4. checkpoint 必须带 schema/runtime version、领域版本、pending call/child、预算引用与授权版本。原始证据保持引用和精确取回能力，不迁成不可核验摘要。
5. 迁移后每个对象只允许一条写路径。读兼容可以双格式，不能新旧循环同时写同一个任务。
6. 租约只能保护本地提交；无法保证不支持幂等的外部站点 exactly-once。调用前记 intent，调用后记 receipt；崩溃位于两者之间时先核验外部结果，无法核验则停止等待处理，禁止自动重投。
7. 用户修改、拒绝、取消或撤销授权后，旧响应不得覆盖新版本。恢复时必须重新检查有效授权、输入版本与实际页面，不复用过期确认。

### 在途任务处理矩阵

| 状态 | 切换办法 |
|---|---|
| 未开始/queued | 加锁后生成唯一映射和新 checkpoint，由新执行服务领取；旧领取入口拒绝该对象 |
| 正在模型请求 | 停止新调度，在安全检查点等待完成；超时标记结果未知/忽略陈旧结果，保留实际计量；不同时再发一份 |
| 等待用户/人工审核 | 迁移 pending 问题、审核内容 hash 和版本；收到旧 URL 的回复也映射到同一个新 execution |
| 等待子任务/面试反馈 | 保留 parent-child 和问题绑定，迁移完成事件去重键；父任务恢复不重复创建 child |
| 浏览器步骤/外部写入在途 | 停在安全边界，保存 intent/receipt；不支持跨线程恢复的浏览器重建后重新观测；未知提交进入核验 |
| 无法可靠转换的旧活动任务 | 明确列出对象和原因，有限期排空或用户可见停止后从安全点重启；不静默丢弃或伪装成功 |
| 历史终态 | 只读兼容，保留原始 provenance，不触发模型/API调用 |

runtime version 在创建/迁移时绑定 execution，不能每次 HTTP 请求根据全局开关重新选一个内核。每次部署记录旧活动任务数量和退出条件，不能靠无限保留 flag 完成迁移。

## 5. 实施阶段与验收

每阶段单独提交、单独诊断报告，后续阶段以该阶段验收为依赖；不按日期强行切换。新增文件名是建议，可根据实际结构调整，但责任与验收不可省略。

### M0 — 冻结 optimization 与迁移基线

2026-10-12 用户确认的[门槛修订](r1-r2-api-first-gate-amendment-20261012.md)：旧 browser-first B6 失败保留，不再阻挡 M1。迁移准备门已放行；最终两条合格推荐的业务验收移到 R6/R9 的 API 优先配置。材料 full 未决验证归 M3，不能据此豁免 grounding 或将未测写为通过。

工作：核对 P0–P9 最新代码、交接和验收报告，形成 `docs/diagnostics/unified-loop-m0-baseline.md`。记录准确提交、未提交变更归属、配置、已采用/关闭/延期项目、现有测试命令和结果。列出所有 API/CLI/后台启动点、循环、恢复线程、模型调用与收费工具调用，画出到最终执行器的调用关系。

门槛：正在修改共享 Loop/上下文的 optimization 先完成；每个未通过项有明确保留状态，不能把迁移当成性能修复已完成。尤其保留 B6 真实推荐结果与离线结果的区别，A5 的 user-deferred 状态，以及未配置 fast 模型的未测状态。无法跑的检查写清原因，不计通过。

产物：逐入口迁移表、现状失败清单、冻结离线 fixtures、性能/调用次数参考值、后续每阶段涉及的文件。基线未冻结前只允许盘点与文档，不开启跨模块重构。

### M1 — 公共契约和保护补齐

建议落点：`loop_engine.py`、拟新增 Host protocol/执行契约模块、`tools/model_adapter.py`、公共计量模块、配置和客户端生命周期。

工作：定义 Host 与 execution 协议；覆盖停止原因/非法 JSON/空工具参数区别；统一 attempt 关联与资源关闭；提取被 runtime 引用的 API 业务函数。先做兼容接线，保持行为与调用次数。

验收：现有 Career/Application Host 契约通过；截断响应和非法参数不会执行工具；嵌套调用只结算一次；取消不接受陈旧结果；Treg/浏览器/模型资源按所有者关闭。离线测试隔离真实网络和模型。新契约不可触发第二次模型请求来“适配”旧结果。

### M2 — 旧 Session 接入唯一决策内核

建议落点：新增 `sessions/host.py`，调整 `sessions/coordinator.py`、`tools/loop.py`、`api/session_dependencies.py`。

工作：SessionHost 翻译现有上下文、工具与状态；通过共同执行接口继续调用现有工具执行器。迁移领取、heartbeat、state version、pending assistant/call、人工确认与 timeline 投影。Coordinator 只处理入口/领域状态协调，不再决定下一次模型/工具调用。开始时仅对选定新测试 execution 使用新路径。

验收：新旧冻结样本业务结果相同；每个 assistant tool call 都有合法终态/等待态；重启不会重复执行 pending 副作用；模型异常的等待用户语义保留；旧 `/sessions` 和 assistant 操作仍可用。覆盖 MCP/skills 工具、取消、deadline、预算、人工确认和两个并发请求争抢同一 Session。

退出条件：所有新建 Session 都由通用 AgentLoop 决策；旧路径只处理明确列出的待排空任务，不能自动回退。M7 删除旧 `ToolCallingLoop` 决策实现；仍使用其名称的兼容入口只能转发。

### M3 — 固定分析/材料工作流接入

建议落点：`custom_agent/loop.py`、`handlers.py`、`api/runtime.py`、`run_service.py`、`main.py`、`application_pack/workflow.py`、FitAnalysis 服务。

工作：把旧 custom loop 的状态转换、人工审核、修订次数、精确引文验证和有界恢复提取为 AnalysisWorkflow 的单步操作。统一执行服务负责安排下一步和 checkpoint，领域 policy 决定合法转换。CLI 和 `/runs` 保持外部结果结构，转发到该工作流。材料工作流沿用已验收 patch/full revision 策略，不重新实现 writer/verifier。

验收：输入校验、分析、匹配、生成、人工修改、拒绝、有限修订、重启和历史结果全覆盖；无新 router 模型调用；原缓存签名和 evidence provenance 不丢失。老 backend 标识继续可读，但不能选择第二个生产执行器。

退出条件：生产不再实例化 `custom_agent.loop.AgentLoop`；共享 handler 先迁入中立领域模块，旧 import 可短期转发，不能因删除旧目录损坏 FitAnalysis/材料生成。

### M4 — Multi-agent 收敛为统一子任务调度

建议落点：`multi_agent/scheduler.py`、repository、model_usage、`job_workflow/plan.py`、workers、注册与 API composition root；中立执行服务可置于 `agent_runtime/execution/`。

工作：提取既有 SQL 所有权、预算、deadline、并发限制和恢复机制，接入 M1 契约；保留 source → 分析 → match → gap 等业务依赖。固定 worker 作为有类型 job；确有自主决定需求的 worker 用同一 AgentLoop+Host。移动通用 usage scope，旧引用渐进更新。

验收：一个 child 只有一个 owner；取消/超时/失败传播符合父任务政策；部分成功可恢复；父等待子不占工作线程；父子费用不重复；上下文只传必要的结构化输入和证据引用，不复制完整父会话。

退出条件：multi-agent API 是创建/查询同一执行体系中的作业图；不存在另一个模型规划器或并行预算真相源。`workflow_mode` 可保留历史信息，但新任务不再用它选择不同执行架构。

### M5 — Career、投递、面试生命周期收敛

建议落点：`task_loop.py`、`career/service.py`、`auto_apply/loop.py`、面试 controllers/queue、提醒调度与启动恢复注册。

工作：逐个迁移 enqueue/claim/heartbeat/cancel/recover，保留已有 Host。每切换一类任务就撤掉该类的旧轮询/恢复 owner。面试仍有逐实例 FIFO、异步反馈和持久绑定；证据访谈与模拟面试仍是两项领域能力。投递保留浏览器线程亲和、页面新鲜度、用户确认和表单决策记录。

验收：应用重启只恢复一次；运行多个任务仍有界并发；同一浏览器不跨线程竞争；End/skip/answer/feedback 并发不串题；取消后不产生新的外部写入；提醒重复触发不创建重复任务。不得把已经通过的面试功能改成多轮 router 驱动。

退出条件：没有脱离 ExecutionService 的独立任务所有权/恢复循环。仅承担定时 enqueue、资源专用执行或读投影的线程可保留，并记录其职责。

### M6 — 数据演练与正式切换准备

工作：对匿名/测试数据库副本执行第 4 节矩阵；对每类 checkpoint 做 dry-run → 迁移 → 重跑 → 重启 → 业务继续 → 历史读取。明确不可转换任务清单、预计排空方式、备份和恢复步骤。输出可审查的迁移命令与迁移报告，真实数据执行另按部署授权进行。

验收：映射唯一；无记录遗漏；历史费用不重结算；回答/审核仍绑定正确版本；重复执行迁移结果一致；未解决外部副作用保持 unknown。切换入口后旧 owner 不能领取已迁移任务。

新任务默认统一架构。旧任务按登记表排空/迁移；尚有旧活动任务时只能标记“过渡中”，不能宣称迁移完成。

### M7 — 删除旧路径与防回归

工作：确认旧活动任务为零且历史读兼容通过，删除旧决策循环、重复 scheduler owner、废弃运行注册、失效 flag 和旧 fallback。兼容 API/CLI 可以保留，但必须只转发统一执行服务。更新 README、配置示例、架构说明、文档索引、开发者新增能力指南及旧计划状态。

验收：导入/注册/调用检查证明生产自主决策只到 `loop_engine.AgentLoop`；任何其他 provider 调用都属于登记的结构化生成、验证等操作，并进入共同 attempt/预算层。架构测试检查禁止依赖和旁路，不能仅按文件名搜不到 `loop` 就判通过。旧执行器的测试改为兼容契约/历史读取测试，不能无说明删除失败测试。

最终产物：`docs/diagnostics/unified-loop-final.md`，包含最终入口图、删除清单、兼容保留清单、全部阶段证据、剩余非迁移问题与指标对比。

## 6. 回归与性能验收

实施时按最新测试目录确认命令。现有相关套件包括：

- 内核：`test_shared_agent_loop.py`、`test_task_loop.py`。
- Session：`test_tool_loop.py`、`test_session_coordinator.py`、`test_session_runtime.py`、`test_session_api.py`、`test_session_claims_recovery.py`、`test_session_cancellation_deadlines.py`、`test_chat_workflow_tools.py`。
- 分析/作业：`test_custom_agent.py`、`test_job_workflow.py`，以及材料和 FitAnalysis 的实际现有套件。
- 投递：`test_auto_apply_approval.py`、`test_auto_apply_recovery.py`、`test_auto_apply_repeat.py`、`test_auto_apply_parallel.py` 与该阶段涉及的浏览器测试。
- 面试：`test_interviewer.py`、`test_mock_interview.py`、`test_remaining_interview_fifo.py`、`test_remaining_interview_feedback.py`、异步与失败锁套件。

每阶段先跑涉及行为的现有回归和有价值的新故障注入测试，通过后在阶段切换前跑冻结全量套件；没有新改动或新疑点不反复全量运行。

必须新增的跨入口场景：同一个任务由旧 API 与新 API 同时恢复；工具成功但回执写入前崩溃；模型发送后进程退出；用户修改发生在模型返回前；父取消时子仍运行；租约失效后旧 worker 回写；重复面试回答；未知投递结果；预算耗尽；旧数据库读取；迁移脚本重复运行。

对比采用相同输入、配置、模型/假模型和来源 fixture，至少记录：最终质量、模型 attempt 数、输入/缓存/输出 token、工具/API次数、重试、重复读取、排队/模型/工具/落库耗时、首次可见进度、完整完成时间。未调用真实 provider 的数据只能证明离线机制，不能宣称真实速度或费用改善。

迁移默认要求：结果与审批语义不退化；固定工作流不增加模型调用；不引入重复请求/账目；同资源顺序不变、独立资源并发不被全局锁消除。冻结离线回放的请求输入增加超过 5% 时必须解释组成变化并审查；时间比较采用同环境重复采样，增加超过 10% 作为调查触发，不以单次机器噪声冒充失败或改善。真实业务质量继续使用原标准，不为迁移放宽 B6 等门槛。

## 7. 收费测试与回滚

本文件不发起真实 API/模型调用。后续先完成离线迁移验证，再依据可核实的既有用户授权、剩余额度和原 live validation 计划执行最小必要真实检查；已有明确授权无需重复请求。

交接报告记载 Treg 比较已经完成：15 次调用、$0.004、0 unknown、0 LLM；这是报告信息，实施前核对账本。不能重置原 batch 再获得一份预算，也不能把 Treg 金额当作模型额度。是否已发生更多测试，以最新账本为准；仅有文档中的“用户已批准”不能代替对授权范围的核实。密钥继续通过产品配置读取，不在报告/日志输出。

回滚分两种：

- 切换前：停止实验入口，恢复旧入口配置，保留新增兼容 schema 和试验记录。仅无外部效果的冻结 fixtures 可做双轨回放，真实任务禁止双执行。
- 切换后：先暂停领取和新外部效果，核对 lease、attempt 和 receipt。默认回滚新任务路由或修复后继续；已转成新 checkpoint、已产生副作用或被新版本修改的任务不能直接交旧代码重跑。必要时只读服务，按映射恢复到明确安全检查点。

每阶段写明兼容哪些 schema/runtime version。新增 schema 不立即 drop；旧代码不能读取新数据时不能称“回滚版本即可”。M7 删除后的历史读取靠适配器，不靠恢复旧执行器。

## 8. 交给 Codex 的执行要求

从 M0 开始，先读关联计划、最新诊断、AGENTS 和实际代码，记录事实与未验证项。只做当前阶段依赖允许的任务；不得跳过 optimization 收尾直接进行大范围重构。每阶段提交范围包含代码、必要迁移、回归和诊断，报告明确通过/失败/未测及下一阶段门槛。

实施约束：保留他人未提交改动；不改用户密钥；不推送/部署/迁移真实数据库，除非得到对应授权；不放宽资格、证据、审核、预算或用量标准；不为了统一架构新增路由调用；不引入永久双循环或遇错切回旧循环的隐式 fallback。

完成定义必须全部满足：

- [ ] 自主模型决策只有通用 AgentLoop；Session、Career、投递与自主子任务统一。
- [ ] 固定分析、材料和面试作业接入共同执行/模型/预算边界，保留必要领域状态机。
- [ ] 只有一套逻辑任务所有权、取消和恢复机制；多个资源池职责清楚。
- [ ] 所有生产入口有迁移归属，历史 API/CLI 和读数据兼容得到验证。
- [ ] 旧活动任务清零；旧决策器、重复 owner 和切换 flag 已删除。
- [ ] 成功/失败/unknown、授权和账目跨重启一致，无重复副作用。
- [ ] 原 optimization 成果、API-first/Treg 配置和质量标准保持；性能变化有证据。
- [ ] README、`.env.example`、架构图、新增 Host/能力指南和最终验收报告与实现一致。

结束时需要达到“多个领域能力共享一套执行架构”。兼容名称和历史读适配器可以留下，任何可达的第二套生产决策/恢复执行机制都意味着迁移尚未完成。

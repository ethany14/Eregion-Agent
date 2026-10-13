# JobHunterAgent 最新完整执行方案与 Claude 交接

日期：2026-10-12。执行对象：Claude。项目：`C:\Users\zhiyu\Documents\JobHunterAgent`。

本文件是本次交接的执行入口，汇总 optimization 收尾、统一 Loop 迁移、招聘板/Treg 链路、LinkedIn MCP 测试及最终业务验收。用户已确认：允许先迁移，不要求旧自主浏览器搜索先通过 B6。此次交接只编写文档，不代表后续代码或测试已完成。

## 1. 执行结论和不可混淆的状态

**现在从 R2/M1 开始实施，先核对基线，不重做 R1。** R1 的迁移准备门已放行；真实业务验收仍未通过。旧 B6 失败作为历史基线保留，最终两条合格推荐的业务门移到迁移后 API 优先配置。

最终目标：所有自主决策只使用 `agent_runtime.loop_engine.AgentLoop`；所有任务共享一套逻辑执行所有权、预算、取消、恢复和计量机制。分析、评分、材料校验、面试等固定流程继续作为确定性工作流，不为了架构统一增加 LLM 路由。

目标搜索路线：**招聘板 API／已配置的 Treg 获取候选 → 去重 → 补完整 JD → 资格核验 → 正式评分 → 决策与保存 → 用户交付**。浏览器补充读取和核验；LinkedIn MCP 只有验证通过且用户配置可用后才参与，不是前置必需依赖。

不得把“允许迁移”写成“optimization 全部通过”，也不得因旧浏览器 B6 未通过而重新阻塞 R2。

## 2. 必读文件与优先级

以下路径均相对项目根目录。先读适用的 `AGENTS.md`、项目约束及最新代码，再按顺序阅读：

1. `docs/specs/claude-unified-execution-plan-20261012.md`：本交接入口与执行顺序。
2. `docs/specs/r1-r2-api-first-gate-amendment-20261012.md`：用户确认的门槛调整，覆盖旧文档的 browser-first B6 前置要求。
3. `docs/diagnostics/r1-closeout-and-r2-gate-20261012.md`、`r1-adoption-decisions-20261012.md`：当前状态、采用决定和未决问题。
4. `docs/specs/unified-loop-migration-plan-20261012.md`：M0–M7 技术细则、在途任务矩阵与回滚。
5. `docs/specs/execution-roadmap-linkedin-mcp-20261012.md`：R1–R9 总纲、LinkedIn MCP 接入和 T0/T1/T2 细则。
6. `docs/specs/integrated-optimization-execution-plan-20261012.md`、`integrated-handoff-claude-to-codex-20261012.md`：已有优化实现与交接，不重新启动另一套优化工程。
7. `docs/specs/opt-v3-stage-1b-treg-ab.md`、`treg-ab-execution-handoff-20261012.md`，以及 `docs/diagnostics/treg-ab-contract.md`：已有 Treg 实现、契约和比较结果。
8. `docs/diagnostics/integrated-live-validation-plan.md`、`r1-live-validation-20261012.md`、`r1-offline-revalidation-20261012.md`，以及 `docs/benchmarks/r1-closeout-20261012/`：测试节点、实际结果和费用账目。

旧文档出现“当前只授权写文档”“R1 不放行”时，区分其写作时点与最新修订。阶段依赖遵循用户确认的门槛修订；历史日志的失败事实不能被新文档覆盖。发现其他技术冲突先核对实际代码与证据，不自行放宽质量、预算或授权。

## 3. 已完成基线与实施前核对

| 项目 | 已记录状态 | 执行含义 |
|---|---|---|
| 原项目 HEAD | `92b60550c0aeda7f3d4a67911f026b17769292af` | 原工作区有未提交/未跟踪的优化文件，HEAD 不代表全部当前代码 |
| optimization 验证基线 | `57c63ab4b9812ddcb0d9bc8e9f3760d1539f8a45` | 已在隔离 checkout 进行离线及真实测试 |
| 最小收尾修复 | `158e55781c0467fb97d70710471d3444090af596` | 修复预算停止时交付已保存结果，以及材料 live 测试 writer/verifier 绑定；已按文件核对写回原项目，不代表原分支已含此提交 |
| 历史 13 个失败/错误节点 | 13 passed，12 passing subtests | 正常权限环境已验证，不再当未处理失败 |
| 基线完整离线 | 2136 passed，134 skipped，16 passing subtests | 对应修复前基线，不称修复后完整全量 |
| 修复后受影响回归 | 53 passed，2 paid skips | 两处最小修复已有离线证据 |
| 真实 L1 | 冻结来源覆盖不足，失败 | 不无限补回放或重跑收费比较；B4、L2 未验证，不采用 |
| 真实 L3 full | needs_revision，失败 | 测试绑定已修，真实复验未做；材料质量待办归 R3 |
| 真实 L4/browser-first B6 | 只保存一条合格推荐；原完整交付计数 0 | 失败保留，不再阻挡迁移；不能声称新来源失败或通过 |

实施前读取 `docs/benchmarks/r1-closeout-20261012/implementation-manifest.json` 与 `sync-receipt.json`，核对后续变化。报告/README 后来因门槛调整而更新是预期差异；运行代码差异必须独立审查。不要把所有文件机械要求等于旧 manifest。

`r1-closeout.bundle` 包含原 optimization 延续与最小修复，前置提交为上述原 HEAD。需要重建时在新的干净审查 checkout 中使用；不要在原脏工作区 reset、clean、全量覆盖或盲目 cherry-pick。检查他人正在修改的文件，先固定实施快照和归属。

先生成或更新 `docs/diagnostics/unified-loop-m0-baseline.md`：记录当前真实版本/差异、入口清单、采用开关、已知失败、测试结果及每阶段文件范围。已有证据未受变化影响就复用，不无理由重跑全量或收费测试。

## 4. 唯一执行顺序

| 顺序 | 阶段 | 范围 | 阶段门 |
|---|---|---|---|
| 1 | R2 / M1 | 公共契约、响应保护、计量、资源关闭、API-first 指令一致性 | 离线契约与故障边界通过 |
| 2 | R3 / M2 | Session 接入通用 AgentLoop | 新 Session 唯一决策内核，兼容 API 与恢复正确 |
| 3 | R3 / M3 | 固定分析、材料工作流接入 | 无新增 router 调用，审核/证据/修订语义保留；材料未决验证有结果 |
| 4 | R4 / M4 | Multi-agent 收敛为子任务调度 | 单一 owner、预算和账目；父等待不占执行线程 |
| 5 | R4 / M5 | Career、投递、面试生命周期统一 | 无重复恢复、串题、浏览器争抢或取消后写入 |
| 6 | R5 / M6–M7 | 数据副本演练、在途任务处理、旧路径退出 | 映射/恢复/历史读取通过；旧活动任务清零后删除旧执行器 |
| 7 | R6 | 招聘板＋Treg 新体系回归，API 优先 B6 | 来源链路正确，真实业务状态独立报告 |
| 8 | R7 | LinkedIn MCP 适配与分层验证 | 采用／可选试验／延期有明确结论 |
| 9 | R8 | 固定最终来源策略 | 默认行为与采用证据一致 |
| 10 | R9 | 开源配置、最终业务验收与交付 | 唯一架构、业务门、文档和证据均完成 |

每一阶段先查是否已实现，再做小范围改动与必要验证。前一阶段契约/正确性失败时不进行依赖它的切换；可以继续无依赖的只读盘点和测试准备。不能同时大改 Loop、提示、来源、模型和并发后混合归因。

## 5. R2：公共契约与最小保护

建议核对 `agent_runtime/loop_engine.py`、`task_loop.py`、`task_host.py`、`tools/model_adapter.py`、`career/harness.py`、公共计量与配置代码。文件落点以仓库实际结构为准，不为满足文件名新增重复层。

执行任务：

- 为现有 Host 的 observe、invoke、execute、persist、取消/陈旧响应、batch 校验等明确协议；沿用 Career/Application Host，不重新写决策引擎。
- 修复旧 Session 模型转换丢失 stop/finish reason、非法 tool call 和 provider 元数据的问题。损坏 JSON 不能降成空参数后执行；合法空参数与损坏参数区分。
- 统一 root/child/attempt 关联、预留与结算；嵌套评分、验证、修订和重试只记一次且都占预算；unknown 不当零成本。
- 修复 `CareerHarness.close()` 的 Treg 生命周期缺口，覆盖重复关闭和异常退出；浏览器在所属线程释放。
- 让 API-first 的 prompt、snapshot、工具说明与 slim tools 由一致配置决定，验证开/关两种路径；本阶段不自动改用户 `.env` 或开启收费来源。
- 确定共同能力执行边界，保留现有授权/幂等/工具校验；被 runtime 依赖的 API 业务函数逐步移到中立服务，避免另造全能框架。

验收：截断/非法调用不执行工具；取消后陈旧结果不提交；无重复计费；资源可关闭；固定结果适配无额外模型请求。输出 `docs/diagnostics/unified-loop-m1-validation.md`，列范围、版本、命令、结果与下一步。

## 6. R3：Session 与固定工作流

### M2 Session

实现 SessionHost，把现有消息、工具、状态、人工确认与 timeline 投影接到通用 AgentLoop。复用 ToolExecutor、MCP/skills、claim/heartbeat/version 等保护。Coordinator 仅保留入口和领域协调，不再有另一套决定下一步的循环。

覆盖 `/sessions`、assistant 操作、并发争抢、取消/deadline、等待用户、pending call、工具成功但回执落库前崩溃、模型返回前用户修改。所有新任务用统一内核；旧任务只能按登记表排空，不允许遇错自动回退旧循环。

### M3 分析与材料

把 custom_agent 固定步骤变成确定性 AnalysisWorkflow，由共同执行层调度和 checkpoint。复用 handlers、FitAnalysis、ApplicationPackWorkflow、缓存与验证器；CLI、`/runs` 保持结果契约。不得为解析、评分、校验和状态推进增加 router 请求。

迁移保留人工审核、拒绝、版本绑定、精确引文、有界修订、恢复和历史读取。`MATERIAL_PATCHES=0`，不能把已接线但未通过采用验证的 patch 当默认。

单列本次 L3 遗留：writer/verifier 绑定已修复；未引用的 experience opening 和 full 路径真实验收仍未解决。先用离线证据定位，不删除 grounding；符合原授权和预算时准备一个有限复验批次。人工风格评审未做就明确未做，不能代签。未解决时材料迁移不能标全验收通过；不影响独立代码准备，但最终交付必须保留阻塞。

产物：`unified-loop-m2-validation.md`、`unified-loop-m3-validation.md`，以及材料原验证报告的追加结果。不得覆盖旧失败样本。

## 7. R4：调度与生命周期

### M4 子任务调度

从现有 multi_agent scheduler 提取 SQL claim、lease、heartbeat、deadline、有界并发和预算；保留 source→分析→match 等业务 DAG。固定 worker 是有类型作业；真正需要自主决策的 worker 使用同一 AgentLoop+Host。

统一执行服务是唯一逻辑 owner，可以有不同资源池，不要求所有业务串行。父任务等待子任务时保存引用并让出工作线程；父子账目只聚合不重复结算；只传结构化输入和证据引用，不复制全部会话。旧 `workflow_mode` 可作历史字段，不能选择第二套架构。

### M5 Career / 投递 / 面试

逐类切换 enqueue、claim、cancel、recover，切换一类就撤掉对应旧 owner。保留领域 Host、浏览器线程亲和、页面新鲜度、用户确认、面试逐实例 FIFO、题目/回答绑定、异步反馈和 End 语义。

验收包括应用重启只恢复一次、父取消子运行、租约失效后旧 worker 回写、重复提醒、重复回答、并发 End/skip/feedback、未知投递结果。定时 enqueue、资源专用线程和读投影可保留，但需说明它们不是另一套执行 owner。

产物：`unified-loop-m4-validation.md`、`unified-loop-m5-validation.md`。

## 8. R5：迁移演练与旧路径退出

依迁移细则第 4 节在匿名/测试数据库副本执行 dry-run→迁移→重复运行→重启→继续业务→历史读取。保持旧 ID、审核/答案绑定、provenance、费用与未知外部效果；历史结束任务可读适配，不伪造新执行记录。

列清每类在途任务如何排空、转换或人工处理。一个任务不能同时由新旧 owner 写入；外部请求已发送但回执未知时不能自动重投。记录 schema/runtime version、备份和可实际执行的恢复步骤。

**真实用户数据库迁移与部署不在本交接中自动获准。** 在副本完成可审查的准备；如果删除旧路径依赖真实部署排空而尚无授权，就记录部署切换待办，不能声称线上已完成。其间可在隔离的新架构验证环境做 R6 准备/验证；不因此启用旧循环生产 fallback。

旧活动任务清零且历史读取通过后，删除旧 ToolCallingLoop、自建 custom_agent 决策执行器、重复 scheduler/recovery 注册和失效切换 flag。兼容 API/CLI/import 可以薄转发，不能暗含第二套决策路径。

输出 `unified-loop-m6-validation.md`、`unified-loop-final.md`：入口调用图、保留/删除清单、在途任务状态、证据和部署待办。通过调用/注册/架构测试证明唯一内核，不只按文件名搜索。

## 9. R6：API 优先来源链路与 B6

先核对已有招聘板、Treg、AnyAPI/Crawl4AI 适配与历史比较，不重复接入、不重新花钱选供应商。公开招聘板通常需要 company/board 映射，不能当作全市场搜索数据库；公司发现与映射要保留。

统一候选身份、URL/岗位 ID、来源与时间、query provenance、JD 完整性和原始证据引用。跨来源去重以可信 ID/申请链接为依据；来源缺字段就保持未知。预算/健康/缓存/取消都接共同执行边界。

离线覆盖：正常、无结果、分页重复、缺 JD、关闭岗位、部分错误、超时、unknown 费用、重试幂等、API 禁用、无 key、多用户证据隔离。浏览器只在缺正文/证据冲突等必要情况下补读，完整可靠响应不重复打开核验。登录挑战/限流不能换同账号通道绕行。

新增 API-first 测试节点或来源策略参数，保留旧 browser-first 节点/原始证据；复用原 `evaluate_search` 业务断言。测试目标仍是合成简历的 **纽约 junior Data Analyst，至少两条有效合格推荐，不投递、不创建提醒**。

移除任务中强制“Start with LinkedIn or Indeed”的指令，与 API-first prompt/tool/snapshot 保持一致。每条必须读取 JD、核验岗位/资历/地点、正式评分、明确推荐、持久保存，并在最终回复包含链接和分数。仅发现 URL 或保存候选不算推荐。

模型限制：原 60 主调用、主/总各 1M 原始输入上限保留；沿用现运行器更严格的 **60 总 provider attempts**，内部评分/验证也计入。不得为了通过提高预算或换容易候选。Treg 外部工具单独预算/记账，不能拿模型额度补工具支出。

先准备有限批次与剩余额度，再在既有明确授权内执行一次必要验收；失败停止本组、保留证据、离线归因，不自动无限重跑。输出 `docs/diagnostics/api-first-b6-validation.md` 和独立样本/账本目录。B6 失败不倒退为要求旧浏览器路线通过，但最终业务交付仍不合格。

## 10. R7：LinkedIn MCP 的可选接入

严格沿用实施总纲的固定上游快照/版本核验、独立子进程环境与现有 MCP transport。复用 allowlist、read_only_tools、超时和诊断，不重写通用 MCP 客户端。

业务白名单：search_jobs、get_job_details、get_job_apply_url、search_companies、get_company_profile；实际工具 schema 必须核对上游固定版本。close_session 仅用于生命周期。发消息、连接请求、收件箱、个人资料修改和申请提交不在范围。

| 层级 | 执行内容 | 限制与停止条件 |
|---|---|---|
| T0 | 假服务、适配器、身份、分页、partial/限流/取消/重启/超大响应 | 零真实模型/账号请求；保护失败不得进入 T1 |
| T1 | 三组搜索，按固定顺序读取详情/申请入口，另做公司查询 | 最多 26 次业务 MCP 调用，零模型；每组最多两页，单次 ≤120 秒、批次 ≤30 分钟；重试计入 |
| T2 | 先录制内容的离线回放，再做必要真实 Agent 对比 | 仅在 T0/T1 通过且授权/剩余预算明确时；每样本 ≤20 attempts、100K 输入、15 分钟，六样本合计 ≤120 attempts/600K；取与既有额度的较小值 |

T1 账号必须由用户明确选择，不能自动借用本机登录会话。关闭自动浏览器登录导入，按用户/会话隔离 profile；同一会话初版串行，超时后确认底层取消/回收才安排下一次。登录挑战、限流、串号或无法取消时停止该来源。

已有浏览器路线无可比成功基线时，报告“无法比较”，不强制重跑来证明它成功、不编造加速百分比。允许单独确认 MCP 可用，但默认采用的覆盖/成本证据不足则保持可选。完整采用阈值沿用总纲第 6 节，禁止看完结果降低。

产物：`linkedin-mcp-contract.md`、`linkedin-mcp-offline-validation.md`、`linkedin-mcp-live-validation.md`、`linkedin-mcp-comparison.md`。MCP 未安装/未登录/未通过时明确延期，招聘板＋Treg 主线仍可交付；不得为完成阶段伪造通过。

## 11. R8–R9：配置、最终验收与交付

依据实际证据决定来源优先级：基础招聘板 API；用户已配置且可用的 Treg 补充发现/抓取；通过验收的 MCP 承担 LinkedIn 专用读取；浏览器补缺。来源按覆盖、健康、预算选择，不要求全部逐一调用。

Treg 继续开源用户自配 key，支持 `.env` 与已有配置优先级，无统一托管计费。只改 `.env.example` 的实际开关与占位值，不覆盖用户 `.env`。README 写清无 key 的基础能力、Treg 费用/启用、MCP 固定版本/显式登录/启停/注销、失败状态及回滚。

最终检查无额外凭据、只配置 Treg、只配置 LinkedIn、二者均配置的初始化与路由行为；能离线验证的配置组合不额外收费。无凭据不崩溃，不代表基础来源覆盖已被真实证明。

R6 已验收版本和 R8 最终配置一致时，R9 引用原 B6 证据；来源、配置或行为有实质变化只补受影响验收。最终采用配置必须通过至少两条合格推荐与预算门；材料 full 等独立业务门不能被搜索通过替代。MCP 可明确延期，不能偷偷作为未验证默认路径。

最终报告：`docs/diagnostics/execution-roadmap-final.md`，逐项列架构、业务、来源、配置、部署状态。若真实库切换待授权，区分“代码/隔离验收完成”与“部署迁移未完成”。

## 12. 测试、费用和回滚规则

- 每阶段先现有相关回归＋必要故障注入，阶段切换前按迁移细则做完整离线检查；无新改动/疑点不重复全量。Windows 浏览器/MCP 子进程需正常权限环境，不能为避开环境错误放松断言或开启网络。
- 测试数据库独立，默认阻断真实网络和模型，真实检查只选择精确节点，不给全套 pytest 打 live flag。
- 本轮既有 R1 真实续跑账目为 71 次已完成请求、741,045 输入、48,953 输出；不是所有历史总用量。旧 L1 29,997 输入预留继续保留，累计 402,777/2.5M。费用未知不能写零；reasoning/output、cached/input 不重复相加。
- 历史 Treg 交接记录 15 次调用、$0.004、0 unknown、0 LLM，实际以后续账本为准。原批次不重置；Treg 与模型授权/预算分开。配置默认额度不是新增实验授权。
- 已有明确范围授权持续有效，不重复确认；新增范围、增加额度、真实账号使用、部署和用户库迁移缺少授权时，只问缺失项。此前文档中的建议测试上限不能独立当成人类授权。
- 对正确性或机制失败停止该组，保留失败样本。模型/账户/reasoning/预算不得自动换档来取得通过。
- 回滚先暂停领取和外部写入，核对租约与收据；不能把已迁移或产生副作用的任务交给旧代码重跑。保留历史读适配、费用和证据，不删除 unknown。
- 不推送、不部署、不自动申请岗位、不发送消息，不批量安装无关渠道。Adzuna、TheirStack、HarvestAPI 必选、Agent Reach 整包均不进入范围。

## 13. 每阶段交付格式与最终完成定义

每阶段报告包含：准确版本/文件范围；问题与最终行为；实际测试命令、通过/失败/跳过；模型/工具调用和成本（或未知）；保留风险与回滚点；是否允许下一阶段。保留其他会话改动，小范围组织提交，不擅自提交整个脏工作区。

完整完成必须同时满足：

- 自主决策只进入通用 AgentLoop；固定工作流不新增路由；多任务能力成为统一调度下的作业。
- 所有入口有执行归属；单一逻辑 owner；取消、预算、恢复、审核和浏览器/面试顺序正确。
- 旧活动任务已处理，旧循环/重复 owner 已退出；历史读取保留；未完成部署明确标记。
- 招聘板＋Treg 在统一架构运行，MCP 有明确采用或延期决定；无凭据有可解释的基础路径。
- 最终配置的 API 优先 B6 业务门通过，材料等独立业务待办关闭；不降低原质量标准。
- README、配置示例、架构/能力开发指南、阶段报告与代码一致；所有付费样本账目完整。

**Claude 的第一步：读取必读文件和当前差异，更新 M0 基线，然后实施 R2/M1 的公共契约与保护修复。不要重跑旧 browser-first B6，不要先安装 LinkedIn MCP，不要一次性改完所有阶段。**

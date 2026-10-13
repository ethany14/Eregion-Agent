# Treg A+B：closeout 审查与下一阶段实施交接

日期：2026-10-12。状态：**允许进入受控开发；本次仅审查和编写任务文档，未在项目中实施 Treg。**

本文件是下一位 Codex 的执行入口。详细功能边界沿用 [Treg A+B 规格](opt-v3-stage-1b-treg-ab.md)，主路线为 [optimization-plan-v3.md](optimization-plan-v3.md)。本文件补充 closeout 审查结论、执行顺序和证据缺口，不取代原规格中的资格、预算、恢复及业务验收要求。

## 1. 审查结论：可以进入，但不是全面验收通过

**同意 Claude 的 `ready_for_treg: true`，仅表示允许从已修复的默认基线开展 A+B 开发和离线验收。** 不表示阶段 2/4 应启用、不表示真实 B6 达标、不表示已经证明 Treg 会改善推荐结果。

按 [原收尾任务 §8](opt-v3-closeout-decisions-validation.md)，优化开关可以明确关闭或延期后交接，不必先把所有实验变绿。当前不存在由本次审查确认、必须先修复才能开始 Treg 契约/基础设施工作的运行阻断；证据清单仍需按 S0 补齐。

### 1.1 本次实际审查的证据

| 材料 | 判断与证据边界 |
|---|---|
| [closeout baseline](../diagnostics/opt-v3-closeout-baseline-20261012.md) | 根因描述合理：P2 已评分岗位的关键证据原本可见，缺的是明确决策与继续搜索前的约束；不能继续把它归因于信息丢失。被淘汰的已读原文无法重新取回是另一项独立缺陷。完整 actions 计数优于截断 history |
| [closeout validation](../diagnostics/opt-v3-closeout-validation-20261012.md) | 正确区分机制测试、脚本回放、真实模型和完整联网验收。阶段 4 仅是候选，阶段 2 的 B2/r1 仍失败；字符减少不能换算成实际 token/美元收益 |
| [closeout handoff](../diagnostics/opt-v3-closeout-handoff-20261012.md) | 允许在阶段 2/4 关闭的基线上交接，与原收尾定义一致。真实 B6 仍是 FAILED，来源覆盖和真实决策行为都未解决，不能全部转嫁给 Treg |
| 关键源文件身份 | `decisions.py`、`harness.py`、`request_context.py`、`loop_engine.py`、`task_host.py`、`tests/conftest.py`、`tests/test_opt_v3_closeout.py` 的 SHA-256 前 16 位全部与 handoff 一致 |
| 独立定向复核 | 本次运行现有 `tests/test_opt_v3_closeout.py`：**9 passed，1 warning，10.51s**。使用隔离临时库、禁用 live/OPT 环境继承、不写 pytest cache；未改实现代码，未运行真实模型或付费 API |
| 原始矩阵核对 | 现有 23 份逐场景 JSON 的合格数与评分输入哈希均与对应 B0 一致；四配置的 `correct`、`directory-positive` 均为 2 条合格。日志为 B0/B4/B24 各 6 passed，B2 为 5 passed、1 failed |
| 全量回归 | **2054 passed / 132 skipped 是 Claude 报告的既有结果，本次未重跑或独立确认全量总数。** 不将这组数字写成本次新运行结果 |

审查时 HEAD：`34d3e27201caa2375e9a0521b855d7bf491c45c5`，文档提交；报告中的全量测试基线为 `37a83df`。本次 9 项定向复核对应当前关键文件。开工时重新记录实际 HEAD 和已有工作区改动，不覆盖他人工作。

### 1.2 两处证据归档缺口

1. **矩阵可复现性不完整。** `.codex-runs/opt-v3-closeout-20261012/matrix/matrix.json` 有 23 项，`matrix-final.json` 有 24 项；当前目录缺少 `B2/r1-granular.json`。报告已披露该项在本地禁用断言后测量，正式测试仍因 protected overflow 失败。补充汇总中的 48,279/48,000 可以作为报告值引用，但不能冒称来自现存的标准 runner 成功产物。
2. **跳过原因数量对不上。** 现有 `skip-reasons.txt` 的计数合计 **108**，与报告的 **132** 相差 24。可能涉及统计口径或遗漏，当前证据不足以确定原因。补齐同一运行的日志/统计说明，或明确标记无法追溯；不能声称所有 132 项已逐项解释。

这两项目前是证据问题，**不据此推翻已经复核的正确性修复，也不要求为解锁 Treg 先修 B2 的可选优化**。S0 处理归档；若追溯或定向回归发现新的丢结果、重复副作用、越预算或资格缺陷，则重新关门并先修该缺陷。

## 2. 锁定基线和本轮范围

| 配置/能力 | 本轮要求 |
|---|---|
| `JOB_AGENT_OPT_SNAPSHOT_REFS` / `PROMPT_TRIM` / `STABLE_TOOLS` | `0` |
| `JOB_AGENT_OPT_HISTORY_POLICY` | `current` |
| `JOB_AGENT_OPT_VERIFY_AND_SCORE` | `0`；使用现有粒度工具 |
| 决策、读恢复、终止交付修复 | 保留，不作为可选优化关闭 |
| 模型、router/writer/scoring/verifier 推理配置 | 不变；不采纳 router low 或 writer medium |
| `JOB_AGENT_JOB_API_FIRST` / `JOB_AGENT_TREG_ENABLED` | 发布默认均为 `0`，分别控制，不因填写 key 自动启用 |
| 搜索 provider | 比较前不预设赢家；证据不足则保持未选定/关闭 |
| Crawl4AI 正文提取 | 独立默认关闭，不随搜索 provider 自动开启 |

范围仍是 **已有 Greenhouse/Lever/Ashby/Workday + Treg 三个固定端点**：`anyapi.linkedin.search.jobs`、`crawl4ai.linkedin.search.jobs`、`crawl4ai.web.scrape`。

不加入 HarvestAPI、Adzuna、TheirStack、AnyAPI full、公司/联系人发现、动态路由、通用工具市场、Crawl4AI 整站抓取或 LLM extraction。开源用户自行配置 Treg key，自己的后端直连；不建设作者托管代理、共享账户或统一计费服务。

**此前当前聊天 `work/treg-stage` 中存在未完成、未验收的实现草稿，未落入项目。它不是交接基线，不得直接复制、安装或视为已完成实现。下一位 Codex 依据项目实际代码和本规格开展工作。**

## 3. 执行顺序与各步完成条件

### S0：确认接收基线，补齐证据索引

- 阅读本文件、三份 closeout 报告和原 A+B 规格，记录 HEAD、相关文件哈希、工作区已有改动与默认开关。
- 对 §1.2 的矩阵缺项和 skip 数量给出可追溯说明。保留 B2/r1 原失败，不删除断言或调整阈值制造通过；可将测量和验收状态分开归档。暂不能找回的原始记录明确写 unavailable。
- 复用本次 9 项复核；若开工时代码变更，重跑受影响的定向集合。不要仅为了复现 passed 总数反复跑全量或付费测试。
- 输出/更新 `docs/diagnostics/treg-ab-offline-validation.md` 的基线与证据索引。本轮后续实现稳定时仍须完成受影响回归及必要整体离线检查。

完成门：基线身份明确、阶段 2/4 关闭、已知失败/缺失证据显式保留，没有新发现的正确性阻断。归档缺口不阻塞独立的公开契约阅读。

### S1：确认真实契约，不先写一个“看似能用”的适配器

交付 `docs/diagnostics/treg-ab-contract.md`，记录日期、官方 URL、完整定义/示例哈希、参数及响应映射、费用/恢复规则和未确认项。合成 fixtures、官方示例、后续脱敏真实录制分开标记。

本次公开资料核对得到以下线索，实施时再核实当前定义：

| 端点 | 已观察到的契约 | 实施关注点 |
|---|---|---|
| AnyAPI Jobs Index | POST；`query`、可选 `location`、`limit`、`cursor` 等；示例岗位位于 `output.data.items` | 目录说明 limit 可能被忽略，仍需本地累计截断；`id` 与 URL 身份一致；没有 JD 是预期行为；分页返回字段须单独确认 |
| Crawl4AI LinkedIn | POST；`query`、`location`、`start`、`limit`、`posted`；示例岗位在 `rows`，含 `job_id` | 卡片是候选，不能证明完整 JD/有效岗位/资格；缺失日期和未应用筛选要披露 |
| Crawl4AI scrape | POST；`url`、`format`、`proxy` 等；公开文档支持 `markdown`/`html` | HTTP 200 或非空 Markdown 不足以判定完整 JD；必须绑定目标身份、检查正文范围、截断、登录/验证码和多岗位污染 |

官方入口：[Treg HTTP 文档](https://treg.to/llms.txt)、[OpenAPI](https://treg.to/openapi.json)、[AnyAPI 定义](https://treg.to/catalog/endpoints/anyapi.linkedin.search.jobs)、[Crawl4AI 搜索定义](https://treg.to/catalog/endpoints/crawl4ai.linkedin.search.jobs)、[正文定义](https://treg.to/catalog/endpoints/crawl4ai.web.scrape)、[Crawl4AI Cloud 文档](https://crawl4ai.com/llms.txt)。Cloud 端点不等同于安装开源 Python 库，Treg 的特定账户访问也不等同于上游全部公开能力。

必须解决的三个边界：

1. **固定端点不自动等于固定供应商。** Treg 官方资料披露 platform overflow。确认当前账户是否可能切换、如何禁用以及响应如何识别；不能擅自修改账户设置。若无法保证本轮禁止替换的要求，则阻止该真实调用，继续其他离线工作。意外替换的结果隔离但费用照实记录。
2. **访问报价与最终实扣不同。** 鉴权用 `X-Treg-Token`，需要时加 `X-Treg-Org`；调用前确认账户 access/price，设置已验证的单次成本上限。以网关费用收据为 USD 依据，不用上游 credits 或响应 `costUsd` 替代网关实扣。
3. **未知收费不能靠重发解决。** 核实 `Idempotency-Key`、call ID、replay 的原始费用、409/410 及只读收据查询。恢复原调用、继续新调用和读取保存结果是三种不同操作；未确认契约不能猜。缺失费用或丢失响应保持 unknown，不计零。

完成门：请求构造、账户访问、来源约束和费用上界可解释；未确认端点保持关闭。仅靠目录摘要不开放真实调用。

### S2：A——配置、固定客户端、持久费用与恢复

- 使用固定端点白名单和隔离的 HTTP 客户端；复用连接，禁用自动跳转和隐式传输重试，设置连接/读取超时、整体 deadline、有界响应和并发。
- 统一配置加载：进程环境 > 项目根 `.env` > 默认值；显式空值不回退；不依赖启动 cwd，不污染全局环境；缺 key/非法预算阻止 Treg 而不破坏已有招聘板/浏览器功能。
- 补 `.env.example`、README、`docs/configuration.md` 和忽略规则。示例无密钥、默认关闭；只有 `.env` 不存在时才复制，已有文件只补字段；清楚说明用户自付、关闭方法、真实 smoke 独立 opt-in。
- 外部工具账本与现有模型账本分开，绑定 task/run/revision、逻辑操作、物理请求、端点、call ID 和费用。金额用整数 micro-USD，预算配置用精确十进制解析。
- 在同一部署数据库原子预留任务累计和 UTC 日额度；多 worker 竞争、取消迟到、进程崩溃、重启、跨日、token 轮换都不能释放未知收费或重复扣账。查询/轮询/重试也占 attempt。
- 同一逻辑操作幂等重入；在持久状态不清楚时不发新收费请求。恢复入口受开关、请求数和 deadline 控制；关闭开关不启动后台对账。响应成本超过预留要如实记录并停止，不能裁剪成预算内。
- 临时数据库验证 migration 升级/回退及测试模型注册，不迁移用户真实库。

完成门：原规格 §6 的协议、预算、并发、配置、关闭与恢复测试通过；日志/异常/配置接口不泄漏 key；默认测试无外网和真实模型。

### S3：B 的离线接线——先证明业务链，再花钱选来源

只扩展现有 `search_jobs` / `read_job` 后端实现，不向模型开放端点、HTTP header、预算或 token 参数；四种 API-first/Treg 开关组合均验证。两开关全关时保留原工具定义与旧路径。

搜索与读取顺序：

1. 按用户目标 revision 固定来源约束与过滤条件。明确公司/招聘板优先其已有 API；无来源限制时使用可信目录；明确仅 LinkedIn 时不得遍历其他招聘板。不要用几个英文关键词的正则替代完整的来源权限/目标约束；中英文、否定、来源变更都需要反例。
2. 先处理已观察、去重后仍可行动的候选与已评分待决策项，再为真实缺口补搜。完整正文可复用；未知字段不是合格证据，卡片不作为已完成推荐。
3. 正文获取沿用已有 ATS/HTTP 能力，必要时用已验证且开启的 Crawl4AI 抓取；显式区域观察、证据缺失/冲突/过期、身份不明时保留浏览器核验。页面曾被打开本身不强制再浏览。
4. 浏览器传输受阻与 API 传输健康分开，岗位 identity、资格拒绝和去重共享。API 并非绕过登录、验证码或非公开访问限制的后门。
5. 始终保留 `read → qualification → import → score → recommend`、`decide_job` 门、最终回复与落库一致性。取消/旧 revision 结果可记账，但不得推进任务。

完成门：通过真实 CareerService/TaskHost/harness + 临时 DB、模拟模型与 HTTP 的业务正反例；不改 `evaluate_search`，正例至少两条合格、已评分且持久化的推荐。另验证只有一条/零条、Associate 缺证据、关闭岗位、地点冲突、正文污染、重复页、重启、取消和预算终止。完整 API 证据场景浏览器调用为 0，必要核验分支仍真实可达。模拟评分不证明真实评分质量。

### S4：受控 AnyAPI/Crawl4AI 对比——沿用已授权额度

只有 S1–S3 对应离线门通过后，才能进入独立 live API 通道。用户已授权本范围，不重复索取相同授权；缺 key/账户访问/overflow 条件时记录 blocked，不索要用户把 key 发到聊天里，不替用户改设置。

整个实验使用一个持久 batch ID 和隔离数据库：**累计 $0.10、最多 20 次网关请求、每次 `/call/` 上限 $0.01；任何一项先到即停。真实 LLM 调用数必须为 0。** 该预算不得分给 Claude 提议的真实模型 12-run/3M-input 实验。

- 冻结 5 组用户目标范围内的职位/地区/日期条件，两家分别首屏查询一次，共 10 次；语义不等价的过滤项明确列未应用，不猜 geo ID。原始返回数与最多 10 条本地结果分开记录。
- 从合并去重且初筛通过的结果，按事先规定的规则选择最多 5 个不同公开岗位，用 Crawl4AI 各抓一次；不足不额外补搜凑数。
- **修正预算分配口径：原规格的“其余 5 次”也必须容纳账户、access/price、收据等网关查询，不是另外赠送的重试额度。** 如预检需 5 次，则 10+5+5 正好 20，已无重试余量；更多必要查询要减少样本并披露，或停止，不能绕过保护/拆批充值额度。
- 重启、失败、换 provider、跨日均不新开额度。未知成本占用预留，不新 key 重试碰运气。不增加真实模型、收费浏览器或额外抓取做人工验证。
- 输出 `docs/diagnostics/treg-provider-comparison.md`：每组原始/去重/可判断相关数、独有与交集、缺失字段、未应用筛选、错误、抓取完整性、身份一致性、实测耗时、实际实扣/unknown、全部请求清单。所有比例列分母，不把小样本写成全站召回率。

完成门：能清楚区分“搜索候选质量”和“正文提取质量”；AnyAPI 不含 JD 不直接扣分。选择一个搜索源的配置建议须基于相关候选/可验证正文/实际费用的证据；两家无明显优势、都失败或未测时允许不选，不强行集成成功。抓取是否值得开启另作决定。

### S5：交付与关闭状态

- 交付代码、测试、配置/README、契约报告、离线验证报告和对比报告；本轮实际执行到哪一步、哪里 blocked/未测写清楚。
- 固定受影响测试集合无新增失败，保留原 B6 fixture/标准与 closeout 修复。已有 B2/r1 失败须按配置归因，不能混入默认新回归里伪称全部通过或泛化为环境问题。
- 生产开关继续默认关闭，测试配置不写回维护者 `.env`。不自动提交/推送/部署，不修改真实用户库、原始 paid logs 或 `.codex-runs/b6-evidence/`。
- 外部实扣、unknown 预留和模型费用分别展示；汇总中费用未知必须可见。关闭 Treg 保留历史证据与账本，已有招聘板/浏览器继续可用。
- 最终区分：可开发、离线机制通过、真实 API 已测、来源建议、真实模型/联网 B6 通过。**本轮即使完成，也不能据此把真实 B6 的历史 FAILED 改成 PASSED。**

## 4. 继续延期的事项

阶段 2 的 protected overflow 与真实收益、阶段 4 的真实决策模型对照、完整联网 B6、Writer medium、A3 人工标签、scoring/verifier 推理实验、条件式 RAG 继续单列。真实模型批次缺美元预算与完整费用约束，不能仅凭 token 上限开跑；后续另定批次，不挪用本轮 API 额度。A5 用户暂缓状态不重开。

## 5. 可直接交给 Codex 的任务指令

> 从 `docs/specs/treg-ab-execution-handoff-20261012.md` 开始，结合 `opt-v3-stage-1b-treg-ab.md` 实施 A+B。先完成 S0 的基线/证据说明，保留阶段 2/4 关闭和真实 B6 失败状态，再按 S1 契约、S2 配置/账本/客户端、S3 离线业务路由、S4 小额 API 对比、S5 交付推进。不要使用当前聊天中未验收的暂存实现草稿。开源用户自行配置 Treg key；仅三个固定端点；已有招聘板 API 优先、浏览器补充核验；HarvestAPI、Adzuna、TheirStack 不进入范围。先通过离线门，再在同一持久批次中执行已授权的 $0.10/20 次/单次 $0.01 API 测试，所有查询与重试计数，真实 LLM 为 0。缺 key 或契约/账户约束未满足时继续完成可独立的离线工作并准确报告阻断，不自动扩大范围或额度。保留既有资格与两条合格推荐验收标准，生产默认关闭，不自动提交、推送或部署。

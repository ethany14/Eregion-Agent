# Eregion 成本与时延优化方案 v2（2026-10-11）

> **已被 `optimization-plan-v3.md` 取代**（2026-10-11）：本版的工具占比、B6 r1 描述、历史裁剪方案与质量门有误，见 v3 第 1 节。

在 Codex 9 阶段路线基础上，按本项目实测成本结构和当前业界做法重排。原则：**先量后改、按实测占比排序、每阶段一个开关可回滚、质量门不降低**。

## 1. 结论摘要

1. 最大的两块钱是**推理 token**和**每次 router 调用重发的大 snapshot**，不是工具定义，也不是网络速度。
2. 顺序调整为：计量补齐 → 推理量按用途配置 → 缓存友好的请求结构 → snapshot 按需取回 → 机械步骤结晶为确定性工作流 → 来源层改用官方 API → （有条件）检索。
3. 砍掉/暂缓：工具按需加载（工具仅 0.7K 字符）、默认摘要式压缩、子智能体、推测执行、多模型抢答。
4. B6 的根本问题是来源被拦截，属于"来源层"而不是"性能层"，单列为阶段 5，并与 Codex 正在做的 B6 离线回放衔接。
5. 评分相关优化必须等 A3 人工标签（或以 A1 一致性 + 离线夹具作为临时门）——没有标准答案就无法证明"质量不退化"。

## 2. 实测基线（本轮证据）

| 场景 | 调用 | input | output | 其他 |
|---|---|---|---|---|
| B6 r1（成功找到 2 岗） | 20 主 / 36 provider | 304,067（缓存命中 100,594 ≈ 33%） | 14,767 | 118 s |
| B6 r3（来源阻断） | 37 主 | 553,369 | 24,171 | 262 s |
| B6 历史（修复前） | 52–58 主 | 715K–1.1M | ~30K | 337–512 s |
| B6 单次请求构成 | — | System 13,368 字符 + tools 739 + replay 3,494 + **snapshot 42,732** | — | snapshot ≈ 70% |
| C16 面试反馈 | 6 | 5,228 | 8,139 | p50 15.7 s（reasoning low，原 110 s） |
| E5 求职信 | 4 | ~5,000 | ~9,000，其中 reasoning ~7,900 | — |
| A1 稳定性样本 | 64 trial | 238,553 | 517,877 | 中位 43.5 s/trial |
| A5 八岗批量 | 21 | 31,859 | 14,273 | cold 89 s（用户已暂缓性能项） |

代码事实：
- 请求顺序为 `System(prompt) → history → Human(live snapshot)`（`request_context.py:600`），snapshot 在末尾，结构上适合前缀缓存。
- 超预算时 `replay.groups.pop(0)` **从前端逐组淘汰历史**，每次淘汰都会改变 System 之后的前缀，使缓存失效。
- `job_agent/model.py` 只为 `extraction` / `agent` / `fast` 用途读取 reasoning 配置；评分、材料 writer、verifier 等其余用途走供应商默认值。
- 供应商为 OpenAI 兼容接口（`ProviderCompatibleChatOpenAI` + `LLM_BASE_URL`），usage 已返回 `cached_input_tokens` 和 `reasoning_tokens`，现有账本可以直接计量。

## 3. 设计原则（业界依据）

| 原则 | 依据 | 本项目落点 |
|---|---|---|
| 用最少的高信号 token；引用优先，按需取回（just-in-time） | Anthropic《Effective context engineering》；工具结果清理是最轻、可逆的手段 | 阶段 3：snapshot 改为引用 + `read_context` |
| 缓存是 harness 设计问题：前缀逐字节稳定、只追加、易变内容放末尾，监控命中率 | OpenAI Prompt Caching 201；Codex CLI 与 Claude Code 的实践；案例中把易变字段移到末尾后命中率 23%→71% | 阶段 2 |
| 有缓存时保留全文常常比摘要更便宜；规则放常驻位置，不放可被压缩的历史 | Bouchard 2026 评测；"45 轮后违反规则"的案例 | 不默认做摘要压缩；用户条件保持常驻 |
| 推理量按步骤匹配难度；静态全低会掉质量 | ARES（arXiv 2603.07915）：按步选择推理量，降本 52.7% 且不掉分 | 阶段 1：按用途配置 + 失败升级 |
| 已验证的探索固化为确定性工作流，并能自动降级 | Progressive Crystallization（arXiv 2607.07052）：确定性占比 0→45%，单事件成本降 70% 以上 | 阶段 4 |
| 工具少时保持全量加载，按需加载反而是开销 | Hermes tool-search 文档；按需加载适用于数十上百个工具的场景 | 不做工具按需加载 |
| 网页类 agent 的成本和失败常来自搜索/来源层 | Parallel.ai 2026；Greenhouse 公开 API 需要逐公司 token，没有目录 | 阶段 5 |
| 检索先用 FTS5，向量作可选增强（RRF 融合） | starpod/ai-memory 等项目；小样本基准上混合检索优于纯 FTS | 阶段 6（有条件） |

## 4. 分阶段方案

每个阶段：一个环境开关（`JOB_AGENT_OPT_<名>=0` 即回滚）、固定评测集、数字目标。上一阶段达标后再开下一阶段，便于归因。

### 阶段 0 · 计量补齐（小）
- 沿用现有 `provider_usage` 账本，只补两项：
  - 耗时拆分：排队、模型、工具、落库、前端可见；
  - 每次请求的构成：system / tools / history / snapshot 的字符数，以及缓存命中率。
- 冻结评测集：
  - B6 离线回放（Codex 在建）；
  - C16、E5 自动检查；
  - A1 8 对样本；
  - 8 岗批量。
- 统一产出 `docs/benchmarks/opt-<阶段>-<日期>/`，内容为 manifest 加用量。
- **目标**：每个 provider attempt 都可归因；任意两次运行可以按任务对比。

### 阶段 1 · 推理量按用途配置（收益最大、最先做）
- 为每类用途显式配置 reasoning：router、extraction、scoring、pack_writer、claim_verifier、interview_question、interview_feedback。
  - 方式：新增 `LLM_REASONING_<PURPOSE>`；未配置时沿用现状，保证可回滚。
- 起始建议：
  - router `low`；
  - verifier / claim decisions `low`；
  - interview `low`（已验证）；
  - writer `medium`；
  - scoring 维持现状，等质量门。
- **失败升级**：校验失败、grounding 未通过或结构错误时，只对该步重试一次并提高一级推理量。这是 ARES 思路的确定性简化版，不训练路由器。
- reasoning 配置进入分析缓存签名，避免新旧结果混用。
- **目标**：
  - E5 reasoning token 降 ≥50%；
  - B6 output 降 ≥30%；
  - C16、E5 自动检查全部保持通过。

### 阶段 2 · 缓存友好的请求结构
- 核对 `harness.prompt` 和工具列表逐字节稳定：不含时间、ID、预算、用户数据，顺序固定。
- 历史淘汰改为**阶梯式**：超预算时一次淘汰一大块（例如最早的一半，或到固定检查点），代替每轮 `pop(0)`。这样前缀在多数轮次中保持不变。
- 若供应商支持 `prompt_cache_key`，按 task 设置。上线前用单次实测核对 `cached_input_tokens` 是否上升。
- 命中率进入阶段 0 的报表，回退时告警。
- **目标**：B6 缓存命中率从 33% 提到 ≥60%；单次请求成本按命中折算下降。

### 阶段 3 · snapshot 按需取回（输入大头）
- snapshot 中只**常驻**：
  - 用户原始条件与授权；
  - 当前请求；
  - 简历摘要；
  - 候选身份与健康状态；
  - 受阻来源；
  - 已评分 / 已推荐结果的要点。
- 改为引用、经 `read_context` 按需读取：
  - 研究页面正文；
  - JD 全文；
  - 旧工具结果；
  - 历史进度消息。

  ContextArchive 已有机制，主要是扩大使用范围。
- 旧工具结果清理：保留最近 N 个原文，其余替换为"引用 + 一行摘要"，原文持久保存、可回取。
- **目标**：
  - 平均请求 ≤25K 字符（现约 45–60K）；
  - B6 主 input 降 ≥40%；
  - B6 离线回放和既有请求体积测试全部通过。

### 阶段 4 · 机械步骤结晶为确定性工作流
- 新增复合工具 `verify_and_score(url)`：read → 资格过滤 → import → score，在一次 router 决策内完成。每步独立落库，可从检查点恢复；任一步失败都原样返回给模型。
- board 搜索结果先做确定性预筛（角色词、地点、级别证据），再交给模型。
- `recommend_job` 和最终回复仍由模型决定，现有校验一律不跳过。
- 只结晶在回放和真实记录中反复成功的序列；对应校验出现回退时自动降级回逐步调用（Progressive Crystallization 的晋升 / 降级机制）。
- **目标**：B6 router 调用 ≤25（r1 为 20，历史 52–58）；对 B6 离线回放零行为差异。

### 阶段 5 · 来源层（B6 的根因）
- 优先使用官方 / 公开 API：
  - Greenhouse / Lever / Ashby / Workday 公开接口（已支持）；
  - 联邦岗位用 USAJOBS 官方 API；
  - Adzuna 等聚合 API 需先核对条款，并由用户自行申请 key，不代办。
- **公司招聘板目录**：Greenhouse 没有公开目录，需要维护一份按领域 / 城市整理的公司 token 清单（人工审核、带来源和更新时间），供 board 搜索使用。
- HTTP 客户端复用、按来源限流；只对 API 类来源做有界并发（≤3）。对有 bot 防护的站点不并发、不绕过，被拦截时如实披露。
- 用户本人登录的 Chrome 作为可选来源（已有 opt-in），用于 LinkedIn / Indeed。
- **目标**：B6 在 LinkedIn / Indeed 被拦截时，仍能通过 API 来源找到 ≥2 个合格岗位；真实 B6 连续 3 次中 ≥2 次通过。

### 阶段 6 · 检索 / 记忆（有条件启动）
- 启动条件：阶段 3 之后，长正文 / 历史仍占请求 >30%，或出现跨会话回忆需求。
- 方案：SQLite FTS5 + 元数据过滤（申请人、岗位、版本），精确取回原文；向量检索可选，用 RRF 融合。
- 硬规则：
  - 评分始终覆盖完整冻结需求目录，检索不到证据不得判 missing；
  - 未授权的跨申请回答不复用；
  - 实时状态直接查库，不走检索。

### 阶段 7 · 异步与展示（大部分已完成）
- 沿用 C16 的 FIFO、异步反馈和短锁。
- 新增：最终回复流式展示、真实进度。首次可见时间和完成时间分开计时。

### 阶段 8 · 离线评测降本
- A1 稳定性、标签评测等非实时任务走供应商 Batch 接口（若支持，通常约半价）。冻结版本对比，证据归档。

## 5. 不做 / 暂缓

| 方法 | 决定 | 理由 |
|---|---|---|
| 工具按需加载 | 不做 | 工具 739 字符；会破坏稳定前缀；当前任务所需能力可能不可达 |
| 默认摘要压缩 | 不做 | 有缓存时保留更省；规则在摘要中容易丢失。改用引用 + 清理 |
| 子智能体 | 暂缓 | 只有独立长任务被证明能降低总成本时才考虑 |
| 推测执行、多模型抢答 | 不做 | 增加费用和恢复复杂度 |
| 语义答案缓存 | 仅限通用知识 | 申请人事实、评分、资格、审批必须严格查询 |
| 训练推理量路由器（完整 ARES） | 暂缓 | 先用失败升级的确定性版本，数据够了再评估 |

## 6. 质量门

| 门 | 适用阶段 | 标准 |
|---|---|---|
| B6 离线回放 + `evaluate_search` 不改 | 2、3、4、5 | 全部通过，行为零差异或差异经审核 |
| C16 / E5 自动检查 | 1、2、3 | 全部通过；E5 另需人工风格审阅 |
| A1 一致性 | 1（scoring）、6 | spread 不高于当前样本（max 5.6） |
| 评分准确性 | 任何评分改动 | 需 A3 人工标签；标签到位前评分用途不降推理量 |
| 全量测试 | 全部 | 不低于当前 1770 passed |

## 7. 排期与当前工作的关系

1. **现在（与验收并行，低风险）**：阶段 0 计量补齐 + 阶段 1 的推理量审计（先审计，不改默认值）。
2. **B6 离线回放合入后**：阶段 2 → 阶段 3（回放就是回归门）。
3. **然后**：阶段 4、阶段 5（阶段 5 直接服务 B6 真实验收）。
4. **按条件**：阶段 6；阶段 8 随评测需要启动。
5. 用户此前暂缓了 A5 性能项。本方案启动前需确认重新开启；A5 的 60 s 门槛不变。

## 8. 风险

- **阶梯式淘汰会让单次请求变长**：需要设上限，并用阶段 0 的数据验证净成本。
- **复合工具隐藏中间状态，增加排错难度**：每步落库，并在工具结果中返回每步状态。
- **推理量下调可能悄悄降低质量**：先审计，再按用途逐个开启，每个都过质量门。
- **公司 token 目录维护成本**：限定在评测覆盖的领域和城市，注明来源和更新时间。

## 参考

- [Anthropic: Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- [Claude cookbook: context engineering tools](https://platform.claude.com/cookbook/tool-use-context-engineering-context-engineering-tools)
- [Context engineering: memory, compaction, tool clearing（tianpan.co）](https://tianpan.co/blog/2026-02-26-context-engineering-memory-compaction-tool-clearing)
- [Louis Bouchard: context engineering 2026](https://www.louisbouchard.ai/context-engineering-2026/)
- [OpenAI: Prompt caching guide](https://developers.openai.com/api/docs/guides/prompt-caching) / [Prompt Caching 201](https://developers.openai.com/cookbook/examples/prompt_caching_201)
- [Prompt caching is a harness design problem（DEV）](https://dev.to/amitrix/prompt-caching-is-a-harness-design-problem-not-an-api-toggle-2c2b)
- [DigitalOcean: prompt caching hit rate in practice](https://www.digitalocean.com/community/tutorials/prompt-caching-in-practice-hit-rate)
- [Codex CLI prompt caching](https://codex.danielvaughan.com/2026/04/21/codex-cli-prompt-caching-maximise-cache-hits-cost-reduction/)
- [ARES: Adaptive Reasoning Effort Selection（arXiv 2603.07915）](https://arxiv.org/html/2603.07915)
- [Progressive Crystallization（arXiv 2607.07052）](https://arxiv.org/pdf/2607.07052)
- [Hermes Agent: Tool Search](https://hermes-agent.nousresearch.com/docs/user-guide/features/tool-search)
- [GitHub Copilot: improving token efficiency](https://code.visualstudio.com/blogs/2026/06/17/improving-token-efficiency-in-github-copilot)
- [Parallel.ai: LLM cost optimization for AI agents](https://parallel.ai/articles/llm-cost-optimization-for-ai-agents)
- [Code execution with MCP（AIMultiple）](https://research.aimultiple.com/code-execution-with-mcp)
- [FTS vs hybrid memory benchmark（SoulClaw）](https://blog.clawsouls.ai/posts/fts-vs-hybrid-memory-benchmark/)
- [USAJOBS API: Search Jobs](https://developer.usajobs.gov/tutorials/search-jobs)

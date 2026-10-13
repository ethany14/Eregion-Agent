# 模型主导岗位判断：本轮收尾与 Claude 接手报告

日期：2026-10-13。项目：`C:\Users\zhiyu\Documents\JobHunterAgent`。执行分支：本地 `main`。

本轮代码提交：**`a37f6e4c48c2c4e2ace6e3b4b64b5f5bac6c7a36`**（`Move search qualification and fit semantics into model assessments`）；上一轮真实搜索基线为 `55d16bb`。本报告是下一轮执行入口。用户要求先收尾交接，因此本轮没有继续启动完整的付费搜索。

## 1. 结论与用户要求

**本轮完成的是“语义判断交回模型”的代码修复；10–15 个岗位的真实业务验收仍未通过。** 不得把离线回归、定向语义测试或保存文本的模型复判写成新的真实搜索成功。

用户最近明确要求：

- 模型判断岗位、资格和匹配含义，不能靠 harness、关键词或脚本替模型下结论。
- 默认 LinkedIn MCP + 公司招聘板 API；Treg 保持关闭，可选 BYOK，不改为统一托管。
- 目标仍为纽约 junior Data Analyst，搜索 15 个，至少交付 10 个经过核验、评分、满足条件的推荐；不得降低职位、地点、级别或个人资格要求凑数。
- 允许合理小额付费测试，但需要报告真实调用、token、耗时和失败；没有美元账单时不得声称已执行美元硬上限。
- 仍使用 `eregion` 下的唯一 AgentLoop；本轮不新增执行器、兼容架构或第二套搜索 loop。

旧 `docs/specs/claude-unified-execution-plan-20261012.md` 和 R1/R2 门修订保留历史价值，但其中旧目录名、两条推荐门和 Treg 路线不能覆盖上面的最新要求。无需重做已完成的迁移，也无需先过旧 browser-first B6。

## 2. 本轮已落地的改动

### 2.1 搜索资格由模型输出带证据的结论

入口：`backend/eregion/domain/search_qualification.py`；持久化与验证：`backend/eregion/runtime/career/qualification.py`。

- 模型读取原始用户要求与抓取到的完整岗位文本，逐项判断 role、location、seniority、vacancy，输出 `met / unmet / unknown / not_requested`、理由和原文引用。
- 每组最多四个岗位，输入上限 48,000 字符；超长输入保留 unknown，不静默截断以便通过。模型失败也不会切回规则判断。
- 不再依靠固定 junior 标题、0–3 年/4+ 年阈值、talent-network 关键词或公司办公室地址决定合格与否。
- 地点语义在提示词中要求区分城市内部行政区与独立邻近城市；vacancy 始终是必核验项。
- 引用必须绑定原岗位/用户原文；岗位 ID 必须完整且唯一。无效引用或缺项不获得通过。
- 未变更的请求、原文和模型配置复用判断；变化时失效。模型调用计入当前执行 owner 的预算，取消或用户改意后丢弃过时结果。
- `verify_and_score_jobs` 先取得文本，再批量资格判断，只为满足条件的岗位导入/评分。单个评分和推荐入口也使用同一判断，不留下浏览器路线旁路。

### 2.2 Jev 仍负责评分；去掉语义规则覆盖

主要文件：`domain/jev_fit/core.py`、`domain/jev_fit/resolve.py`、`domain/job_extraction.py`、`domain/domain.py`、`domain/fast_match.py`、`api/services/fit_analysis_service.py`。

- Jev 继续做要求分类与候选人证据判断；所有原文片段，包括标题、福利和公司背景，都交给模型分类。代码不再用 section/boilerplate 词表强制 required、preferred 或 context。
- 普通模型评分路线也由模型提取要求目录。移除本地正则目录默认路径；旧 `JOB_AGENT_MAIN_CATALOG` 不再改变行为。
- 去掉匹配结果后的工具名、教育进行中、年限正则与词语重合度覆盖；字面出现技能名也不再自动判 matched。
- 主模型仍决定最终推荐、排除或待补证据。数学加权由代码执行，不等于代码判断岗位含义。
- 引用缺失或模型未提供判断时保留 unknown，不伪造 missing 或数值评分。
- 更新匹配版本与 Jev 分类版本/缓存签名；**不能把旧版评分缓存当作新版语义判断证据。**

### 2.3 重复读取与验收证据

- 模型基于原文作出的候选排除，在同一用户轮次、同一正文下持久化。切换页面视图或其他工具不能把已排除岗位恢复成“新进展”；真正正文变化或新用户输入才允许重新判断。
- 批量流程保留读入、导入、评分进度；恢复时复用结果。修复抓取返回规范化/跳转 URL 时批次条目绑定的问题。
- 新增盲审 `tools/evals/search_semantic_audit.py`：只给审计模型原始用户要求、标题、地点和正文，不给生产判断、评分或推荐理由。独立计量和限额。
- `tests/test_default_route_batch_live.py` 已接入盲审，但**本轮没有运行新版完整 live 测试**。
- 离线 workflow 的模型是显式替身；历史 replay/规则测试仅验证协议、状态和旧报告兼容，不能作为新模型质量证据。

代码仍保留结构解析、搜索 query 构造、候选排序、去重、身份和引用校验、预算、取消、缓存以及评分计算。这份报告不声称项目所有正则表达式都被移除。后续不得把排序信号升级成硬性资格结论。

## 3. 测试证据与实际状态

### 3.1 离线回归

最终结果：**615 passed、6 skipped、4 subtests passed，212.46 秒，退出码 0**。共 38 个测试文件；一个现有 Starlette/AnyIO 弃用警告。跳过项未计作通过。新增 URL 跳转身份回归已包含在该最终集合中。

测试集合与摘要保存到 `docs/benchmarks/model-owned-search-20261013/`；最终原始本地日志在 `.codex-runs/model-owned-search-closeout-verified.log`。较早的 `...closeout.log`、`...closeout-recheck.log`、`...closeout-final.log` 是修复过程中的失败记录，不能误当最终结果。覆盖资格判断、身份/引用隔离、批量与单个路线、跨请求复用、崩溃恢复、模型排除后的重复读取、两种评分路线、预算及取消。

初次回归暴露了旧测试替身依赖“本地目录自动补齐”和“错误 ID/未知被改成 missing”的问题。本轮更新替身使其返回真实输入 ID 和原文来源，并调整语义规则断言为模型结论与来源约束断言。没有为了测试通过恢复生产语义规则。

这是一组有针对性的后端回归，不是整个仓库、前端或所有模型配置的全量验收。

### 3.2 最后两次完整真实搜索（本轮迁移之前）

| 运行 | 代码 | 推荐数 / 已评分 | provider 调用 | 已知输入 / 输出 token | 耗时 | 结果 |
|---|---|---:|---:|---:|---:|---|
| `default-batch-20261013-main-6` | `32c998c` | 4 / 7 | 60：24 主模型 + 36 Jev | 444,635 / 25,780 | 336.76 秒 | FAILED；一次超时、usage 不完整 |
| `default-batch-20261013-main-7` | `55d16bb` | 7 / 9 | 60：21 主模型 + 39 Jev | 532,575 / 40,898 | 579.60 秒 | FAILED；预算停止，usage 完整 |

run7 发现 53 张候选卡，保存 47 份岗位正文；LinkedIn 为 4 次搜索 + 46 次详情调用，达到 50 次来源额度。`read_context` 为 6 次。以上是历史测量，不代表新代码的成本、准确率或成功率。

### 3.3 本轮付费语义探针：没有新来源抓取

工具：`tools/evals/search_qualification_compare.py`。只测试人工预期的合成案例，并复判 run7 已保存的公开岗位文本。未重新搜索、未正式评分、未生成新推荐。

| 探针 | 结果 | provider 调用 | 已知输入 / 输出 token | 耗时 |
|---|---|---:|---:|---:|
| `semantic-qualification-probe-20261013-1` | 当时 8 个定向案例通过，但回放有两次超时，usage 不完整 | 7，完成 5 | 30,301 / 37,796 | 688.34 秒 |
| `semantic-qualification-probe-20261013-2` | 7/8；错误地把 Brooklyn 判为不在纽约，未继续回放 | 2 | 2,495 / 5,759 | 69.87 秒 |
| `semantic-qualification-probe-20261013-3` | 当前四维提示词；10/10 定向案例通过，47 个保存岗位完成复判 | 15，全部完成 | 63,285 / 50,353 | 620.58 秒 |

探针 3 的 47 个岗位中：模型初筛合格 9 个，至少一项 unmet 的 13 个，只有 unknown 未通过的 25 个。四维总计 28 个 unknown 标签；这是标签数量，不能当作 28 个岗位。9 个初筛结果没有经过新版 Jev 评分、独立盲审或人工逐条验收，**不能计作 9 条成功推荐**。

探针 3 验证毕业生同义表达、标题与资历矛盾、同事资历误借、公司地址误借、相近职业、Brooklyn、否定表达、非英语初级描述、人才库、正常职位附带人才库链接。样本很小且同一个模型参与生产和盲审，不能据此声称可靠率 100%。

三个探针累计 24 次 provider 尝试；其中两次缺失 usage，已知 token 合计只是下界。所有 `cost_usd` 为 null，因为没有账单价格证据。测试工具按调用数/input token 限制开销，不能冒称精确美元封顶。

## 4. Claude 接手后的执行顺序

### C1：先核对基线和剩余风险，勿重建架构

1. 阅读本报告、当前 Git 状态及上述入口；确认本地 `main` 包含本轮提交，保护其他人的未提交改动。
2. 运行本报告保存的离线回归集合。确保模型判断、引用校验、预算与取消约束继续成立。
3. 阅读探针 3 的原始 `gold-cases.json`、`replay.json` 与 usage；将 25 个 unknown 原因分为正文缺失、资格本来不明、输出引用无效、模型判断不稳。用原文复核，不能用新的规则 oracle 自动“纠正”模型。
4. 特别核查未来开始日期、都市圈范围、跨职业混合标题、个人资格（如 VIE、语言、工作授权）与纯搜索资格的区别；它们不能仅靠有数值分数就推荐。

### C2：先小样本验证新版评分，再优化效率

1. 从保存的完整 JD 中选少量有代表性的岗位，用新版 Jev 分类/评分验证要求覆盖、required/preferred、福利背景、否定和候选人证据。禁止注入旧评分缓存。
2. 核查原文切分是否丢失限定词，Jev 批量是否串岗位证据；用带原文的模型判断和人工可审查样本检查语义质量。
3. 测量 qualification、Jev、必要主模型复核分别的调用、token、延迟。减少重复输入、复用稳定证据、适当批量化；不要重新加入关键词资格裁决，也不要为节省 token 省略限制条件。
4. 当前 `model_unavailable`/unknown 会针对相同输入缓存，以阻止循环重读。评估一次受预算约束的显式重判策略；没有新证据的无限重试不允许，未知也不能改成合格。
5. 模型推理/输出成本仍显著：探针 3 用时超过十分钟且输出约五万 token。四岗位批量 + low reasoning 不是已证明的最优参数；再做实验前列清假设、预算和停止条件。

### C3：扩大合适候选覆盖，保持条件不变

1. 优先保留模型认为等价的职业/初级表达，利用 LinkedIn/provider 可用过滤条件和招聘板数据提高检索召回。
2. 列表阶段信号可以辅助排序和选择下一批；含糊标题、都市圈、无级别标签不能靠脚本直接当成合格或永久排除。
3. 当前 run7 只有 47 份文本、探针 3 只有 9 个搜索初筛合格；即使评分全过也不足 10 条。下一轮需要改进检索覆盖或补足确实缺失的证据，不能只提高预算然后重复读同一批岗位。
4. 全程继续同一 AgentLoop 和执行 owner；新来源或评分仍作为工具/固定步骤挂入现有链路。默认来源、Treg 关闭状态保持一致。

### C4：有针对性的改动通过后，再跑一次完整真实验收

使用 `tests/test_default_route_batch_live.py::test_default_route_ten_to_fifteen`，新输出目录、隔离 SQLite、合成候选人；不要操作用户生产数据库。

- 原目标 15，最低 10；职位/地点/级别/个人资格不放宽。
- 执行 provider 上限 60 次（包含主模型、qualification、Jev 与嵌套调用），输入 token 上限 1,000,000；执行等待期限 900 秒。
- LinkedIn 来源额度 50 次；MCP 调用和模型调用分开记账，不意味着可以额外花 50 次模型调用。
- 盲审单独最多 6 次 provider 调用、200,000 输入 token。900 秒执行等待不包含随后盲审，报告两段及总耗时。
- 单次结束就检查证据和瓶颈；不要无修改自动重跑或连续耗尽额度。若需超过本基线，用新证据说明收益与新增预算，不默默增加上限。
- provider 超时/usage 未知、预算停止、不足 10 条、未知资格冒充合格均不能写 PASS。只保存真实推荐与明确失败原因。

验收交付：commit、调用版本/配置（脱敏）、调用账本、来源账本、抓取与评分覆盖、重复读取、原始 transcript、blind audit、最终推荐 URL/分数及未通过原因。按任务级总量统计，不能只报主模型 token。

## 5. 可直接使用的本地命令与资料

仓库根目录运行。先做离线检查：

```powershell
$env:PYTHONPATH = 'backend;tools'
$checks = Get-Content docs/benchmarks/model-owned-search-20261013/validation-files.json -Raw | ConvertFrom-Json
.venv/Scripts/python.exe -m pytest @checks -q -p no:cacheprovider --tb=short
```

准备好 C4 后才运行付费验收；不要把它当成普通回归自动执行：

```powershell
$env:PYTHONPATH = 'backend;tools'
$env:JOB_AGENT_LIVE_DEFAULT_BATCH = '1'
$env:JOB_AGENT_ANALYSIS_WARMUP = '0'
$env:MCP_CONFIG_PATH = (Resolve-Path .codex-runs/linkedin-career-mcp.json).Path
# 选一个全新目录；测试拒绝覆盖已有样本。
$env:OPT_LIVE_OUTPUT = '.codex-runs/default-batch-claude-model-owned-01'
.venv/Scripts/python.exe -m pytest tests/test_default_route_batch_live.py::test_default_route_ten_to_fifteen -q -s -p no:cacheprovider
Remove-Item Env:JOB_AGENT_LIVE_DEFAULT_BATCH
```

测试结束必须清理所有 `JOB_AGENT_LIVE_*`/live-replay 开关后再跑离线测试，因为这类开关会改变测试网络隔离。配置中已有的 key 不要打印、复制进报告或提交。

本机资料（不在 Git 中）：

- `.codex-runs/default-batch-20261013-main-6/`、`...-main-7/`：历史真实测试；run7 含隔离测试 `career.sqlite3`、`fit.sqlite3`、原文与账本。
- `.codex-runs/semantic-qualification-probe-20261013-{1,2,3}/`：探针原始结果和 `usage.sqlite3`。
- `.codex-runs/linkedin-career-mcp.json`：官方 MCP 配置；已授权、独立登录资料在 `.codex-runs/linkedin-comparison-session/profile`，独立环境在 `.codex-runs/linkedin-comparison-venv`。
- MCP 当前固定 `mcp-server-linkedin==4.27.0`，只用 `search_jobs / get_job_details / close_session`，启动为 `--no-auto-import`。不要改用用户日常 Chrome profile，不重做登录、不导出凭据。会话失效则如实报告。

Git 内可移交的脱敏摘要位于 [`../benchmarks/model-owned-search-20261013/`](../benchmarks/model-owned-search-20261013/)。原始大文本/SQLite/会话目录不得随报告提交或上传。

## 6. 本轮交接边界

本轮到代码修复、离线检查、语义探针证据、提交及本报告为止。不再监督或向 Claude 自动发消息。未推送远端，未投递、部署、迁移用户库，也未启动新的完整付费搜索。

下一轮优先级：**新版模型评分质量与成本 → unknown 补证据/候选覆盖 → 单次真实 10–15 岗位验收**。成功标准保持原要求；不回到规则替模型判断的方向。

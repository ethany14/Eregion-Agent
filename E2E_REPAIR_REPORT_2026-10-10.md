# E2E 修复与复验报告 — 2026-10-10

**本地提交说明（2026-10-11）**：用户已明确授权 commit；此前验收轮“未stage/commit”保留为历史记录。提交前暂存检查发现两处EOF空行，已仅修格式，未改变功能/阈值/失败结论。r4保留为提交前中间快照，链接标题对齐后的最终清单为git-review-scope-r5.json；旧r3原205哈希/206含自身check exit0保留为历史，不覆盖。只提交本地，推送/PR仍待批准，无收费重测或清理。

**F2交付（2026-10-11，本轮新revision）**：[拟提交范围与具体缺口](E2E_GIT_REVIEW_SCOPE_2026-10-11.md)、[r5精确路径/SHA清单](docs/diagnostics/remaining-2026-10-11/git-review-scope-r5.json)。旧F2 r1/r2均保留历史；r2原199哈希/200含自身、本地/监督独立check exit0，不能代替本轮F3/链接校正后的新复核。38原件留本地并发布索引，33个catalogue r1文件哈希保留。F2限审阅/审计范围，其余A–F状态不提高。未stage/commit/push/PR/批量清理/收费重测。

**F3只读增量**：[tmp候选与引用保护审计](docs/diagnostics/remaining-2026-10-11/tmp-cleanup-dry-run-r1.md)；监督6857文件/5807780140bytes/189组基线与当前逐组比较，目录引用保护子树，成功合成夹具须有实际通过XML/唯一测试归属/源码/新目录重建依据，其他保持。完整逐文件清单留本地tmp，精简归档含哈希和候选明细；全部deletion_eligible=false，没有打开/修改原库或执行重建。15项工具契约通过，F3实际清理仍未完成。矩阵A5 producti0错误链接已校正为实际product0，未重跑A5。监督E5新增5项独立通过不算真实风格通过。

**C16/E5本轮离线增量**：C16反馈失败持久化被下一题RPC长锁阻塞，before3失败→after3通过1取消失败；原SQLite证实CANCELLED被晚草稿改回FAILED，终态保护后原4项通过7.751s，最终相邻95通过3跳过/63.389s。监督21项及终态4项SHA核对，重叠不合计unique；真实延迟仍失败。[准确before/after及边界](docs/diagnostics/remaining-2026-10-11/interview-failure-lock-offline.md)。E5生产建议/评测筛查重复邀请规则不一致，4失败1通过→47通过2付费跳过；无新稿，verifier不变，原真实稿仍风格失败。[E5离线增量](docs/diagnostics/remaining-2026-10-11/cover-style-screen-offline-r1.md)。

**2026-10-11 当前验收状态以 [A–F 逐项矩阵](E2E_ACCEPTANCE_MATRIX_2026-10-11.md) 为准。** 下方全量结果是此前阶段的历史验证，不代表完整 A–F 通过。B6 backend 原输入已通过、不重复付费；analyst 最新 phase4-recovery 失败（52主calls/336.75s、0保存岗位/0推荐、715985主及总input、30044output、完整账本，needs_input/no_progress）。原 interval-completion 1推荐且超预算失败仍保留，本轮不收费重跑。A5 去重实测cold89.015s超过原60s，**用户要求暂缓性能优化、不再反复付费**；要求误删准确性继续修复。C16 主模型p50=110.097s超过原30s，异步实测又遇连接失败，均未通过；E5冻结真实稿风格仍失败，v8仅离线回归通过。原始失败与用量保留，推送/PR 等待批准。

对应原始报告：[E2E_TEST_REPORT_2026-10-10.md](E2E_TEST_REPORT_2026-10-10.md)。诊断基线：`95cfda9`；本次结论针对其上的工作区修复。

**2026-10-11本轮离线增量**：A1完整JobAnalysis目录身份/正文span/ID验证、显式主服务输入与持久缓存隔离、实际attempt计数已修。原retry4报3及25bullet七次报4有回归，provider与adapter/未知usage明确区分；139通过4跳过，批量预检7通过、后续相邻47通过+4subtests。v3三失败/v4一失败及before均保留。默认路线仍待真实用户选择，显式输入不等于默认绑定或真实稳定性通过。C11两个保存ID同岗位1run却报2starts已复现修复，本地29通过；真实模型链仍未测。见[诊断](docs/diagnostics/remaining-2026-10-11/catalogue-attempt-offline.md)及SHA索引`catalogue-attempt-offline-r1.json`。根矩阵全文历史“进行中/待补”已对齐终态，#8本地Chrome通过、B6最新失败不变。本轮没有收费测试、真实投递、推送或PR。

核心运行时、简历结构和无上传框复核问题已修复并通过专项及全量回归。最终全量 **1300 passed / 0 failed / 2 skipped**，前端 **23/23**。Jev 的分段、限定条件、缓存和区间消费已改进，但复杂真实 JD 仍有较宽的不确定区间，不能宣称评分问题全部解决。

## 1. 验证结果

| 验证 | 结果 | 范围 |
|---|---|---|
| 最终 Python 全量（包含浏览器） | **1300 passed / 0 failed / 2 skipped，710.98s** | 全仓库测试；独立临时数据库；另有 16 个 subtests 通过 |
| 前端 Node 测试 | **23 passed / 0 failed** | 对话、问答、时间线、Markdown、模型用量、界面及 API 辅助逻辑 |
| 上下文/UI 专项 | **34 passed / 0 failed** | 实时面试信息、星期编辑器、材料页面及上下文压缩 |
| 原先面试浏览器失败复验 | **2/2 passed** | 首页和已保存职位入口的搜索→评分→材料审核→申请→面试；所在中间专项曾有一个新增上下文断言失败，该问题后在上述 34 项中复验通过 |
| 四申请人材料流转及版本专项 | **25 passed / 0 failed** | 简历投影→证据库→材料快照→PDF，及材料文档版本 |
| 控制异常专项 | **1 passed / 0 failed** | 快速结束动作失败后进入可处理状态，防止任务悬在 queued |
| 真实 API 算法矩阵 | **24/24 返回，无调用错误** | 4 位匿名虚构申请人 × 3 类职位 × Jev/主模型 |
| 真实主模型规划 | **1 passed / 0 failed，45.92s** | 模型自行选择浏览器→读取→导入→评分→生成材料→完成；职位与材料工具使用本地夹具，未投递 |
| 日间/夜间视觉检查 | **8 个状态已检查** | Forge 和订阅编辑器；1440px/375px；无横向溢出及 SVG 路径错误 |

专项之间存在重叠，不能将它们累加为独立用例总数。全量测试之前的中间版本为 `1288 passed / 2 failed / 2 skipped`；两项失败均为面试对象身份问题，后续专项已复验通过。该中间结果不是最终验收结果。

两项全量跳过分别为默认关闭的付费真实模型规划测试（本轮已单独开启并通过），及 Windows 环境无法创建符号链接的测试。全量还有一条 Starlette/AnyIO 弃用警告，没有运行错误。

## 2. 修复内容及其边界

### C1：空读循环、面试结束与上下文失真

- 连续三次无新增证据的重复步骤触发停止；状态进入 `needs_input`，错误码 `no_progress`，保留已完成工作并明确告知任务尚未完成。首次读取不计入重复；等待正在执行的子任务不会误判为空转。
- 无进展计数持久化并绑定用户请求版本，新请求重置计数。计数与状态更新使用任务锁，避免用户中途发消息后旧步骤覆盖新请求。
- 即使上下文过大，仍保留面试 ID、问题、状态和材料版本等可操作摘要。对象列表按对象压缩，历史细节可通过引用读取。
- 浏览器回归揭示了额外根因：面试对象同时含职位 ID 和面试 ID，原逻辑优先按职位识别，可能用过期职位摘要替换当前面试。现在优先使用 `mock_interview_id`；紧凑投影也不会仅因 JSON 字段较少被误判为旧版本。
- “结束面试”等明确指令、且仅有一个活动目标时，直接调用现有结束接口，使用已保存回答生成报告；无需额外推理模型选择动作。控制失败会进入明确可处理状态，不会留在 queued。

**边界：** 熔断防止持续浪费调用，并不保证任意自然语言任务必定自动完成。多对象操作的完整性仍需要从保存的实际结果核对；没有将模型普通进度文本改成任务完成。

主要实现：`agent_runtime/task_host.py`、`task_loop.py`、`request_context.py`、`career/harness.py`。

### C2：雇主、日期、学历和技能限定丢失

- 新增保守的原文结构解析，覆盖竖线布局、`职位 - 雇主, 地点 (日期)`、英文月份、ISO 年月、换行表头和常见学历表头。
- 分开同一章节中的雇主和学历记录，证据引文仍来自原文；无法识别的前导文字独立保留，避免归给邻近雇主。
- 材料快照中的 Summary/Profile 和无元数据的 Resume/Other 不再被重建为工作经历。
- PDF 渲染保留学历正文，避免把 `in progress`、`expected May 2027`、`not graduated` 等限定隐藏。
- 技能拆分忽略括号内逗号，保留 `AWS (EKS, RDS)`、`Java (prior)`。
- 来源含日期但经历/学历仍退化为没有所有者和日期的整章时，材料结构校验返回 `unresolved_source_structure`，阻止继续把退化材料判为合格。

四位申请人的端到端结构回归覆盖分析师、后端工程师、在读硕士和护士转 UX；逐项确认投影与证据库快照所有者一致，并从输出 PDF 提取文本核对雇主、日期、学位和限定。

**边界：** 解析器覆盖明确布局，不猜测任意模板的隐含关系。既有退化材料属于历史版本，本次没有批量改写生产数据库；应重新评分/生成并审核新的材料。

主要实现：`job_agent/resume_layout.py`、`jev_fit/projection.py`、`quality.py`、`pdf_rendering.py`、`agent_runtime/application_pack/workflow.py`。

### C3：没有上传框时无法进入复核

`document_refresh` 仅在当前页面或之前观察过的复核字段存在相应上传控件时形成上传义务。没有上传框的申请不会被不存在的上传任务永久挡住；前一步观察过、仍需更新的上传义务会保留到后续页面。简历和求职信使用一致规则，其他必填字段校验继续生效。

主要实现：`agent_runtime/auto_apply/autofill.py`。

### C4：Jev 分段、判断阻断与推荐不兼容

- JD 按句子、列表和明确章节标题划分原文跨度，平铺文本不再必然成为一个巨大的复合问题；`Python and SQL` 等并列要求不会拆成改变含义的条件。
- 明确的 Required/Preferred 章节决定要求权重；语义不明确的提取和个人条件分类有一次有界澄清。
- 完整匹配仍要求原要求的全部组件与限定得到支持；相关经验只支持 partial，不替代 full。针对不确定完整匹配，增加一次完整来源澄清，避免局部摘录的否定被误当成全局缺失。
- 阈值保持 `.85/.15`；不通过降低阈值强行出分，不在 Jev 路径偷偷回退主模型。
- 提供给概率模型的展示空白规范化，缓存键同步处理；原始简历/JD、来源跨度和引用保持原样。解析器及策略变更进入缓存签名。
- 推荐允许有界分数区间，明确附上不确定性。订阅最低分过滤使用区间下限，不使用中点伪造点分数；过期分析、非当前简历及其他已有推荐限制仍生效。

**状态：部分解决。** 简单明确 JD 的矩阵结果明显改善，复杂真实 JD 的不确定提取和复合要求仍需校准，详见第 4 节。

### 其他已修复的问题

| 问题 | 修复与验证 |
|---|---|
| 周一到周五被保存成每天 | 增加持久化 `weekdays`；编辑器可选星期；跳过周末且保留本地时间/DST。旧配置默认每天，兼容读取。测试覆盖纽约秋季 DST 切换。 |
| 提醒摘要出现 “Send continue” | 摘要基于已保存推荐条数和真实终止原因生成，不复制最后一条模型进度。 |
| 跨会话共用申请导致替换或取消 | 在工作线程启动前保存 `origin_task_id`，变更动作检查所有者；重复申请归属其他会话时拒绝变更。旧的歧义共享记录也拒绝跨会话写入。 |
| 手动接管后错误自动继续 | `pause_requested` 或 `paused_for_control` 为真时禁止自动恢复申请。 |
| Forge 手机标题溢出、logo 路径无效 | 修复折行、手机间距及 SVG 参数；浏览器断言并检查双主题截图。 |
| 审核导致文档版本看似递增 | 材料 API 单独提供 `document_version`，界面显示内容版本；原 `version` 继续用于审核并发控制。测试确认审核改变状态版本而不伪造新文档版本。 |

## 3. 真实 API 对比：四申请人 × 三职位

主模型为 `muse-spark-1.3-contributor`，Jev 为 `jev-1.13.0`。使用独立匿名虚构文本，没有读取或发送保存候选人的联系方式、简历或数据库记录。主模型分支禁用快速决策路由，比较完整主模型分析与 Jev-only 分析。

每格为 **Jev / 主模型**。区间表示 Jev 保留未知条件，没有伪造点分数。

| 申请人 | 后端：Python API、生产 K8s、Go | ML：PyTorch、已完成 CS 硕士、Python | UX：Figma、用户访谈、医疗经历 |
|---|---|---|---|
| 数据分析师 | `[0,40] / 20` | `20 / 20` | `0 / 0` |
| 资深后端工程师 | `100 / 100` | `20 / 20` | `0 / 0` |
| 在读 CS 硕士/ML 实习生 | `[0,40] / 40` | `80 / 60` | `0 / 0` |
| 护士转 UX 设计师 | `0 / 0` | `0 / 0` | `100 / 100` |

Jev 产生 10/12 点分数、2/12 区间；主模型产生 12/12 点分数。24 组全部返回，无调用错误。

关键差异：

1. 数据分析师的简历写 Python 数据管道，没有明确写 API 开发。主模型判 partial，Jev 保留 unknown。
2. 学生有 FastAPI 原型和 Python 经验，明确没有生产所有权；生产 K8s 和 Go 均缺失。Python API 项主模型 matched，Jev unknown，因此给出 `[0,40]`。
3. 学生的硕士仍在读：Jev 对“已完成硕士”判 partial，主模型判 missing，因此总分 80 vs 60。两者都没有判 matched，也没有声称已毕业；partial 权重与严格完成门槛的产品语义仍需统一。

原始 `comparison.json` 保留执行时的人工参考标签；后续复核发现前两处 Python API 的参考标签写反，已经在可复跑脚本中纠正。此报告按实际原文解释差异，不拿这些有歧义的参考标签计算所谓准确率；也不改写原始模型输出来美化结果。

| 指标 | Jev | 主模型 |
|---|---:|---:|
| 12 组总墙钟耗时 | 15.160s | 272.995s |
| 平均每组耗时 | 1.263s | 22.750s |
| 汇总 model_calls | 53 | 19 |

这是一轮顺序执行的小样本，包含同一矩阵内部的缓存复用；Jev 调用是概率问答批次，主模型调用是结构化生成，不能仅凭调用数量比较费用或推断正式环境性能。没有取得足以计算完整账单的价格和 token 数据。

对同一简单后端 JD 增加尾部换行、或压成一行，两种变体都复用已持久化的语义决策，新增模型调用 **0**，保持 `100 / [100,100]`，引用仍使用各自原文坐标。

证据：[comparison.json](docs/diagnostics/repairs-2026-10-10/matrix/comparison.json)、[format-variants.json](docs/diagnostics/repairs-2026-10-10/matrix/format-variants.json)。

## 4. 未解决和未重新验证的部分

### 复杂真实 JD：仍不能认为 Jev 点分数可靠

对原诊断中保留的公开 Stripe 后端 JD，使用匿名虚构后端简历重新调用真实 Jev；这三次探针关闭持久化缓存，观察冷请求。

| JD 形态 | 单元数 | 提取不确定单元 | unknown 匹配 | 分数区间 | 调用错误 |
|---|---:|---:|---:|---|---:|
| 结构化 | 39 | 4 | 8 | `[22.22,100]` | 0 |
| 平铺 | 38 | 5 | 9 | `[20,100]` | 0 |
| 结构化加尾部换行 | 39 | 5 | 9 | `[20,100]` | 0 |

这比“整个平铺 JD 变成一道问题”更可检查，但仍不足以稳定区分候选人。冷请求仍可能波动，规范化和缓存没有证明提供方输出在所有冷请求上确定。区间下限低于订阅门槛时，该职位会被保守排除；这是显式不确定性带来的代价，不能把零推荐自动解释为没有适合职位。

后续应针对真实 JD 的邀请/排除说明、软技能复合条件和跨要求关联建立独立人工标注集，先测误判和弃判，再校准提取与判定。不能用这次 12 个简单组合取代完整准确性评测。

证据：[最终复杂 JD 探针](docs/diagnostics/repairs-2026-10-10/refined/)；上级目录中的同名探针属于澄清策略调整前的中间版本，应以 `refined/` 为准。

### 其他边界

- 本轮完整自动化使用脚本模型和受控页面覆盖流程；真实 API 矩阵针对评分。没有再次把四位虚构用户的每一段长对话都跑在真实推理模型和招聘网站上，不能声称原报告中的 7/11 预算耗尽已全部在真实长对话中消失。
- LinkedIn/Indeed 的登录墙、Cloudflare、第三方网站变化和主模型长任务稳定性，本轮没有重新验收；代码修复不会保证外部网站可访问。
- 原报告关于重启后“已暂停的父会话重新开任务”的完整触发链尚未取得稳定复现。本次验证的是已确认的申请接管自动恢复竞态，不能将其等同于解决所有重启问题。
- 没有向真实雇主提交虚构申请，没有改写旧材料、证据或测试原始数据库，也没有修改 `.env`。

## 5. 测试维护与复跑方式

除新增针对根因的回归外，更新了旧测试与现有契约的分歧：完成需显式 `finish_task`；上下文读取通过游标和 `context_evidence` 返回原文；来源输入采用现有 `type_from_source` 协议；视觉测试先提供真实可用浏览器夹具；学历抽取允许一次完整原文直接成功。保留原有行为、事实边界和安全断言，没有通过降低产品阈值或删除失败测试凑绿。

真实主模型规划测试首次运行失败：原夹具只模拟 `read_job` 的发现服务，通用浏览器没有拦截模拟 URL，因此访问真实 Lever 并读到 404，模型如实拒绝编造材料。修复这个测试夹具，使两条读取路径都返回受控职位文本后，复验完成 `browser_open → read_job → import_job → score_job → generate_materials → finish_task`，生成两份草稿且没有申请运行。首次失败日志也保留，不能将它当作产品“假装已生成材料”的证据。

```powershell
# 全量自动化，独立临时目录
$env:JOB_AGENT_BROWSER_TESTS='1'
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp=tmp/repair-final-full --junitxml=tmp/repair-final-full.xml

# 前端
node --test tests/test_web_ui.mjs tests/test_model_usage.mjs tests/test_lens_api.mjs tests/test_chat_markdown.mjs tests/test_career_timeline.mjs tests/test_career_chat.mjs tests/test_apply_answers.mjs

# 真实 API，需已有费用授权与配置；换输出目录可获得独立缓存
.venv/Scripts/python.exe scripts/e2e_repair_evaluation.py --live --output docs/diagnostics/repairs-2026-10-10/matrix-rerun

# 真实主模型规划 + 本地模拟职位及材料工具
$env:JOB_AGENT_LIVE_CAREER_TEST='1'
.venv/Scripts/python.exe -m pytest -q -s tests/test_career_flow.py::test_configured_model_directs_real_career_tools_with_synthetic_sources --basetemp=tmp/repair-live-career-rerun
```

新根因回归在 `tests/test_e2e_repairs.py`；浏览器视觉/星期选择在 `tests/test_job_alerts_browser.py`；材料版本在 `tests/test_material_routes.py`。最终日志、JUnit 与截图归档到 `docs/diagnostics/repairs-2026-10-10/`。
# 2026-10-11 持续验收入口

当前逐项状态、监督反例、失败记录与最终证据以 [A–F 验收矩阵](E2E_ACCEPTANCE_MATRIX_2026-10-11.md) 为准，最新修复细节见 [持续验收补充](docs/diagnostics/remaining-2026-10-11/latest-status.md)。B6 backend 原输入已通过；analyst 最新 phase4-recovery 52调用/0推荐仍失败，已归档不收费重跑。C12/C14/C15 本地 Chrome 前端/API 链路已通过；C16 异步/FIFO/恢复局部通过，原主模型 p50=110.097s 超过30s，异步真实复验连接失败保留，fast未配置。A1/A2/A4缺证据、A3人工待审；A5八岗60s按用户要求暂缓，原89.015s失败保留。推送/PR继续等待用户批准。


## 2026-10-11 Phase4 analyst 终态及离线修复

B6仍失败：52主调用/336.75s、0保存岗位/0推荐，needs_input/no_progress；主与任务输入均715985、输出30044，账本完整。原两合格持久推荐/60calls/各100万不变，不收费重跑。末24动作不是完整52轨迹；已保存原答复、失败XML和完整账本及哈希。离线相邻95通过，新增Chrome/候选/拒绝25通过0skip，只证明局部修复。见[详细失败与离线修复](docs/diagnostics/remaining-2026-10-11/analyst-phase4-offline-repair.md)。

原1–18/E1–E6/F1–F3以完整矩阵为准：A1/A2/A4缺证据、A3人工待审、C16真实延迟失败保留；A5性能用户暂缓，backend不重复；E5风格仍失败，继续冻结文本离线策略/回归，不启动付费生成。

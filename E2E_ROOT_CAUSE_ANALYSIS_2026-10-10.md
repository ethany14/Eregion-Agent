# E2E 严重问题根因分析

> 后续修复和复验结果见 [E2E_REPAIR_REPORT_2026-10-10.md](E2E_REPAIR_REPORT_2026-10-10.md)。本文保留修复前的诊断事实及代码基线。

分析对象：`E2E_TEST_REPORT_2026-10-10.md`。代码基线：`95cfda9`。

本次工作是诊断，不是修复。读取了原始 SQLite 测试数据库、自动化失败日志、生成材料及算法对比结果，并在当前代码上复现关键路径。未修改产品代码、`.env` 或原始测试数据库；没有执行真实职位投递。

## 1. 结论

报告中的四个 Critical 问题都有依据，但不是一个问题造成的所有症状。

| 问题 | 已确认的直接原因 | 证据强度 |
|---|---|---|
| C1 循环耗尽预算 | 完成必须显式调用 `finish_task`；重复读取只得到提示，没有停止或降级机制；上下文压缩使可操作对象藏到引用后面，进一步诱发寻找、重复读取 | 原始状态 + 本地脚本模型复现 |
| C2 简历丢失结构 | Jev 的简历投影只识别特定竖线和日期格式；真实测试简历被压成整章来源。材料流程继承空元数据；PDF 又不渲染学历正文；验证只检查与退化后的来源一致 | 同一份原始材料重新渲染 + 结构验证复现 |
| C3 无上传框无法进入复核 | `document_refresh.resume=true` 被直接当作未完成上传，与页面是否存在上传框无关；三个复核入口都检查它 | 直接函数复现 + 调用链核对 |
| C4 Jev 评分不可用 | 分段依赖换行；要求提取同时依赖“是否要求”和“是否优选”的置信判定；提取不确定的条目被跳过匹配，却保留全部权重；后续分类不确定也会阻断结论 | 原始评分数据 + 新的真实 Jev 诊断 |

这些问题相互放大：C3 让申请子任务无法结束，C1 继续消耗调用；C4 让推荐工具拒绝结果；C2 将评分阶段产生的粗糙结构传递到正式申请材料。

## 2. C1：为什么一直读上下文，却不完成任务

### 2.1 运行时没有对重复读取实施硬限制

代码位置：

- `agent_runtime/task_host.py:83`：普通文本只作为进度发布，不完成任务。
- `agent_runtime/task_host.py:142`：每次工具调用后的进展检查。
- `agent_runtime/task_host.py:158`：检测最近历史中的重复指纹。
- `agent_runtime/task_host.py:162`：重复结果只增加 `progress_feedback`。
- `agent_runtime/career/harness.py:842`：重复读取后的自动等待，仅在存在运行中的申请子任务时生效。
- `agent_runtime/task_loop.py:168`：预算耗尽后输出 “Send continue”。

模型忽略提示时，运行时仍允许继续调用相同工具。搜索、材料呈现、面试结束都没有正在运行的申请子任务，因此不能通过上述自动等待退出。

本地用始终读取同一条记录的脚本模型，在真实 `TaskLoop` 上设置 8 次预算：

```json
{
  "status": "needs_input",
  "model_calls": 8,
  "read_count": 8,
  "feedback_count": 7,
  "last_message": "I have saved the work so far. Send continue to allow more steps."
}
```

说明重复检测能识别问题，但不会阻止问题。增加总预算只能让这类失败更贵。

### 2.2 面试无法结束，实际没有走到结束接口

Daniel 原始会话：`be0dbe00-87af-41e4-85b7-ccede22d3471`。

数据库中已经有活动面试 ID `047eb5fc-f51a-4a8f-bdee-361070e36b7f`。最终状态仍为 `awaiting_answer`。

运行时记录显示：

- `ctx-e15717d2ce9aecd378bfe06c` 对应的面试列表共 3,912 字符，累计读取 **60 次**，已无未读内容。
- 另一个引用明确返回 `historical=true`、`no_new_evidence=true`。
- 收尾历史全是 `read_context`，没有 `control_interview`。
- 面试事件表没有结束/生成报告事件。

所以这次故障发生在 Agent 决策与工具选择层，不能归因为“面试报告生成接口超时”。`control_interview(action='end')` 的能力已存在；`MockInterviewController.end()` 根据保存的问答组装报告，不需要额外调用模型。相关直接工具流程测试在本轮复跑中通过。

### 2.3 上下文压缩是放大因素

`agent_runtime/request_context.py` 在请求超出预算时，会把整个 `interviews`、`materials`、`jobs` 数组换成 `context_ref`。大型工具结果摘要保留 `application_id`、`pack_id` 等字段，但没有专门保护 `mock_interview_id`、当前问题和可执行的结束动作。

这会让模型转去寻找引用中的对象。虽然读取进度和 `context_evidence` 已提供内容，仍然缺少“对象已知、状态已读、应该执行控制动作”的运行时保证。原始面试日志正出现这种模式。

### 2.4 修复应解决什么

1. 按用户请求版本记录连续无进展，区分首次读取、读取新范围与重复空读。
2. 达到阈值后禁止继续同类空读，进入受限收尾或明确的故障停止；不能编造已完成结果。
3. 将面试 ID、问题 ID、状态、材料版本、可执行动作保留在小型实时摘要中。
4. 为“结束面试”“暂停”等明确控制指令提供稳定路由，避免要求模型反复寻找已知 ID。

## 3. C2：为什么“验证通过”的简历没有雇主、日期和学历

### 3.1 元数据首先在 Jev 简历投影阶段丢失

`job_agent/jev_fit/projection.py:23–55` 的识别条件很窄：经历/学历条目需要至少三段 `|` 分隔，最后一段还必须完整符合年份、年月或 `Present/Current` 的正则。

Daniel 原始测试简历使用普通简历布局和英文月份。重新调用 `resume_projection()` 得到：

- 整个 EXPERIENCE 只产生 **一个**来源。
- 该来源 `heading/organization/start_date/end_date` 全为 `null`。
- EDUCATION 来源的上述字段也全为 `null`。

原始数据库保存的 `resume_analysis` 与复现结果一致。因此，损坏不是下载 PDF 时才发生，也不是简历上传提取失败：入职资料提取与 Jev 评分简历投影是不同路径，前者成功不代表后者能保留结构。

### 3.2 材料流程把整章证据当作一个来源

传播链：

```text
Jev resume_projection：整章证据、空元数据
  → WorkspaceAnalysisService 导入 CareerEvidence
  → resume_analysis_from_snapshot：按现有元数据分组
  → 缺失职位标题时退回 source_section，例如 "Experience"
  → 两个雇主的经历变成一个 "Experience" 条目
```

`agent_runtime/application_pack/workflow.py:100` 使用 `role/employer_or_project/source_section` 构造条目，没有恢复原始分条结构。

此外，`agent_runtime/evidence/repository.py:338` 将 `summary` 和 `other` 都映射为 experience 类别。材料快照再重建时，原来的 Summary、Resume 也被作为 experience 来源处理；这是额外的来源类型损失。

### 3.3 PDF 渲染进一步隐藏学历

`job_agent/pdf_rendering.py:114–148`：

1. 将与章节名相同的条目标题隐藏，例如 `Education`、`Experience`。
2. 仅对非 education 条目渲染 `bullets`。

本例学历只剩 `heading='Education'`，真正的学位和学校保存在 bullet 正文里。标题被隐藏，正文又不渲染，所以整个学历条目没有输出内容。

本次从原始存储的 tailored resume 再次渲染并提取 PDF 文本，以下四项全部缺失：

- `B.S. in Computer Science`
- `University of Illinois`
- `Lakeshore Payments`
- `Prairie Logistics`

### 3.4 为什么验证没有拦住

对原始材料快照和原始草稿再次调用 `verify_resume_structure()`：

```json
{"passed": true, "issues": []}
```

`job_agent/quality.py:415` 主要检查草稿元数据是否等于来源元数据。来源本身已经退化为空值或章节名，草稿继承它就能通过。验证还检查引用、所有权、事实支持，但没有检查：

- 原始简历中多个雇主是否仍为多个条目；
- 原始已有雇主、职位和日期是否被丢弃；
- 学历正文是否最终出现在 PDF 中。

所以 `verification.passed=true` 不等于“原始结构完整、最终 PDF 完整”。

### 3.5 修复应解决什么

应让 Jev 评分复用独立、结构完整的简历分析，或明确保留无法解析的条目并阻止其直接生成正式材料。不能为了获得元数据把整个经历章绑定给第一个雇主。

材料验证必须检查原始来源结构的保留；PDF 验证必须检查学历、雇主和日期实际可见。仅在 PDF 中打开学历 bullets，能修复学历消失的表现，但不能修复上游两个雇主已合并的问题。

## 4. C3：为什么没有上传框也一直找上传入口

`agent_runtime/auto_apply/autofill.py:73`：

```python
pending = ['resume'] if refresh.get('resume') else []
```

这里没有检查 `fields`。而 cover letter 分支会检查当前或历史复核字段是否有对应文件控件。

`AutoApplicationRepository.create()` 在传入 `material_refs` 时设置 `document_refresh.resume=true`；`open_application_url()` 即使使用原简历，也传入 `material_refs={}`，因此同样触发。

直接复现：

| 输入 | pending_documents 结果 |
|---|---|
| 没有任何字段，resume refresh=true | `['resume']` |
| 只有姓名输入框，resume refresh=true | `['resume']` |
| 没有任何字段，cover letter refresh=true | `[]` |

随后以下入口都因 pending documents 拒绝复核：

- `agent_runtime/auto_apply/agent.py:427`
- `agent_runtime/auto_apply/runner.py:196`
- `agent_runtime/auto_apply/loop.py:874`

成功上传才会清除 refresh 标记，但页面根本没有上传入口，所以状态无法满足。用户说“没有上传框”不会改变这个代码条件。

需要区分“已知存在的文件字段需要替换”与“尚未观察到上传字段”。多步骤 ATS 还需记录前页文件字段与最终上传状态，不能仅凭当前页无字段就一律免除上传。报告提出的一行判断能解决简单表单，但完整修复必须覆盖这类多页情况。

## 5. C4：为什么 Jev 又快又省，却几乎不出分

### 5.1 平铺 JD 退化为一道复合问题

`job_agent/jev_fit/core.py:115` 的 `job_units()` 依据空行、行首 bullet、部分章节标记拆分；它不按普通句号拆分一行长文本。

所以复制粘贴/网页清洗后成为一行的 JD，会整体作为一个 unit。简介、职责、资格、福利混合在同一个 yes/no 问题中，要求分类自然容易不确定。

### 5.2 提取阶段的门槛会阻断后续匹配

`core.py:150` 同时询问：

- 这段是不是候选人要求？
- 这段是不是明确 preferred/optional？

只有第一问为 true、第二问可确定时才分类为 required/preferred。`boolean()` 的阈值为 ≥0.85 / ≤0.15，中间全部 unknown。

即使“这是一个要求”已经确定，只要 preferred 判断不确定，整条仍变成 `extraction_uncertain`。`core.py:187` 随后直接跳过该条目的证据匹配。

这些条目不是被排除，而是作为 required、weight=2 的 unknown 继续参与区间计算。再叠加 `core.py:274` 对提取未知的点分数禁用，结果就是宽区间。

### 5.3 结构化 JD 也还有额外阻断

对成功提取的要求，是否属于个人条件的 `c` 分类若不确定，匹配状态仍保持 unknown。focused pass 只对部分 `f/r` 问题工作，不修复提取分类或 `c` 分类；且只用明确正向结果覆盖，不能用负向精读结果确认缺失。

因此，不能把修复简化为“加一个句号切分”或“降低阈值”。当前错误来自串联判定、上下文分段与不确定传播策略；降低阈值可能把无依据结果变成确定分数，需要带人工标准答案的校准。

### 5.4 新的真实 API 复现

使用脚本内硬编码的虚构工程师经历，无姓名、邮箱、电话或真实申请人数据；公开职位使用原报告保存的 Stripe Backend JD。三次均无 provider error。

| JD 形式 | units（含职位抬头） | 提取 unknown | 匹配 unknown | 最终结果 |
|---|---:|---:|---:|---|
| 结构化 | 14 | 5 | 7/11 | `[30,100]`，无点分数 |
| 压成一行 | 1 | 1 | 1/1 | `[0,100]`，无点分数 |
| 结构化末尾追加换行 | 14 | 4 | 6/10 | `[33.33,100]`，无点分数 |

追加换行后的 unit 数量没有改变，但提取分类变了。代码把原始文本直接送给模型，并以原始内容生成缓存身份，因此这一变化会重新走判断路径。这证明对语义等价格式缺少稳定性保证；三次实验不能单独证明提供方随机性的具体机制。

### 5.5 与推荐/提醒的接口不兼容

`agent_runtime/career/harness.py:369` 的 `recommend_job` 在 `match_score is None` 时直接拒绝。提醒的阈值接口也只支持数字。

所以一方面提示词说“区间也是已完成的评分”，另一方面推荐能力必须拿到点分数，两个契约不一致。即使放宽 `min_score`，也先被 `recommend_job` 的空分数门槛挡住。

修复需要同时定义评分与推荐策略：例如保守下界满足阈值时允许带不确定性的推荐，或按明确授权选择另一评分路径。不得把区间中点伪装为实测点分数，也不应无声回退主模型。

## 6. 其他高风险问题的原因

### 6.1 周一到周五被保存为每天：已确认

`agent_runtime/career/alerts.py:21` 的 `AlertConfig` 没有 weekday 字段，`next_due()` 总是当天或次日。模型配置工具调用中也没有保存周几的信息，却在 `finish_task` 中宣称 “Weekdays”。

使用报告对应时间重算得到 `2026-10-11T13:00:00+00:00`，纽约周日上午 9 点。不是时区换算错误，是需求没有对应的数据模型和调度逻辑，同时自然语言确认未经结构化结果校验。

### 6.2 提醒摘要出现 “Send continue”：已确认

`agent_runtime/career/alert_scheduler.py:91` 附近直接取会话最后一条 assistant message 作为 digest，没有区分成果摘要、进度消息和预算停止通知。

Maya 这次提醒的最终历史仍在浏览、读取页面，不能断言这次“0 推荐”直接由 Jev 空分数造成。C1 的耗尽是该次已见失败；C4 是即使之后走到评分也会遇到的独立阻碍。

### 6.3 主模型慢、分数浮动：原因范围已定位，不能过度断言

- `job_agent/job_extraction.py` 要求提取所有资格、职责和条件，并拆成原子项；长 JD 按句子组分批，每批同时带全部源上下文。
- 输入包含完整职位文本时，职责、泛化期望和资格都可能进入评分集合，扩大输出和匹配工作量。
- `job_agent/domain.py:565` 的算术是确定的，并按 source group 计分；不能说单纯拆成更多原子项就一定线性拉低分数。
- 要求集合、分组和 matched/partial 判定仍由模型生成，语义相近但不同的输出会改变评分。
- 当前 `job_agent/model.py:96` 已设 `temperature=0`，所以“把温度改成 0”不是修复。
- 超时按单次请求配置，不是整次分析 120 秒封顶。并发下的长提取/匹配可能使某次请求触发 timeout，而端到端时间又可超过 120 秒。

原报告通过追加 footer 绕过缓存来测试方差，测到的是“语义相近、输入不同”的稳健性，而不是严格的“相同字节冷跑随机方差”。需要分别控制输入、缓存和并发，才能量化提供方随机性及排队延迟各占多少。

### 6.4 跨会话共用申请及互相取消：代码已支持该故障链

`auto_apply/repository.py:107` 的去重以 posting identity 为界，没有会话所有权。`career/harness.py:695` 捕获 DuplicateApplication 后直接复用旧 run，并把它关联到新的会话。`CareerService.cancel()` 会取消该会话关联的申请 run，不检查其他会话是否也依赖它。

需要明确“共享同一职位结果”与“拥有一个可取消的执行实例”的边界。只修改前端提示无法解决相互取消。

### 6.5 接管后会话失效：代码中存在自动恢复竞态

`auto_apply/loop.py:136` 的 `_resume_after_handoff()` 在验证墙消失后自动恢复；即使 `paused_for_control=true` 也允许恢复，并清除 pause、增加 revision。

而 `browser_control()` 要求 pause 仍存在、revision 一致。用户输入验证码导致导航后，后台自动恢复可能使后续 frame/Done 请求失效，符合报告中的 409。

该链条可以解释接管失效，但原始 “Browser control could not complete” 包装了 Playwright 具体异常；没有保留该异常的安全诊断信息，不能确定其与同一个竞态完全同源。

### 6.6 重启后恢复“已暂停”任务：尚不能认定已定位

`TaskLoop.__init__()` 和 `AutoApplicationRepository.recover()` 都检查 pause 标记。不能根据报告描述直接认定所有暂停任务都会错误恢复。

必须确认重启前父会话与子申请各自的 `status/pause_requested/paused_for_control`、恢复事件和新 run 的创建来源。现有恢复会自动恢复部分未显式暂停的 hybrid run，跨会话共享也可能造成父子状态不一致。这项仍需保留现场定向复现。

## 7. 21 个失败测试的重新分类

本次针对 8 个相关模块复跑，结果：**18 failed，102 passed，5 skipped，4 subtests passed**，49.26 秒。未在本轮重新执行全部 Chrome 浏览器测试或整个 1,275 项套件。

原始 `pytest.log` 的全量结果确为 **21 failed，1252 passed，2 skipped**。原报告把 shared loop 失败写成 11 个，实际失败列表中为 **10 个**。

| 组别 | 本次发现 |
|---|---|
| shared loop，10 个 | 脚本模型最终只返回普通文本；产品契约要求显式 finish_task，脚本没有下一条输出而 StopIteration。多数是测试契约陈旧，但 C1 的实际产品空转仍独立成立 |
| token usage，3 个 | 两个是快照新增空 history/游标行为变化的精确相等断言；另一个也涉及普通文本完成契约。需要更新预期并保留原安全断言 |
| speed pipeline，1 个 | fixture 调用缺少 `name`，validate_batch 读取 `call['name']` 报 KeyError；未走到其想测试的 newly revealed 字段保护 |
| career flow，2 个 | 视觉测试在打开开关后未创建浏览器，工具仍不可用；不是未授权时提供截图工具。另一项是新增 unknown/confirmed_condition 计数使字典精确相等失败 |
| custom agent，1 个 | 实际多出来的是正确的原文 `Example University\nOther text\nExpected May 2027`；不能据此声称学历被混进 Experience。`complete_source_evidence()` 补齐了原文，旧测试要求完全删除学历，预期需要审查 |
| career organise，1 个 | 实际失败在永久删除会话后，原 run 又作为无主申请出现。`_created_by_conversation()` 用 messages[:3] 和固定字符串前缀推断来源，缺少稳定的来源字段 |
| 原始浏览器测试，3 个 | 本轮只复核原日志；一个 aria-pressed 数量断言，两个 interview 卡片仍显示旧问题。不能未复现就全归为过时 UI 文案；尤其后两项可能与消息路由/状态刷新有关 |

因此，报告中“视觉权限泄漏”“学历原文混入经历”的描述需要修正，不能按它们安排安全漏洞修复。多数测试契约漂移也不能成为忽略实际 C1–C4 故障的理由。

## 8. 修复和验收顺序

1. **先修 C3**：无上传框、晚出现上传框、前页已上传、材料替换必须四类都覆盖；复核、记忆保存和模拟提交链应能完成。
2. **修 C2 的整条链**：普通格式、多雇主、多学历、未完成学历、括号内技能列表；不能只修 PDF 展示。验收包括重新提取最终 PDF 并比对必保留字段。
3. **修 C1 并处理面试控制**：搜索无新证据、完成材料后收尾、结束面试、后台申请等待分别测试；预算不应成为正常完成机制。
4. **修 C4 与推荐契约**：先固定分段/提取覆盖，再做带人工标签的多申请人、多职位评估；单测 MockTransport 回答 0.99/0.01 不能验证真实质量。
5. **修提醒语义**：weekday/时区/DST、数字和区间阈值、无匹配摘要、部分结果摘要、预算/超时摘要。
6. **修执行所有权及接管**：跨会话取消隔离、接管中禁止自动恢复、父子 pause 状态一致。
7. 更新已确认过时的测试，再复跑全量测试；保留尚未定位的浏览器和快速面试回答问题，不用改期望值掩盖。

## 9. 本次证据文件

- [本地复现数据](docs/diagnostics/e2e-2026-10-10/local-reproductions.json)
- [循环复现](docs/diagnostics/e2e-2026-10-10/loop-reproduction.json)
- [重新渲染的简历 PDF 文本](docs/diagnostics/e2e-2026-10-10/reproduced-tailored-resume-text.txt)
- [复跑失败详情](docs/diagnostics/e2e-2026-10-10/test-failures.json)
- [Jev 结构化 JD 逐阶段问题与响应](docs/diagnostics/e2e-2026-10-10/jev-structured.json)
- [Jev 平铺 JD 逐阶段问题与响应](docs/diagnostics/e2e-2026-10-10/jev-flat.json)
- [Jev 追加换行的逐阶段问题与响应](docs/diagnostics/e2e-2026-10-10/jev-structured-newline.json)

原始测试现场仍位于原报告第 7 节列出的 scratchpad；本次以只读方式检查。第一次真实 API 诊断因简历外传风险被自动审批拒绝；替换为脚本内硬编码、无身份信息的虚构数据后获准运行，未发送测试数据库中的简历。

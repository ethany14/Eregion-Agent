# A–F 修复验收矩阵 · 2026-10-11

**本地提交说明（2026-10-11）**：用户已明确授权 commit；此前验收轮“未stage/commit”保留为历史记录。提交前暂存检查发现两处EOF空行，已仅修格式，未改变功能/阈值/失败结论。r4保留为提交前中间快照，链接标题对齐后的最终清单为git-review-scope-r5.json；旧r3原205哈希/206含自身check exit0保留为历史，不覆盖。只提交本地，推送/PR仍待批准，无收费重测或清理。

此矩阵是当前状态的依据，保留原编号。局部回归通过不代表整项验收通过。状态：**通过 / 失败 / 未测 / 需用户操作**。真实链路与脚本测试分别记录；原始失败及用量保留，不降低阈值、不删失败样本。当前分支 `codex/remaining-e2e-fixes-20261011`，未推送、未创建 PR。

| 原编号 | 验收项 | 状态 | 最终测试、证据和缺口 |
|---|---|---|---|
| 1 | 主模型固定到 Jev 需求目录 | 失败 | 默认路线仍OPEN/pending真实用户选择，未擅改TYPESAFE_ENABLED=false。共同部分已实现完整JobAnalysis字段冻结、正文/span/ID验证、显式主服务single/batch匹配输入与持久缓存版本隔离；python→rust/展示/typed变化不能沿用旧身份。实际attempt计数修复，133pass4skip后新增边界139pass4skip，另批量预检7pass；均离线，原v3三失败/v4一失败保留。见catalogue-attempt-offline.md/.json、main-analysis-offline.md。原3.5四冷spread≤8、典型≤30、32次6并发0timeout真实仍未测，不将显式目录或编排通过当默认绑定/质量通过 |
| 2 | Jev 分数尺度和告警阈值 | 失败 | 原 Six Feet Up 评分受其他职位污染，不能用来校准。先修正文、复测，再用人工标签校准；阈值未降低 |
| 3 | 6 申请人 × 12 真实岗位标签 | 需用户操作 | evals/fit_labels_v1.json r2已建6合成申请人×12公开ATS岗位（4领域各3）、structured/flat及72组合待审模板；12来源+12要求+72组合共96项人工复核pending，非human gold。冻结manifest/版本签名/严格验证及offline/live管线已建；共享quote映射缺陷修复，22项纯离线契约通过，不代表质量通过。两真实JD分段及24文本offset局部通过；3.2评分差≤10占比≥90%及数量比0.8–1.25仍未测。未启动288收费预测；旧污染和读取失败保留。见evals/fit_labels_README.md |
| 4 | 收紧 partial | 未测 | 已复现合法原文但无关quote错误partial，主流程/可选resolver新增必要内容词/有限alias防护，单岗/八岗/持久缓存、C/R/C++/C#、泛词/伪造引用局部通过；0.5不变。原before4fail5pass保留，准确率/AUC及冻结baseline仍未测，不将机制当质量通过。见main-analysis-offline.md |
| 5 | 跨岗位 resolver 批处理 | 失败 | 八岗去重实测 cold89.015s /resolver84.455s，超过原≤60s；21calls/31859in/14273out完整账本，warm0.387s零新调用。**用户要求暂缓性能优化，不再反复付费复测**。机制/alias通过；真实输出错误删除缺证据要求，已改保留unknown并做八岗语义回归，准确性继续修，不计性能通过 |
| 6 | 真实模型长对话 | 失败 | 最新phase4-recovery自然终态52主calls/336.75s，0保存岗位/0推荐，needs_input/no_progress；主/总input均715985、output30044、52账本完整，费用门槛通过但两岗成果失败。末24动作不等于52完整轨迹。原interval-completion qualified1且超1M失败保留。离线相邻95通过+本地Chrome/候选25通过0skip；不收费重跑。见analyst-phase4-offline-repair.md及failure-and-usage.json。backend已过不重测；完整长对话范围不缩减 |
| 7 | 已知结果摘要（条件项） | 失败 | #6 循环已触发；摘要、完整控件入口、无进展保护已实现。新修复减少重复观察和请求上下文成本，允许不同查询恢复；离线通过，真实原输入尚未复验通过 |
| 8 | 模拟站 review→remember→submit | 通过 | 补齐 pending 勾选/未勾选分支；真实 Chrome 两种提交、第二岗位及重启：tmp/remaining-mock-unchecked.xml（2 passed）；真实决策模型另归 #6 |
| 9 | 本人真实雇主登录投递 | 需用户操作 | Workday/Greenhouse/Lever；本人登录和真实投递，不代用户操作 |
| 10 | URL 去重：旧记录、重启、跨会话 | 通过 | 旧哈希/新旧重复记录、三种提交保护状态、父会话 running 重启、活动归属拒绝/取消归属接管、终态重启不开浏览器均通过；见下方证据。真实模型模拟站重开尚在 #6/#8 验收范围 |
| 11 | 一次开启多岗位且回复数量准确 | 未测 | 原两条虚假复数回复已修，81项局部通过。新增真实SQLite两个保存ID同一岗位仅1run却报2starts已复现修复：按唯一run统计starts/opened，与resolved_request_count分开；tmp/plural-identity-before-20261011.xml保留1fail，after29pass含重放/既有状态守卫。真实模型多申请链仍未测，不将本地合成浏览器当整项通过 |
| 12 | 同站多申请共享已登录状态 | 通过 | 14 项底层 Chrome 回归及 tmp/remaining-account-ui-contract-fixed.xml 前端/API/生产 worker 全链路通过；第二申请重载后复用登录 cookie。全部为本地模拟站，非真实雇主登录 |
| 13 | Country 等资料记忆 | 通过 | 安全字段/独立词边界/法律字段排除通过；自由文本 Country 保存、第二岗位 Chrome 自动填入通过，tmp/remaining-mock-unchecked.xml |
| 14 | 过期登录横幅 | 通过 | tmp/remaining-account-ui-contract-fixed.xml：账户表单→验证码→Country，旧父问题及登录横幅清除；截图及事件 JSON 见下方，未 force 点击 |
| 15 | 导航后接管面板 | 通过 | 同一 Chrome UI 链路真实点击接管，输入验证码并导航，frame/end/chat API 均 200，恢复 agent 后前端无 JS 错误；首轮面板夹具失败单独保留 |
| 16 | 快速面试答案顺序与反馈延迟 | 失败 | 原p50=110.097>30s保留。异步CAS/FIFO/恢复102通过3跳过，追加失败反馈显式重试/聊天/取消/重启63通过1跳过；真实Chrome最终1通过15.31s，20张日夜×桌面手机截图已目视、End report/零JS错误。真实主模型异步复验自然1失败378.54s：6任务calls中1连接失败，已知4116in/11474out、1调用用量未知；仅两条完整等待34.214/51.739s，三样本p50不可算，仍未达标。不重复收费整轮；终态观察器及ConnectError安全分类42通过2跳过。证据interview-async-main-connection-failure.json。fast ID未配置，10s未测；本轮deferred RPC长锁before3fail→after3pass1取消fail→after-v2原4pass；原库CANCELLED→QUESTION_FAILED已定位修复，最终95pass3skip/63.389s，总98不是98pass。监督21项/终态4项SHA已核对，重叠不累计。真实延迟仍失败；见interview-failure-lock-offline.md/.json |
| 17 | 阻断切源、Ashby/Workday、headless 提示 | 未测 | Phase4租户/host/site稳定身份、同用户turn持久表、跨query/工具/重启阻断、真实用户Control后刷新均已修；本地相邻131通过1skip另1披露缺陷已修，针对性53通过+DDG2通过；获取路径55通过8Chrome opt-in跳过，随后4通过0skip含真实本地Chrome恢复，再2通过验证伪造引用和分页阻断。免费公网Ashby linear与Workday nvidia各search→target detail成功，仅证明这两源可读。B6单次phase4-recovery已52调用/0推荐失败；后续离线95项及Chrome/候选25项通过不替代真实成果，不能以合成HTTP通过替代。详情见phase4-repair.md及精简证据 |
| 18 | 搜索资历不匹配提示 | 未测 | 已从生产SQLite read→import→score→recommend复现Senior-only接受Staff并修复：严格only拒绝，非exclusive强制保存真实warning/caveat；原始用户条件持久化、重启/150消息裁剪保留，明确用户修改才可放宽。尾部两语序、否定include、询问JD/面试保护通过；不是仅discovery warning。实际模型最终推荐行为仍待B6/后续真实链路，不宣称全网资历判断通过 |
| E1 | 回复隐藏内部代码 | 未测 | 已加display_name/人类状态label及完成回复守卫；生产SQLite分析→inspect_job→完成回复、ID/否定ID/URL/路径/代码/用户原文局部通过。首轮81通过1失败1跳过为旧面试同步断言，改按持久反馈终态等待，82通过1跳过；代码变量例外/请求预算相邻回归tmp/remaining-language-volume-final.xml为21通过/5.675s。非真实长对话模型输出整项通过 |
| E2 | 标题不截断单词 | 通过 | tmp/remaining-polish-ui-final-v2.xml 本地真实Chrome/API通过：长标题完整单词+省略号、短标题不截、旧90字符截词从goal恢复、无waiting尾缀；Day/Night×桌面/手机截图已目视核对 |
| E3 | 取消搜索不显示 Application cancelled | 通过 | 同一真实UI链路无申请run→Cancelled、有申请run→Application cancelled，POST200及父/子取消状态一致、无JS错误/零模型调用；首轮隐藏活动面板和取消父夹具失败保留 |
| E4 | 城市保留州 New York, NY | 通过 | 限本地生产PDF解析+合成提取模型：短/完整city、City ST country、ZIP+country、空缺/失败fallback、工作/教育标题家族、雇主学校地址拒绝、非美国不造州、聊天明确改址。统一验证/扩展规则，unified100项98通过2跳过7.660s，独立40通过4.19s；标题边界原4失败保留，不泛称所有真实模型链通过 |
| E5 | 求职信更自然 | 失败 | 原3calls/3290in/8508out失败保留。policy-v5真实writer自动grounding通过，但旧失败seed语义验证判定不一致、reviser未执行，整轮1fail/3calls2360in7334out；随后只补原冻结失败reviser lane，真实修订+最终grounding通过/2calls2643in4830out，过去无据效果和Experience栏目职位混淆已删。旧重复API检查把过去与未来贡献误算重复，离线修正；实际稿仍重复would welcome the opportunity且开头生硬，风格仍失败。v7政策与section元数据投影修复离线通过，未重复付费writer，verifier不变。原文/原失败/冻结FAIL provenance/账本均在cover-style-*及cover-original-revision-evidence.json，人工风格审阅仍待 v8仅离线策略/具体段落建议58通过2真实模型opt-in跳过，verifier不变，无新收费稿；风格仍未通过。见cover-style-v8-offline.md；本轮修生产建议/评测筛查chance与空白变体不一致，before4fail1pass→after47pass2paid-skip，含31项application-pack；有限筛查不是人工审美，无新真实稿。见cover-style-screen-offline-r1.md/.json |
| E6 | U.S. Sponsorship 分句 | 通过 | 限生产PDF→job_units→原文offset链：37项含9个真实PDF用例通过，另31材料相邻通过；合计与E5提示词70通过31.31s。保留U.S./U.K. English、同段前置句/modal、未见独立句等反例；保守语法边界不泛称所有英文句法，原误拆失败保留 |
| F1 | 推送分支、创建 PR | 需用户操作 | 明确等待用户批准；本轮未推送、未开 PR |
| F2 | Git 保留最终报告及精简证据 | 通过 | 限可审阅包/忽略/完整性审计：精确拟提交路径与SHA见git-review-scope-r5.json及E2E_GIT_REVIEW_SCOPE_2026-10-11.md。38历史原件留本地、发布索引；33个r1文件未改写。审计器失败清单假绿灯已修，12项本地及监督独立通过；实际生成/复核见该JSON。未stage/commit/push/PR/清理，不代表其他A–F通过；旧F2 r1因本轮controller及新路径变化已过期、--check正确exit1，保持历史不覆盖；新r2生成后单独复核，不使用旧通过；r2本地/监督独立199哈希200含自身check exit0保留历史，此前F3与链接校正r3已check通过；本次提交格式修正和链接标题对齐后生成r5复核，不覆盖r1/r2/r3 |
| F3 | 清理 tmp | 未测 | 实际清理未执行；本轮仅只读dry-run，全部deletion_eligible=false。监督6857文件/5807780140bytes/189组基线重新盘点，目录引用保护子树；失败/用量/截图/未知恢复库保留。狭窄成功合成夹具候选有实际通过XML、唯一测试归属、源码及新目录重建依据；未执行重建，无依据保持待核查。15项工具契约通过。精确路径/体积/引用/依据见tmp-cleanup-dry-run-r1.md/.json，完整本地清单tmp/f3-cleanup-dry-run-20261011-r1.json，不删除 |

## #10 复现、根因、修复与回归

- **复现输入**：同岗位 `https://careers.example.com/jobs/4021` 和 `/apply`。旧版 `/apply` 记录为 `submitted` / `submission_unknown` / `submitting`，规范 URL 另有 queued 记录；重启后再次开启规范 URL。
- **根因**：旧版 URL 全量哈希产生两个 identity。初次修复在索引未命中时才扫描旧 URL；若先命中新版 queued 记录，仍会遗漏旧版提交锁。
- **修复**：去重使用规范 identity，导航保留原 URL；索引非提交状态也检查 legacy alias，提交状态优先，不改旧 ID 和历史。
- **针对性回归**：`tests/test_remaining_repairs.py` 覆盖七个平台 URL 变体、旧哈希、三种提交锁、新旧重复记录、同会话复用、活动跨会话拒绝、取消 owner 接管、父会话 running 重启、终态 ApplicationLoop 重启不开浏览器。
- **失败保留**：`tmp/remaining-identity-fence-before.log` / `.xml`：5 failed /10 passed，其中 3 项复现提交锁漏洞，另 2 项是新测试 idempotency_key 过短，已纠正测试输入；未删除日志。
- **最终证据**：`tmp/remaining-identity-fence-after.log` / `.xml`：67 passed /1 skipped；进一步补齐父会话重启等：`tmp/remaining-context-verified.log` / `.xml`：56 passed。后者还包括共享循环、资料保存和横幅回归，不能作为真实模型通过证据。
- **真实链路边界**：以上使用真实数据库与生产 TaskLoop/ApplicationLoop，但模型和浏览器 I/O 是脚本；真实 Chrome 与真实模型验收分别归 #8、#6。无 provider 费用。

## #6 / #7 原始失败与修复

**复现输入**：synthetic analyst，找两个 New York junior data analyst 岗位，从 LinkedIn/Indeed 开始；若阻断或登录墙，切公共来源；核实、评分并据实总结，不申请、不建计划。backend 同样要求两个 senior backend remote US 岗位。

**失败**：两个会话均 28 次主循环后 `needs_input/no_progress`。analyst 没有导入岗位；不能称为搜索完成。模型 `muse-spark-1.3-contributor`，浏览器真实访问公共网页。analyst 本轮未进入 Jev 评分。

**根因证据**：工具轨迹显示多次 `browser_read` 后，连续 `read_context` 指向只有前 12 个控件的预览子集；读完仍重复读，未转向岗位链接或结束决策。完整控件数据在原始 archive 中，但摘要缺少醒目的完整路径入口；模型没有利用已知结果。

**修复**：提供完整控件 archive/path；观察中加入 `known_results`；同一请求两次无进展后下一轮移除只读工具与泛化 say，要求结束、必要提问或换行动/来源。原三次 no_progress 停机保护与预算不变。相关代码：`request_context.py`、`career/harness.py`、`task_host.py`、`loop_engine.py`。

**针对性回归**：`test_two_stalled_reads_require_decision_without_another_read`；共享循环回归见 `tmp/remaining-context-verified.xml`。一次测试命令误写了不存在的模块，`tmp/remaining-context-after.log` 保留，未运行测试；随后修正路径再测。

**真实链路与用量**：原始库、transcript、summary 均保留在 `tmp/remaining-live-search/`；日志 `tmp/remaining-live-search.log`；精简只读导出 `tmp/remaining-live-search/evidence-summary.json`，导出脚本 `scripts/export_remaining_evidence.py`。analyst 主任务 28 provider calls /436833 input /11543 output；另外 2 次 resume warmup 1287 input /5080 output，整 fixture 共 438120 input /16623 output。backend 主任务 443602 input /10262 output。首轮采集时其他会话尚未终态，pending/unknown不能按零计费；这是历史边界，不表示当前仍运行。后续终态和完整用量见各阶段JSON及最新状态。

**历史复测（2026-10-11，已终态）**：完全相同 analyst 输入，`tmp/remaining-live-analyst-after.log` / `.xml` 与同名目录，最终失败：60主循环、主任务72provider calls、1154870 input/41128 output，见下方“#6新失败”。当前最终是`tmp/remaining-live-analyst-phase4-recovery/`的52calls/0岗位/0推荐失败，见表格与末尾；没有仍在运行的analyst句柄，也不收费重跑。

## #8 / #13 / #14 历史实现与已完成局部验收（2026-10-11）

**#8 输入**：本地拦截的 `https://qa.example.com/jobs/1001` 表单含 Country、来源、准确性确认；先停 review，用户批准记忆 Country/来源并明确确认提交。第二岗位 `/1002` 应复用资料/来源，保留未记忆的确认问题。分别运行明确收件和歧义处理，再以 `/1001/apply` 重启验证提交锁。

**#8 针对性与真实链路**：`tests/test_remaining_mock_browser.py`使用真实Chrome/生产ApplicationBrowser与ApplicationLoop，所有请求本地拦截。历史首轮`tmp/remaining-mock-browser-first.log`/`.xml`为显式回答记忆契约夹具失败，已终态并保留。最终`tmp/remaining-mock-unchecked.xml`两条通过，两种提交/第二职位/重启及勾选和未勾选pending，完整`browser-chain.json`路径见下一节。没有真实决策模型，不替代#6。

**#13 根因/修复**：原先Country未进入资料记忆映射；新增安全联系字段保存、独立词边界验证，不保存推断的法律/担保/同意答案。针对性`test_literal_country_saved_without_substring_or_legal_inference`及第二岗位Chrome复用均已通过，最终证据`tmp/remaining-mock-unchecked.xml`，历史夹具失败保留。

**#14 根因/修复**：父会话account input_request没有跟踪子申请wait_token；绑定run/token并清除过期父问题。注册→验证码→Country及前端/API/worker真实本地Chrome链已通过，最终`tmp/remaining-account-ui-contract-fixed.xml`，详见下方C12/C14/C15；不代表真实雇主登录。

### #8 最终补充分支

自由文本中的 Country、来源、工作方式均经过模型绑定；来源和工作方式出现在 `pending_approvals`。用户勾选 Country/来源，**未勾选工作方式**。准确性确认另用显式字段回答，按既有契约即时记忆；不把它作为未勾选 pending 的证据。第二岗位 Country/来源自动复用，工作方式保持空白并成为唯一待答问题。两个提交模式和重启均通过：`tmp/remaining-mock-unchecked.xml`（2 passed /59.79s）；每个分支完整字段、状态与 POST 计数：`tmp/remaining-mock-unchecked/test_review_remember_submit_se0/browser-chain.json` 和 `...se1/browser-chain.json`。每个模式 review 前 0 次提交，用户确认后恰好 1 次；歧义状态不自动重试。

保留失败夹具 `tmp/remaining-mock-browser-first.log`：显式回答已记忆，首轮错误期待其不复用，**不是产品缺陷**。自由文本夹具进一步发现实际缺陷：第一次模型绑定写入 `bound_answers` 后，第二个字段被误当作显式有序回答而拒绝。修复 `agent.py`，仅显式绑定冻结整条映射；模型绑定允许补充新字段，已绑定字段仍禁止改值。原始失败 `tmp/remaining-mock-browser-interpreted.log`；修复后 `tmp/remaining-mock-binding-after.xml`（55 passed），新增未勾选分支如上。

### #6 新失败与第二轮修复

analyst原输入第一次修复后触达60次预算，已保存两岗评分但最终答复Send continue，失败。原`tmp/remaining-live-analyst-after/`/`.xml`主任务72calls（60主循环+12Jev）、1154870in/41128out保留。预留最后3个决策的回归`tmp/remaining-final-decision.xml`60passed。第二次`tmp/remaining-live-original-inputs-final/`/`.xml`已终态1failed/1passed，但backend假绿灯被后续outcome-audit-v2判失败，详见下一节。当前analyst最新phase4-recovery仍失败，backend仅后续合格终态通过；不以student/designer代替原输入。

### #11 / #17 / #18 历史实现及当前范围

批量 direct URLs 支持最多四个独立岗位，先验证 URL、按 identity 去重、逐个返回真实 starts/reuse/errors；复数完成回复对照用户 URL 与持久化 attempts，未完成提交不能称已提交。专项测试见 `tests/test_remaining_repairs.py`。Ashby 使用[官方公开岗位 API](https://developers.ashbyhq.com/docs/public-job-posting-api)；Workday 仅向校验后的 tenant CXS 公共搜索接口发送查询，当时尚未真实源验收；后续免费Ashby/Workday各一目标读取通过，仍不代表完整搜索。HTTP 与研究浏览器识别登录墙/挑战，提示切源和 headless 限制。搜索标注 Senior→Staff 资历差异，不降低原要求或伪造岗位。离线批量/源/提示回归：`tmp/remaining-batch-search.xml` 79 passed /1 skipped。整项真实链路仍未验收。

## 监督补充：B6 假绿灯、级别断言与 A1/A2 正文污染

**B6 最终失败**：`tmp/remaining-live-original-inputs-final.xml` 原始结果为 1 failed /1 passed，保留原文件。但 backend 的 pass 是测试漏检，**目标验收仍失败**。它只评分了一个声称 US-remote 的 DevOps 岗位，第二个 backend 未评分，PK 岗位被排除，且未保存推荐。主模型 1100653 input，任务合计 1217110 input，均超过原 1000000 限额。analyst 24 calls /no_progress /0 jobs，375224 input。诚实披露不足不是目标达成。

**断言修复**：`scripts/remaining_search_acceptance.py` / `tests/test_remaining_live.py` 核对两个不同、实际读取、角色/级别/地点满足、实际评分和持久化推荐一致、最终回复逐岗位 URL/分数、无申请/计划、完整用量、60 次主循环及主模型/任务总输入各不超过 100 万。旧记录新增只读复核输出 `tmp/remaining-live-original-inputs-final/test_long_real_search_conversa0/outcome-audit-v2.json` 和 `...conversa1/outcome-audit-v2.json`，两条均 failed；不覆盖原结果。14 项断言回归：`tmp/remaining-outcome-assertions.xml`。

**级别反例**：普通 Data Analyst /UX Designer 描述中的 `mentor junior ...; 8 years experience` 不表明岗位本人是 junior。验收器改为标题或明确“该岗位是 entry-level/junior”语句，资深年限要求也阻断 junior 认定；不确定不算符合。新增用户两条反例、标题/年限冲突和明确初级岗位正例。

**正文污染复现与根因**：原库 `tmp/remaining-live-original-inputs-final/test_long_real_search_conversa1/career.db` 中 Six Feet Up snapshot `f0032a20-5c7a-4e51-9c13-50dff16cf3ca` 保存整页文本，包含导航、地点列表、目标正文、Previous Fusionbox、Next Turing 和页脚。`discovery.job()` 无 JSON-LD 时将整个 HTML 经 PageText 展平，未限定目标正文；通用浏览器 job_only 对未识别页面也退回整页。故外公司标题进入 required/unknown。`No Agencies Please` 属于目标正文原文，但面向招聘机构，被错误当作申请人条件。原评分/unknown/引用和库保留。

**修复**：HTTP 先匹配当前 URL 的 JobPosting JSON-LD，否则只选唯一有边界的职位正文/单岗位 article，剔除 aside/nav/footer/前后职位导航；无边界或多岗位歧义拒绝评分并要求选择实际区域。浏览器 job_only 同样限定区域，不退回整个 body。招聘机构说明在需求抽取前标为 context，保留原文及 extraction ledger；没有删除 unknown 来制造分数。Jev 版本更新，代码签名和清洁正文共同使旧缓存失效。原公开 HTML 保存 `tmp/remaining-python-body-audit/source.html`；实际抽取后 5208 字符，不含 Fusionbox/Turing，保留 Python/Kubernetes 和机构说明。

**针对性最终回归**：`tmp/remaining-body-outcome.xml`23passed；重启中断的`remaining-body-guards.log`无结果，不算通过。重启后`remaining-body-guards-restart.xml`107passed+4subtests。随后`tmp/remaining-body-chrome.xml`9passed、`tmp/remaining-live-body-isolation.xml`1passed，原岗位清洁正文真实Jev37.54、9calls/43058in/6120out，缓存variant0calls；见下方正文污染隔离历史证据。此范围已终态，不代表A1目录/真实稳定性或A2校准通过。

## 2026-10-11 监督补充后的最终记录

### B6 两原输入：body-fixed 历史终态失败（2026-10-11）

| 原输入 | body-fixed 终态 | 主循环 | 任务 input / output | 岗位 / 已评分 | 验收 |
|---|---|---|---|---|---|
| analyst | completed | 58 | 910446 / 27704 | 0 / 0 | 失败 |
| backend | completed | 58 | 903982 / 24264 | 0 / 0 | 失败 |

证据：`tmp/remaining-live-original-inputs-body-fixed/test_long_real_search_conversa0/summary.json`、`acceptance.json`、`transcript.json`，以及 `...conversa1/` 同名文件；终态 `tmp/remaining-live-original-inputs-body-fixed.xml` 为 2 failed /2 deselected。以上用量归属主任务；fixture 的简历预热另计，不当成零费用。

**根因**：正文正确拒绝整页后，Indeed 嵌套详情包装未被识别；筛选 browser_read 会把仍可见但不匹配查询的 region 从最新 observation 删除，随后读旧 region 被拒绝，反复读取没有恢复。补充 HTTP 搜索把 DuckDuckGo 挑战页当作零结果且无错误，没有自动切源；Bing 还返回仅首词相关的词典/养老链接。backend 最后请求用户允许打开详情，违反原请求已有的研究授权。

**修复**：正文增加已观察的嵌套详情选择器，选内部唯一正文，不退回全页；标题、公司和地点仅取同一详情容器内明确的元数据，作为引用保存。区域引用在筛选后保持可见身份，仍严格检查最新 observation/DOM，未绕过过期控件保护。DuckDuckGo 挑战页作为阻断记录并切 Bing，解包实际链接；无关首词结果不作为岗位，空结果附源错误与恢复说明。提示明确公共详情、雇主页面及切源已授权，不要求用户再批准或提供可自行搜索的链接。

**针对性与公开网络证据（历史，2026-10-11）**：`tmp/remaining-source-detail-recovery.xml`62passed（本地真实Chrome），`tmp/remaining-search-recovery-final.xml`62passed；网页/免费预检`tmp/remaining-source-query-audit/`、`remaining-source-network-preflight/`保留。该次`tmp/remaining-live-original-inputs-source-recovery/`已终态2failed/2deselected，analyst/backend均58calls、0岗位0评分，完整费用见下方source-recovery终态及`source-recovery-failures-and-usage.json`。最新B6状态见顶部，原两岗/60主calls/各1M门槛不变。

### 验收器：格式关联与数值最低年限

**复现**：完整合格样本仅把评分放在 URL 前，会误判缺分；旧逻辑仅查 URL 后缀，还把薪资/岗位年龄当分数。表格首次修复又误认任何裸数字，独立 Salary/Job ID/Age 反例成立。Junior 标题下 `Minimum 10 years of experience` / `At least 12 years experience` 的硬要求也被旧单数字正则遗漏。

**修复**：先按列表条目/表格行隔离 URL 与评分，明确评分可在链接前后；表格裸数字仅接受 Score/Fit/评分等列，`/100` 或明确 Score/Fit 单元格可独立识别。相邻条目不能借分，URL ID、薪资、年龄不算分；新表头不继承旧评分列。最低年限解析数值后判断 ≥4，不被 Junior 标题覆盖；0–3 年初级正例保留。

**证据**：`tmp/remaining-reply-format-before.xml` / `.log` 33 项中 5 failed /28 passed，保留原失败；`tmp/remaining-reply-format-after.xml` 33 passed；补年限/同分相邻岗位后 `tmp/remaining-acceptance-format-years.xml` 49 passed（含两个切源测试）；最终 `tmp/remaining-score-column-after.xml` 59 passed；`tmp/remaining-search-recovery-final.xml` 62 passed（另含三项切源）。缺分、错分、未推荐、角色/级别/地点、资格、实际读取、申请/计划禁令、完整用量及原成本限制均仍断言。初次无表头裸分“正例”已纠正为明确 Score 列，保留初次 XML，不作为放宽标准。

### A5 生产批量入口与持久缓存：机制通过，完整性能待验

**输入/原缺口**：同一实际保存的简历，对两个保存岗位分别要求 Python/Rust，两者 requirement ID 相同。现有 resolver 层测试不足以证明生产入口归属及重启缓存。

**实现/验收**：直接执行生产 `CareerHarness.execute(score_jobs)` → `WorkspaceAnalysisService.analyze_many` → `FitAnalysisService` → `JevFitService`，只替换 provider I/O。一次 resolver 请求中的 `job0:j1` / `job1:j1` 分别映射回原岗位：Python matched/100，Rust missing/0，未互换结果。重新连接同一数据库，创建新的 repositories/ApplicationLoop/CareerHarness/FitAnalysisService，在新任务再次 score_jobs，两个结果一致；Jev 与 resolver 新调用均 0，各岗位 resolver cached=1。该证据是持久缓存和归属验证，不是评分质量验证。

**证据**：`tests/test_remaining_resolver_batch.py::test_production_score_jobs_colliding_ids_one_resolver_call_and_restart_cache`；`tmp/remaining-production-batch-runtime.xml` / `.log` 28 passed；完整合成证据 `tmp/remaining-production-batch-runtime/test_production_score_jobs_col0/production-score-jobs-evidence.json`。最初受沙箱临时目录访问限制，`tmp/remaining-production-batch-first.log` 为环境失败，未产生合格结果；保留后在允许数据库测试的环境重新运行，无真实 provider 费用。

**原性能标准的后续终态（2026-10-11）**：本节原为2岗机制证据，后续已取得8岗生产真实cold89.015s失败、完整21calls和warm零新调用，详见“最新终态及优先级更正”及`real-eight-dedup-semantic-failure.json`。原60s不改，按用户要求暂缓优化，不再重复付费计时；不能仍将其描述为没有8岗实测，也不能将机制通过当性能通过。

### C12 / C14 / C15 前端、API、worker 全链路：通过

**真实 Chrome 模拟站链路**：前端安全账户表单→验证码页→正常打开接管面板→输入验证码并 Enter 导航→刷新 frame→结束接管恢复 agent→Country 待答。第二申请重载带登录 cookie；旧父会话问题和登录横幅消失，实际 Country 控件为空；接管 start/text/key/frame/end/chat API 全部 200，前端 JS errors=[]。均为本地拦截模拟站，无真实雇主或模型费用。

**失败区别**：`tmp/remaining-account-ui-first.log` / `.xml` 是工作区自动展开后测试无条件点 toggle 将面板关闭，#take-over 不可见，尚未进入导航，属夹具错误；改为按实际可见性/aria-expanded 决定是否点。`tmp/remaining-account-ui-panel-fixed.log` / `.xml` 已完成导航，末尾错误要求 hybrid input_request，而 autofill 使用 pending_fields，属契约夹具错误；改核对实际 Country 为空。没有 force 点击隐藏按钮。首轮未在超时前保存 PNG，保留日志/数据库状态，不补造失败截图；第二轮截图/事件保留。

**最终证据**：`tmp/remaining-account-ui-contract-fixed.xml` / `.log` 1 passed /19.95s；目录 `.../test_account_banner_shared_log0/` 中 `account-ui-evidence.json`、`attempt-events.json`、`takeover-after-navigation.png`、`country-without-stale-account-banner.png`。底层 14 项 Chrome 回归保留。此处通过不替代 B6 的真实模型对话验收。

### B6 source-recovery 终态失败与运行层修复

`tmp/remaining-live-original-inputs-source-recovery.xml`：**2 failed /2 deselected**，均自然终态。analyst58calls/970424input/27551output，backend58calls/925233input/27237output；均completed但0jobs/0scored。原summary/acceptance/transcript/数据库及费用保留，精简`source-recovery-failures-and-usage.json`。此前calls=55的监督快照是历史非终态；history仅末24项，不据此声称整个任务没有早期search_jobs。

**新根因**：该轮没有消费 read_job 能力，不能把失败说成 read_job 再次拒绝正文。生产大结果压缩遗漏 regions，持久化 browser 摘要也未提供可执行详情入口；主模型反复浏览搜索控件。browser_evidence 虽移除 observation_id，却保留 query/截取内容等视图变化，导致同一页面被认作新证据；无进展恢复工具集又删除 read_job，反而禁用了新正文捕获。重复动作比较包含 observation token，且只在连续 guard≥2 时生效，变更 query/交替读写可以绕过。不存在的归档路径只返回无上下文错误。

**复现/针对性**：`tests/test_remaining_search_runtime.py` 首四项全部真实复现失败，`tmp/remaining-detail-runtime-before.xml` / `.log` 4 failed；修复后与共享循环/上下文回归 `tmp/remaining-detail-runtime-after.xml` 79 passed。补充实际归档后的无效点击阻断及真实源改变后可恢复：`tmp/remaining-detail-archive-guard.xml` 74 passed。

**运行层修复**：BrowserSession 根据唯一有边界正文产出 job_detail 和实际 read_job 参数；上下文压缩及实时 browser 投影保留该入口与精简 region。对真实页面状态计算 hash，query/offset/新 token 不改变 hash，正文/导航/控件实际状态改变才改变 hash；重复已无效点击按页面及稳定动作身份阻断，不允许仅换 token 重试。must_decide 保留 read_job、切源和新的实际行动，禁止重复只读；无进展标志穿过 archive 并独立持久化，不被大结果压缩吞掉。无效归档路径返回实际可用子路径和 no_new_evidence。未自动导入或评分，read_job 的来源/页面身份检查保留。

**真实 Chrome → 有效模型上下文**：`tmp/remaining-detail-context-chrome.xml` 8 passed；生产 BrowserSession 产出字段进入 ContextArchive/prepare_request 的有效 HumanMessage，而非测试注入字段；验证同页 query/offset hash 稳定、目标正文/导航变化 hash 改变、正文/侧栏隔离和多正文歧义拒绝。保存实际 Indeed 页面到 `tmp/remaining-indeed-detail-inspection/source.html` 后发现其单一正文为 `.simple-job-description-html`，先前确未识别；这属于额外结构缺口，不能解释模型没有调用 read_job 的运行层问题。限定同一目标容器补识别正文、标题和字面地点，不扩大到 results/main 全文。

**实际网页重放**：`tmp/remaining-real-detail-consumption.xml` 13 passed（含保存的真实 Indeed HTML、8 项正文/Chrome、4 项运行层）；`.../test_saved_real_indeed_body_and0/saved-real-page-detail-evidence.json` 保存目标正文、Associate Data Analyst、New York, NY 10007、实际 read_job 参数及有效 HumanMessage，未含 GoodApple/其他职位正文。

**历史runtime-recovery复测（2026-10-11，已终态）**：`tmp/remaining-live-original-inputs-runtime-recovery/`/`.log`/`.xml`为2failed/2deselected，analyst26calls/2评分0推荐、backend51calls/仅1条全部合格，完整状态和费用见紧接下方表格。没有仍在运行的句柄；局部Chrome不替代B6。

### runtime-recovery 终态与监督新反例（保留失败）

两条付费句柄均自然终态，没有中断或重启。`tmp/remaining-live-original-inputs-runtime-recovery.xml`：**2 failed /2 deselected**。

| 原输入 | 终态 | 主循环 | 主模型 input | 任务总 input | 已读/已评分/推荐 | 当前判定 |
|---|---|---|---|---|---|---|
| analyst | completed | 26 | 379895 | 427620 | 2 /2 /0 | 失败：未保存推荐；原验收器还误判 GoodApple 低年限及同级 bullet 分数；CUNY 的 associate/优先 1 年不自动证明 junior |
| backend | completed | 51 | 874688 | 923481 | 2 /2 /2 | 失败：仅一条全部合格；Atlassian 保存地点缺 Remote 标记，不能凭搜索筛选自动认可 US-remote |

**证据**：两个 `test_long_real_search_conversa0/1` 目录下原 `summary.json`、`acceptance.json`、`transcript.json`、数据库和日志不覆盖。精简费用含主任务/fixture 总量/未归属预热：`docs/diagnostics/remaining-2026-10-11/runtime-recovery-failures-and-usage.json`。有效 read_job 正文消费已发生，不能再把本轮说成没有消费新正文能力。

**验收器复现输入**：真实 GoodApple `0-2 years of marketing or analytics experience`；真实 final 的粗体职位标题下 URL/Score 多条同级 bullet。复现夹具 `tests/fixtures/remaining_runtime_analyst.json` 仅保存公开岗位正文、实际 final 和合成测试用量。`tmp/remaining-actual-reply-before.xml`：5 failed /67 passed。修复后允许明确、属于岗位本人的低年限区间证明 junior；不泛化 associate、带教 junior、优先 1 年，≥4 的明确最低年限仍否决。按职位标题块归属 URL/分数；Seniority fit 不是匹配分数，薪资/缺分/串分/错分仍失败。中间回归 `tmp/remaining-actual-reply-after.xml` 保留 1 failed /71 passed（发现 Seniority fit 被误解析为 0），已纠正。`tmp/remaining-source-view-hash-after.xml` 87 passed；`tmp/remaining-actual-outcome-production.xml` 79 passed，另验证生产 recommend_job 允许披露低分、拒绝已知不合格条件。不改变 recommendations 缺失断言；实际 analyst 仍失败。

**hash 静态边界复现/根因**：SCAN 用已过 inside(region_ref)/navigation_only 过滤的 controls 算源 hash，同一未变化页四个读取视图产生四个 hash。`tmp/remaining-source-view-hash-before.xml`：1 failed /9 deselected。修复在所有可见非秘密控件上先算源 hash，再过滤返回视图；输入值、正文和真实导航变化仍改变 hash，原正文边界/歧义拒绝保留。新增 Chrome 实际 hash 进入生产进展保护的回归，不用手注入 hash 代替。监督自行终止且未取得结果的探针不计产品失败。

**产品缺口与修复**：普通搜索“推荐任何核实选项”被提示中的 weak/quota 表述误当成强匹配阈值，analyst 最后未调用 recommend_job。明确普通搜索可披露低技能匹配与完整风险，不能称 strong fit；已知不合格、过期、未核实不推荐，告警原阈值保留，继续寻找满足岗位资格的选项。Atlassian 实际保存的目标 header 含 San Francisco, CA 94104 以及单独 Remote 行；投影只保留邮政地址，漏掉工作模式。`tmp/remaining-target-location-before.xml`：1 failed /1 passed，后者证明侧栏 Remote 不可串入。修复仅合并同一目标 header 的模式，US-state ZIP 作为实际美国地址证据；不从侧栏、搜索筛选或正文其他办公室推断。旧 backend 原结果不补写地点或改绿。

**下一步验收**：`tmp/remaining-runtime-boundaries-final.xml` 进行 Chrome/运行层/验收器/告警最终回归；通过后两原输入用新目录真实复验。#6/#7 继续失败，完整 A–F 其余状态不因上述局部测试变更。

**最终针对性回归与原结果复核**：`tmp/remaining-runtime-boundaries-final.xml` / `.log`：**106 passed**，包含实际 Chrome 不同 region/navigation 视图相同源 hash→生产进展计数、保留 read_job、输入/正文/导航变化会变、目标 header 地点模式与侧栏隔离、生产低分推荐允许/已知条件不合格拒绝及告警回归。原两目录新增 `actual-format-audit-v3.json`，不覆盖 acceptance：analyst GoodApple seniority/reply_score 均 true，但缺推荐且另一岗位资历未证实，仍 failed/0；backend 仍 failed/1，旧地点未改。`tmp/remaining-runtime-integrated-regression.xml` 212 passed /1 skipped 是脚本回归，不是真实长对话。

**本轮真实复验**：`tmp/remaining-live-original-inputs-outcome-recovery/` / `.log` / `.xml`，相同 analyst/backend 原输入、两条合格评分推荐、60 主 calls、主模型与任务总 input 各 ≤100 万；2026-10-11已终态：analyst58主calls/978126总input，仅1推荐仍失败；backend46主calls/733310主input/782578总input、两条合格推荐通过。见outcome-recovery-results-and-usage.json及下文终态，不表示当前运行，不重复backend付费测试。

**监督 errors 残余边界（历史复现，后续已修）**：SCAN 的 errors 是 region/navigation 过滤视图，`progress.browser_evidence` 在已有源 hash 时仍包含 errors；同 URL/hash 由既有 alert 切到空 errors 可能重置进展计数。此前无 alert 的 106 项回归不能证明此分支通过。当时等待付费句柄终态后才修复；后续真实Chrome→TaskHost反例已复现修复，remaining-alert-view-before.xml为1fail，remaining-alert-format-after.xml为138pass，保留真实alert变化和blocked恢复信号，详见下节。不表示当前仍有付费进程。

### A3/A2 来源边界：仍未具备标签基准

`tmp/remaining-label-source-inventory.json` 仅盘点 9 个历史岗位，不是 6×12 数据集。`docs/diagnostics/remaining-2026-10-11/a3/source-review-manifest.json` 明确 inventoried_job_count=9、labelled_pair_count=0、human_reviewed_pair_count=0、calibration_allowed=false。旧快照正文均未保存 raw_page_text，不能从旧展平文本假装重新限定 HTML 边界；其他来源要另取目标正文/标题/地点再建立独立 revision。Tuniform 可能是公司名误作标题，特别标注待核对。malformed 旧数据库保留为 read_failed，不能按空岗位/成功样本处理，也未自动修复原数据库。

8113使用已保存`tmp/remaining-python-body-audit/source.html`离线重新抽取，保存`docs/diagnostics/remaining-2026-10-11/a3/python-8113-clean-r1.json`：5208字符、body SHA-256 `df74fd17afb2644256891f787129365fcb0105e822a79db7935c660ae840e9dc`，HTML hash/标题/100% Remote USA Only地点边界均记录。无Fusionbox/Turing，No Agencies原文保留但不是申请人required。旧10287字符snapshot `f0032a20-5c7a-4e51-9c13-50dff16cf3ca`及污染评分保留、排除出干净revision。该历史动作零provider调用，未改当时付费进程；有关进程后续终态已在各节记录，不表示当前仍有运行句柄。

A3 后续须对 6 个合成申请人×12 个真实干净岗位的 **72 组岗位要求/匹配标签** 独立建草稿和人工复核；材料排版/事实质量的 human_quality_review 可复用流程，不能代替这些维度与覆盖。A2 不使用未复核或污染样本校准，告警阈值未更改。

### outcome-recovery 终态、alert/格式与第二岗恢复

`tmp/remaining-live-original-inputs-outcome-recovery.xml`：**1 failed /1 passed /2 deselected**。analyst completed/58 calls，主 input 952827、任务 input 978126，1 岗/1 评分/1 推荐，不是通过；PA/GMT+3 岗位排除正确。实际 `Score vs saved resume: **42.78**` 漏识别使原 acceptance qualified_count=0，独立修复后仍须 failed/1，不降低两岗要求。backend completed/46 calls，主 input 733310、任务 input 782578，两条全部符合角色、级别、US-remote、实际读取/评分/推荐及回复断言，**本原输入通过**，不重复付费跑它。主/任务用量及未归属 fixture 预热 `docs/diagnostics/remaining-2026-10-11/outcome-recovery-results-and-usage.json`；两目录原 summary/acceptance/transcript 和库保留。

**alert 复现与修复**：`tmp/remaining-alert-view-before.xml`：1 failed /12 deselected。真实 Chrome 同源已有 role=alert，full→other-region→navigation 的 hash 相同，但 TaskHost.after_action 计数 `[0,0,1]`，证明 87/106 项旧 hash 测试不足。已有源 hash 时进展指纹不再使用过滤 errors，真正 alert 内容变化通过未过滤源 hash 识别，blocked 状态仍独立保留。`tmp/remaining-alert-format-after.xml` **138 passed**：含 Chrome `[0,1,2]`、alert 内容实际变化恢复计数、blocked 指纹差异，以及原正文/资历/费用约束。

**真实评分标签**：`tmp/remaining-score-vs-resume-before.xml`：1 failed /77 passed；`tests/fixtures/remaining_outcome_analyst.json` 保存实际新回复和单岗结果。增加明确 Score vs/against/for saved resume/profile 标签，不接受 Salary 或相邻/错误分数。修复后真实单岗夹具仍 failed/1。

**恢复归因与运行层反例**：analyst 本轮 search_jobs 换 query 多次，DuckDuckGo 均 challenge、Bing 均无可提取结果；失败源健康未持久化，query 字面变化又被当进展。`tmp/remaining-source-health-before.xml`：2 failed /3 passed（不同 query/重启重复请求阻断源、同城市州别名误过滤）；`tmp/remaining-empty-search-progress-before.xml`：1 failed。公开 board 只读诊断 `tmp/remaining-outcome-source-audit/board-location-audit.json` 证明 Datadog 435 个公开岗使用 New York, New York, USA，Peloton 54 岗且无 analyst；不是已找到第二个合格岗位。原 Etsy 错误、两引擎错误与 actual source coverage 保留，不能把零结果说成市场无职位。

**恢复修复**：按当前用户轮次持久化源健康；阻断引擎不随 query 重试，无提取结果两次后停止同引擎；同库新 harness 复用，新用户轮次可再试。空搜索按实际源/候选结果/错误计进展，文字换 query 不重置；真正新源或新候选可恢复。公开 board 地点比较完整 city/state，只认实际同城州别名，不放行 Albany/PA；未硬编码任何旧岗位或自动导入评分。该修复仍待针对性最终结果及 analyst 原输入真实复验；完整 A–F 其他项继续原状态。

**恢复回归/真实复验（历史，2026-10-11）**：`tmp/remaining-source-health-after.xml`142passed、`tmp/remaining-source-health-note-final.xml`6passed，仅证明机制。对应同原analyst输入`tmp/remaining-live-analyst-source-health/`已终态1failed/109.37s，20主calls、286815主/309973总input、1推荐但final无URL/qualified0，原费用及失败详见紧接下一节和`analyst-source-health-failure-and-usage.json`。最新analyst为phase4-recovery失败；backend不重测，A5性能用户暂缓、C16真实延迟仍失败。

### 新增 analyst 提前结束与候选恢复（本轮）

- **原始失败**：`tmp/remaining-live-analyst-source-health/test_long_real_search_conversa0/{summary,transcript,acceptance}.json` 和同名 `.xml/.log`，pytest 1 failed /109.37s；20 主调用 /286815 主 input /309973 总 input，完整计费。1 岗 1 推荐，最终无 GoodApple URL，qualified=0。精简完整费用：`docs/diagnostics/remaining-2026-10-11/analyst-source-health-failure-and-usage.json`。原文件均保留。
- **根因**：实际状态预算 60、结束时 20；不是实际耗尽。引擎 challenge/empty 后继续读同一 GoodApple，未消费搜索页已观察到的其他岗位 URL。browser compact state 没有持久的未读岗位队列；finish 没有未完成候选检查，也未要求 final 包含推荐链接。
- **修复**：真实 browser controls 中符合当前请求词及 posting URL 结构的候选持久保存，经过过滤读取也不丢；有效 HumanMessage 展示最多 8 个未读候选。只有已观察链接，无自动导入/评分/资格推断。read_job 成功/拒绝均记录尝试，避免强制循环；新用户轮次允许再试。尚有未读候选、推荐数不足且未到最后 3 次保留决策时，finish 被拒绝。结束 URL 检查生效；**分数一致性尚有独立缺陷，下面失败保留，不声称完整检查**。
- **城市预筛选**：`New York, New York, USA` / `New York City, NY` / 裸 `New York` 均可进入候选；不补造 NY。Albany/York PA/New York PA/Kansas City 不同城负例保留。最终正文与地点资格断言未放宽。
- **回归**：`tmp/remaining-city-sentence-before.xml` 3 failed /11 passed（裸城市及两个 country 分句）；一次错误模块路径造成 `remaining-completion-city-sentence-after.log` no tests ran，非产品失败。纠正命令后 `tmp/remaining-completion-city-sentence-after-v2.xml` **169 passed**，覆盖实际模型上下文、完成保留预算、读取拒绝不循环、原成果与费用负例。这是离线机制，不等同真实对话。
- **真实复验（历史，2026-10-11，已终态）**：`tmp/remaining-live-analyst-candidate-recovery/`为1failed/346.83s，58主calls、1102479主/1118360总input超预算，1评分0推荐；GainAmerica人才网络不构成具体vacancy。原summary/transcript/acceptance和完整用量保留，精简`analyst-candidate-recovery-failure-and-usage.json`。后续修复不追溯声称在本轮生效，backend未重测。
- **新分数反例**：`tmp/remaining-final-score-before.xml` 4 failed /5 passed /7 deselected；互换、Salary、Age、相邻条目串分被当前结束校验放行。单推荐缺分/99 错分另已加入，待修。验收器本身仍要求两条逐岗位真实分数，不降低。
- **E6 残余**：`tmp/remaining-language-abbreviation-before.xml` 3 failed /19 passed，Fluency in U.S./U.K. English 与 Proficiency in U.S. Spanish 误拆。仍为失败；需前句完整性判断和原文 offsets，不能只加词白名单。

### A1/A2 正文污染隔离的真实证据（历史）

`tmp/remaining-body-chrome.xml` 9 passed；`tmp/remaining-live-body-isolation.xml` 1 passed。原 Python.org/8113 清洁正文真实 Jev 分数 37.54，9 calls /43058 input /6120 output；改变无关公司后正文与需求相同，新服务持久缓存 0 新调用。证据 `tmp/remaining-live-body-isolation/test_original_python_posting_s0/real-jev-body-evidence.json` 和 `source.html`。仅证明污染隔离；旧 unknown/失败正文未删除，固定目录、人工标签与尺度校准继续待做。

### 恢复控制后：资格、费用和八岗去重测试契约

**B6 原 candidate-recovery 终态保留**：`tmp/remaining-live-analyst-candidate-recovery.xml` 1 failed /346.83s；58 主调用、1102479 主 input、1118360 总 input，超原100万；仅1 scored、0 recommendations。公开正文为 Gain America Early Careers talent network/program，保存标题却是 Job description，final 声称1 verified match；不能凭修标题或解析分数变通过。原 summary/transcript/acceptance 不覆盖；精简完整用量 `docs/diagnostics/remaining-2026-10-11/analyst-candidate-recovery-failure-and-usage.json`。

**复现与修复**：`tests/fixtures/remaining_candidate_recovery.json` 保留实际公开正文/回复/状态。`posting_qualification.validate_posting` 在 read_job/import_job 两处拒绝纯人才网络/项目和泛化标题，不允许模型改名绕过身份验证；明确具体招聘职位及该职位申请入口存在时，附属 Register to join our talent network 不否决整岗。共享逐岗位 reply_evidence 解析器同时用于生产 completion 与测试验收：缺分、错分、互换、Salary/Age数字及未持久化推荐却声称 verified match 都拒绝，原两条合格推荐与费用断言不变。E6 限定当前句的有限谓语，修复前句 Python is/You must 泄漏到 Fluency in U.S. English；保留原文offset，仍不声称覆盖所有英语语法或PDF全链路。

**成本/循环归因**：上一轮有效请求52142字符且 protected_overflow；搜索任务暴露全用途工具schema，固定成本较高。现在明确搜索请求只给研究/岗位工具，另请求申请、材料、面试、告警等能力时保留相应完整功能。Bing相同候选仅 msockid、snippet标题、排序变化被当进展，历史窗口淘汰后再次重置：进展指纹按跟踪参数规范化URL、保留真实岗位ID/来源/board元数据，并按用户revision持久保存。原结果不修改，真实新候选/新源仍可恢复。

**针对回归**：`tmp/remaining-posting-score-sentence-final.xml` 176 passed；`tmp/remaining-source-identity-cost-final.xml` **191 passed /51.97s**。前者中间 `qualification-cost-context-after.xml` 的1 failed /214 passed为 verified match单数匹配遗漏，失败保留后修复。所有此前单分数/互换/工资、纯人才网络、附属CTA、English误拆失败XML均保留。仅离线机制通过，B6仍失败。

**真实复验**：`tmp/remaining-live-analyst-qualification-recovery/` 及同名 `.log/.xml`，仅同一 analyst 原输入；保持两条合格已读评分持久推荐、final每岗URL与实际分数、60主调用、主和总input各≤100万、完整账本。2026-10-11已终态1failed/418.97s：58主calls、主953893/总978020input，1评分岗、0推荐且final无URL，见下方qualification-recovery及精简JSON。最新phase4-recovery亦失败，不收费重跑；后续改动不追溯声称在本轮生效。

**A5 原失败与根因**：`tmp/remaining-real-eight-batch-ledger/` 完整账本21 calls /32086 input /12966 output，cold66.2879882s、resolver61.0841558s，原60s性能门槛失败；warm0.4015616s零新调用。purpose真实为 `jev_fit_resolver:UnknownResolution`，仅修归因断言的schema后缀，不改门槛。原JSON与精简副本 `docs/diagnostics/remaining-2026-10-11/real-eight-production-ledger-retest.json` 保留。第一轮57.0956s缺主resolver账本，不能说零成本或替代本轮失败。

**A5 去重/契约**：按现有decision_key的完整text、level、candidate evidence与模型身份合并，provider只答primary；本地映回全部原job/requirement ID。主测试现采集生产批处理前后的原始unknown及resolver决策，核对 primary + batch_requirement_aliases 精确覆盖全部八岗全部原要求、无重复/丢失、相同predicate/level、合法逐岗结果和精确引文。合法判context需实际provider非申请人要求决策；缺primary答复/伪alias不得补造matched。保持一次resolver、60s、完整ledger、Jev归因和新服务持久warm0。

**A5 离线同构验收（历史记录）**：`tmp/remaining-resolver-alias-contract.xml` 11 passed /4.98s；进一步 `tmp/remaining-eight-offline-production-contract.xml` **12 passed /7.06s**。包含同文本不同level不合并、缺失/伪造quote扇出全部仍unknown、只答alias或不答primary全部仍unknown、原ID碰撞隔离、全部八岗合法扇回及重启缓存。末项直接调用付费测试相同函数、八岗工作负载、生产score_jobs/新服务重启/完整覆盖断言，但provider为本地合成，主bullet仅job0时正确通过；证据 `tmp/remaining-eight-offline-production-contract/test_offline_eight_job_product0/eight-production-cold-warm.json`（2026-10-11只读校正原producti0拼错链接，未重跑）。此耗时不是真实API性能；A5真实89.015s失败、用户要求暂缓，不启动付费复验。

**完整剩余范围的历史缺口与当前结论（2026-10-11）**：A1原四冷spread≤8/典型≤30/32次6并发0timeout仍未真实验收。A3后续已建6×12/72组合模板，96人工复核仍pending，不能以早期9来源盘点代替。此阶段C16曾缺FIFO/end队列，后续持久FIFO/恢复及下一题先显示/异步反馈已局部和本地Chrome通过，详见C16最终节；真实主p50=110.097失败，快ID未提供、≤10s未测。其他1–18/E/F按上表，历史缺口不抹去，也不误称仍未实施。

## 最新终态及优先级更正（2026-10-11）

本节记录历史终态；各启动记录现已补注明对应终态及当前证据，不覆盖旧失败文件。

- **A5 性能失败并由用户暂缓优化**：`tmp/remaining-real-eight-batch-dedup/test_eight_job_production_cold0/eight-production-cold-warm.json`，cold89.0153s、resolver84.4548s；21完整calls/31859input/14273output，warm0.3871s零新调用，5primary和40alias覆盖八岗。原≤60s门槛保留，不再围绕性能反复付费。语义另失败：真实j2协作/j3演示要求因简历无证据被判非candidate而删掉。实际输出 fixture `tests/fixtures/remaining_resolver_classification.json`；现在 resolver不能删除上游要求，false分类保留原unknown/text/level/weight并进入classification_review；八岗alias全回填。精简实测 `docs/diagnostics/remaining-2026-10-11/real-eight-dedup-semantic-failure.json`。这一准确性修复继续，不属于暂停性能的范围。
- **B6 qualification-recovery仍失败**：`tmp/remaining-live-analyst-qualification-recovery/test_long_real_search_conversa0/{summary,transcript,acceptance}.json`，pytest1failed/418.97s、58主calls/953893主input/978020总input、66providercalls完整账本。GoodApple43.85，只有1岗、0recommendations、final无URL；GainAmerica正确拒为人才网络不使整轮通过。精简失败/完整用量 `docs/diagnostics/remaining-2026-10-11/analyst-qualification-recovery-failure-and-usage.json`。空recommendations的完成校验真空通过已修：检查实际read/scored jobs，生产摘要保留原0-2年引文和未决推荐状态；没有自动制造推荐或改两岗标准。
- **C16 FIFO恢复局部通过**：主聊天A1/A2/A3依次对应Q1/Q2/Q3，任意历史消息不能跳过，end排队；原消息裁掉后仍消费持久text，新服务/新DB连接恢复save/evaluate后及receipt窗口，恰好一次。`tmp/remaining-interview-fifo-restored.xml` 75passed/1skipped；`tmp/remaining-semantic-completion-fifo.xml` 191passed/1skipped。均为合成provider，非反馈延迟证明。

### 有界区间完成校验：已通过生产绑定，B6标准未降低

**复现输入**：`match_score=None, score_range=[20,60]`，final=`Read and scored, not recommended: URL Score range 20-60/100; unresolved qualifications remain`。原validator强制数字点分，报expected None；解析器还可能将上限60当点分。`tmp/remaining-score-interval-before.xml` 5failed，失败保留。

**修复**：生产共享`reply_job_evidence`在相同职位块内分别保留scores/ranges，先屏蔽完整区间再读点分；区间必须与保存值完全相同且无捏造点分，有真实点分仍严格逐岗一致。明确Score/Fit/评分表头可绑定裸区间，Salary/Age不能；跨岗互换/相邻串用继续拒绝。兼容API`reply_job_scores`只返回点分，区间上限不会充当点分。原B6两岗、资格、持久化推荐、60主calls、主/总input各100万断言不变；区间通过完成校验不等于原两条点分成果已交付。

**针对性回归**：`tests/test_remaining_score_intervals.py`，含真实workspace.project_fit_analysis保存needs_review报告→job_summary→scored_job_evidence→recommend_job→完成校验；无stub job_summary，生产报告和保存推荐均为None+[20,60]，保留unresolved caveats。补缺区间、错区间、伪造点分、两个区间互换、区间/点分互换、薪资/Age、无效保存区间等反例。

**最终结果**：`tmp/remaining-score-interval-after-v3.xml` **129passed/25.87s**；`tmp/remaining-score-interval-integrated.xml` **214passed/1skipped/62.88s**，覆盖既有点分、薪资排除、逐岗关联、FIFO恢复、resolver语义、任务循环。精简生产绑定证据 `docs/diagnostics/remaining-2026-10-11/production-score-interval-binding.json`（合成provider、0收费API）。首轮实现拼接SyntaxError导致`remaining-score-interval-after.xml` 91failed/37passed，属单一语法/导入错误，不计91种语义缺陷；修复导入后v2的3failed/125passed为新增夹具前缀破坏Markdown标题/表头，均保留，v3已纠正。

**真实后续验收终态（历史，2026-10-11）**：`tmp/remaining-live-analyst-interval-completion/`及同名`.log/.xml/.exitcode`已失败，58calls/511.78s、qualified1，GoodApple推荐/URL/43.95一致但缺第二岗、主1015665/总1040163input均超1M。`tmp/remaining-live-interview-main-feedback/`已失败，三个完整等待42.889/110.097/163.649s、p50=110.097>30；见下方终态和`interview-main-feedback-failure.json`。后续异步主实测连接失败也已归档，未通过延迟。FIFO/下一题先显示/晚到反馈已本地通过，不能替代真实p50；快ID未提供、10s未测。没有运行中付费句柄，backend/A5未重跑。


# 2026-10-11 最新验收补充

## B6 真实终态与请求体积

原 analyst interval-completion：58 主调用 /511.78s，主输入 1015665、任务总输入 1040163，均超过原各 100 万门槛。GoodApple 1 岗 /1 推荐，真实分数 43.95，URL/分数/风险一致，qualified=1；仍缺第二岗，B6 失败。原 summary/transcript/acceptance 保留在 `tmp/remaining-live-analyst-interval-completion/test_long_real_search_conversa0/`，精简用量证据为同目录下 `analyst-interval-completion-failure-and-usage.json`（此文档目录）。backend 已通过，不重测。

原最后一次真实请求为 60308 字符 /48000，protected_overflow=true。离线重建修复前为 60333（25 字符重建差异），贡献 System13368 + tools739 + replay3494 + snapshot42732；归档约 102 万字符不是 provider 输入。修复保留用户指令、权限、简历、资格原文、浏览器状态及 URL/43.95，把旧进度/历史页面和有界候选摘要投影到可精确取回的 archive。完整持久拒绝表及跨工具 preflight 未删减。

实际拒绝摘要加入后重放 45404 字符；合成 8/20/58 拒绝记录为 46255/46260/46261，均在 48000 内。`tmp/remaining-request-volume-integrated.xml`：107 通过 /53.808s；`tmp/remaining-candidate-http-boundary.xml`：7 通过 /10.336s，均已由监督独立核对。原 volume 4 通过 /1 失败属于夹具覆盖真实 source hash，原失败保留。完整请求贡献见 `request-volume-final-replay.json`；原 ledger 58 次中 46 次 context+tools 超 48k 是历史观测，修复后只对保存的末轮做反事实重放，不能声称整轮预算已通过。

## C16 异步反馈、竞争与恢复

原真实主模型 acceptance-to-visible-feedback 三样本 42.889/110.097/163.649 秒，p50=110.097，超过原 30 秒。6 calls /5113 input /13719 output，完整用量见 `interview-main-feedback-failure.json`。fast ID 未配置，10 秒未测。异步局部通过不能替代真实延迟。

career 主聊天现在将答案 FIFO 保存、持久派发反馈后生成下一题；反馈在独立 worker 执行并按原 question/answer 保存，不倒退当前题，不重复计数。迟到自适应追问排在已显示问题之后，保留原父题/答案；end 等所有已接受答案反馈完成后生成完整报告。

原异步首轮 `tmp/remaining-interview-async-first.xml` 为 22 通过 /2 失败：跨仓库 CareerTask JSON 更新丢 receipt，修为版本 CAS。下一轮 `tmp/remaining-interview-async-receipt-fix.xml` 为 2 通过 /1 失败：A3 ANSWER_SAVED 后旧反馈推进版本，defer_feedback 冲突而未入队；不是已执行 end 报错。save_answer/defer_feedback 各保留最多三次数据库 CAS 重试，不重调 provider。旧 FIFO/end 随后 7 项通过。

确定性 Event 测试暂停 A3 派发，让 Q1/Q2 反馈先落库、推进版本并触发一次真实 CAS 冲突；验证答案恰好一次、三个反馈任务、完整 end 报告。另覆盖 Q2 provider 暂停期间 Q1 反馈推进版本、落库后重启的 after_answer/after_queue/after_feedback 三阶段、迟到自适应追问。`tmp/remaining-interview-async-integrated.xml`：102 通过 /3 跳过，监督已独立核对。后续显式失败反馈重试及聊天/取消/重启相邻回归 `tmp/remaining-interview-retry-cas-final.xml`：63 通过 /1 跳过 /49.30s；保存答案不重复，失败反馈不会因重启静默重试付费，用户显式重试后 queued end 得到完整报告。

Node 首轮监督独立运行 3 通过 /1 失败，新增夹具漏 `career:true` 导致生产守卫正常返回，非 UI 排序缺陷。修夹具后 `tmp/remaining-career-chat-fixture-fixed.log` 4 通过，生产守卫不变。真实 Chrome 首轮在主题 reload 返回 Chronicle 后未重选会话，1 失败 /21.28s；第二轮手机视口未打开侧栏抽屉，1 失败 /43.77s。两轮原日志/XML/数据库保留，详见 `interview-ui-fixture-failures.json`。正常重选会话/抽屉复测及20张截图目视核对已随后完成，Chrome最终1pass/15.31s；真实主模型异步复验仍连接失败，见顶部#16与latest-status.md。此段保留历史失败，不表示结果待补。

## 完整范围与用户边界

原 1–18、E1–E6、F1–F3 以仓库根目录 `E2E_ACCEPTANCE_MATRIX_2026-10-11.md` 为准。A5 八岗 cold89.015s 失败保留，原 60 秒不改，用户要求暂缓性能优化，不再付费复测；评分准确性继续处理。A3 人工复核、#9 本人真实雇主登录投递及 F1 推送/PR 批准仍待用户，其余独立工作继续。

## F2与监督独立复核（2026-10-11）

监督目录16pass/3.66s、C11 SQLite+合成浏览器1pass/5.42s、审计器before10fail2pass→after12pass已记录。四XML只读核对SHA一致，XML suite耗时与监督报告墙钟分开保留，见independent-acceptance-20261011-r2.json。C11 requested2/started1/opened1/resolved1且第二项error，重放started0、error保留；实际模型多申请仍未测。33归档和38历史原件哈希一致，未改旧r1。范围与剩余依赖见E2E_GIT_REVIEW_SCOPE_2026-10-11.md，当前精确清单见docs/diagnostics/remaining-2026-10-11/git-review-scope-r5.json；旧F2 r1/r2仅历史，不覆盖。默认路线pending、A5用户暂缓，其他真实失败不变。

## C16 / E5 本轮离线增量与 F2 新 revision

C16 deferred 路径生产SQLite/Event因果反例、取消库、修复和回归见 [interview-failure-lock-offline.md](docs/diagnostics/remaining-2026-10-11/interview-failure-lock-offline.md) / [r1 SHA与精简状态](docs/diagnostics/remaining-2026-10-11/interview-failure-lock-offline-r1.json)。最终95通过3跳过/0失败/0error/63.389s；跳过为两付费反馈及configured-model工具链。监督21项与cancel/end×draft/failure四项有重叠，不宣称25unique。原真实主模型110.097s>30s、异步ConnectError、fast未测不变；直接同步control外层锁仍待逐入口核对。

E5 新离线反例是生产建议和评测筛查规则不一致，修复共享有限matcher后47通过2付费跳过，原4失败1通过保留。冻结真实稿仍事实通过/风格失败，没有新真实成稿或人工审美通过；[复现/修复/边界](docs/diagnostics/remaining-2026-10-11/cover-style-screen-offline-r1.md)。verifier不变，不自动收费再试。

上一轮F2包使用git-review-scope-r2.json（本地/监督check exit0，199哈希/200含自身）；本轮F3增量包使用新git-review-scope-r5.json；旧r1原192哈希/193含自身已是历史快照，--check正确因当前变更失败。保留原始失败、旧manifest和38原件，不推送/PR/批量清理。A1默认路线pending、A3人工待审、B6真实失败、A5用户暂缓及完整1–18/E/F不变。

## F3 只读候选审计与独立增量

监督基线target-tmp-inventory.json：6857文件/5807780140bytes/189组/0读取错误。只读工具重盘并逐组比较，原始失败、付费记录、恢复库、截图和所有既有引用目录子树保持。候选限定有明确可再生依据的成功合成夹具，未引用不等于可删；全部deletion_eligible=false，不打开原库、不执行重建/删除。完整逐文件本地清单与精简候选、引用、源hash及读取前后metadata核对见 [F3报告](docs/diagnostics/remaining-2026-10-11/tmp-cleanup-dry-run-r1.md) / [精简JSON](docs/diagnostics/remaining-2026-10-11/tmp-cleanup-dry-run-r1.json)。F3实际清理仍未测/未完成，15项工具契约不是清理通过。

独立E5五项5pass/4.946s及C16相关bundle只读核对SHA/原XML计数，存在重叠不累计unique；面试35/E5七份归档哈希一致为监督复核，不能代替真实延迟/新成稿。矩阵原A5证据producti0→product0已按实际文件校正，3堆栈截断和1示例命令不冒称缺失证据；不重跑A5。

F2 r2原独立check exit0/199哈希200含自身作为历史保留。本轮F3、报告及链接校正后新r3独立生成/--check，旧revision不覆盖。原1–18/E1–E6/F1–F3和所有阈值不变；不收费/A5/backend/push/PR。

## Claude 本轮付费单次验证与修复（2026-10-11，用户批准"每项一次"）

均为单次运行，无自动重试；原失败文件保留，阈值未改。

| 项 | 结果 | 证据与说明 |
|---|---|---|
| A1 主模型稳定性（缩减样本） | 样本通过，完整标准未测 | 默认主路线改用本地确定性需求目录（`local-units-v3`，`JOB_AGENT_MAIN_CATALOG=extract`可退回自由提取）。r1因运行中改代码签名变化无效，r2 CoStar 8/8失败（domain.py致命年限冲突守卫+自由提取38/50需求漂移）→去守卫、职责兜底后 r3 `docs/benchmarks/main-stability-LIVE-sample-20261011-r3`：64/64 trial、0超时、峰值并发6；8对spread 0.0/0.0/4.2/0.0/0.0/3.5/0.0/5.6（修复前重复均值6.6/最大13.3）；中位43.5s；238553 input/517877 output。仅8/72对，不替代完整72对标准 |
| C16 面试反馈延迟 | 延迟通过，排序子检查失败 | `LLM_INTERVIEW_REASONING=low`（默认）+不支持时无reasoning重试一次。`tmp/c16-live-reasoning-low*`：3样本10.8/15.7/22.6s，p50 15.7s≤30s（原110.1s）；6calls/5228in/8139out。失败子项`next_questions_visible_before_old_feedback`：反馈现在与下一题同一转换内先到。未自行放宽，建议用户确认该检查是否应改为"同一转换内两者均可见" |
| B6 analyst 长对话 | 失败（新根因已修，未复测） | `tmp/remaining-live-analyst-20261011-claude/test_long_real_search_conversa0/`：pytest 1failed/124.86s，20主calls、36provider calls完整账本，主249475/总304067 input、14767 output（均远低于1M，历史为95万–110万）。2保存2评分2推荐，LinkedIn/DDG阻断已披露。失败`fewer_than_two_verified_scored_qualifying_recommendations`：第二岗 Associate Data Analyst 仅"minimum 1 year preferred"，评测器按设计判资历不合格（与fixture历史同两岗）。**根因**：生产`recommendation_warning`只看标题，无级别词标题静默通过，模型自称"matching junior seniority"。**修复**：`search_policy.opening_level`读取岗位正文（明确entry-level/junior、≤3年有界区间为junior证据，任一≥4年最低要求为senior），无证据时写入"Level unverified"警告并前置到caveats；strict请求直接拒绝。回归`test_level_free_title_needs_opening_level_evidence_for_junior_request`；相关8套件199通过1跳过。未付费复测，B6仍记失败 |
| E5 求职信 | 失败（writer lane通过，revision lane前置条件不成立） | `tmp/e5-cover-style-20261011-claude/`：1failed/57.49s，3calls/2601in/8260out完整账本。writer lane 10项自动检查全部通过（grounding、具体角色/公司/需求、第一人称、无僵硬开头、原不支持句删除），成稿见`cover-letter-writer.md`，**人工风格审阅待用户**。revision lane：原被拒稿经实时verifier本次判通过（awaiting_review≠needs_revision），reviser未执行——与上一轮相同的verifier对边界句判定不稳定。建议revision lane改用已有`frozen_verification=True`种子（保留真实reviser与修订后实时复验），需用户确认后再付费 |

**其他离线修复**：`source_health.user_turn`容忍无id消息（`test_remaining_reply_language.py`原10处KeyError，8579945已复现）；面试结束测试改为等待排队结果；`capability_finished`修复丢失唤醒（30/30）；`pytest.ini`限定`testpaths=tests`（本地tmp/含有意失败复现）。

### 续：用户批准的推荐顺序执行结果（2026-10-11）

| 项 | 结果 | 证据与说明 |
|---|---|---|
| C16 排序子检查 | 测量缺陷已修（未付费复测） | 前述"反馈先于下一题"判断有误。三答案同时排队，Q2/Q3出现即被消费，轮询"当前题"永远看不到它们（记为inf）。原证据按系统持久化question.created_at换算：Q2 5.77s<F1 10.79s，Q3 12.73s<F2 15.72s，下一题确实先出现。检查改为取轮询与持久化时间的较早者（非模型时间戳），证据新增started_wall/question_persisted_seconds。离线重放原run通过；原失败xml保留 |
| E5 r2 | 失败1项（根因已修，未再付费） | revision lane改用已有frozen_verification种子（真实reviser+修订后实时复验不变）。`tmp/e5-cover-style-20261011-claude-r2/`：4calls/4991in/9036out完整；两lane均awaiting_review、grounding通过，revision_count=1。唯一失败`original-revision:specific_role_company_need`：修订开头只剩角色+公司。**根因**：生产`style.cover_revision_notes`开头提示写"Employer needs can appear separately"，与writer提示（首段第二句写已验证需求）矛盾，reviser照做移走API reliability。已改为保留在开头段第二句，加回归；cover/pack相关150通过6跳过。人工风格审阅仍待用户 |
| B6 r2 | 失败（外部来源阻断，非资历修复路径） | `tmp/remaining-live-analyst-20261011-claude-r2/`：1failed/148.54s，24主calls，283232in/8601out完整账本，needs_input/no_progress，0保存0评分0推荐。本次Indeed返回Cloudflare校验（r1可读）、LinkedIn登录、hiringcafe Cloudflare；剩余聚合列表页无单一职位正文，jooble/ziprecruiter HTTP错误，gainam被正确拒为人才库。同一search_jobs参数执行6次（重复守卫需连续2次无进展才启用，中间读取重置计数），未尝试公司招聘板。资历修复未被触发。B6结果依赖实时站点可达性，单次结果波动大（r1 2推荐/r2 0） |

### 续：B6搜索修复后E5 r3 / B6 r3（2026-10-11，用户批准付费）

| 项 | 结果 | 证据与说明 |
|---|---|---|
| B6 搜索修复（离线） | 通过 | `task_host`：search_jobs仅当出现本请求未见过的链接才算进展（子集/截断/重排=无新证据），反馈指向公司招聘板；提示词加入来源阻断时改用Greenhouse/Lever/Ashby/Workday boards。回归`test_narrower_or_truncated_repeat_of_observed_search_links_is_not_progress`；全量1768通过131跳过 |
| E5 r3 | 失败1项（根因已修，未再付费） | `tmp/e5-cover-style-20261011-claude-r3/`：1failed/70.27s，4calls/4963in/9737out完整。**revision lane全部通过**（开头保留"The company is hiring to improve API reliability"，r2修复生效）。唯一失败`writer:specific_role_company_need`：writer本次开头只写角色+公司。根因：writer提示"In a separate sentence it **may** refer to ... need"为可选。已改为验证到需求时首段第二句**必须**写入（保留既有固定短语），加回归；cover/pack 151通过 |
| B6 r3 | 失败（外部阻断为主） | `tmp/remaining-live-analyst-20261011-claude-r3/`：1failed/268.25s，37主calls，553369in/24171out完整账本（主528120<1M），needs_input/no_progress；1评分（LinkedIn来源Associate Data Analyst 48.13，无资历证据，未推荐——资历修复使其未被误称junior）、0推荐。Indeed链接HTTP错误、ZipRecruiter/Jooble Cloudflare、gainam正确拒绝。**新行为**：agent首次调用公司boards（datadog/braze greenhouse、ramp ashby、plaid lever），但board结果只要求任一查询词，返回"Accounts Payable Analyst""AI Research Scientist - Data"等噪声。已改为与公开搜索相同的角色词规则（≥min(2,角色词数)，排除级别/填充词），回归`test_board_search_needs_role_terms_not_one_shared_word`；全量1770通过131跳过。未再付费复测 |

**B6结论**：三次单跑r1 2推荐(1合格)/r2 0/r3 0评分推荐，主要受实时站点Cloudflare/登录阻断影响；本轮修复（资历证据、搜索进展判定、board回退及匹配）均离线验证，真实两岗目标仍未达成。

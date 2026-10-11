# 2026-10-11 最新验收补充

**本地提交说明（2026-10-11）**：用户已明确授权 commit；此前验收轮“未stage/commit”保留为历史记录。提交前暂存检查发现两处EOF空行，已仅修格式，未改变功能/阈值/失败结论。r4保留为提交前中间快照，链接标题对齐后的最终清单为git-review-scope-r5.json；旧r3原205哈希/206含自身check exit0保留为历史，不覆盖。只提交本地，推送/PR仍待批准，无收费重测或清理。

## F2交付与独立复核

本轮拟提交清单见git-review-scope-r5.json；旧r2原199哈希/200含自身、本地/监督check exit0，F3/链接校正后保留为历史；可审阅说明在根目录E2E_GIT_REVIEW_SCOPE_2026-10-11.md。旧F2 r1因controller/新增路径变化，--check正确失败，保留为历史快照；不覆盖。38历史原件仅Git忽略未删除，33个catalogue r1产物/实现SHA一致。监督目录16项、C11部分失败/重放1项、审计器12项通过的四XML只读核对SHA，见independent-acceptance-20261011-r2.json。审计器原失败checks假绿灯已修，before/after和环境错误保留于f2-audit-evidence-r1.json。没有stage/commit/push/PR/清理/收费测试；A1默认pending、A5暂缓、B6/C16/E5失败及96人工待审仍保留。

## 本轮 F3 只读审计

监督tmp基线6857文件/5807780140bytes/189组/0读取错误已作为输入；当前逐文件盘点/逐组增量、精确路径体积、目录引用子树保护、原失败/用量/恢复库/截图与可再生成功夹具分开记录。完整本地清单及精简候选见tmp-cleanup-dry-run-r1.md/.json；当前计数以JSON为准，本轮审计器合成自测产物是新增，非原基线。15项工具契约通过，无DB打开/原库写入，无重建或删除，全部deletion_eligible=false，F3实际清理仍未完成。

监督74来源/222引用映射补充核对，目录保护子树，3截断/1示例命令不作缺证据；矩阵A5 producti0拼错链接已校正实际product0，未重跑测试。E5新增五项独立5pass/4.946s与bundle SHA/XML计数核对写入精简JSON，不能当真实风格通过。新F2 r3在报告落盘后生成/--check，旧r1/r2不覆盖；不收费、不重跑A5/backend、不推送/PR。

## 本轮 C16 锁与 E5 筛查离线终态

C16 production CareerService+SQLite/Event：下一题RPC暂停时快速失败反馈不能落库，before3失败；缩短deferred锁范围后3通过1取消失败。原取消库证明CANCELLED→QUESTION_FAILED，已丢弃晚草稿/错误、保留终态；after-v2原4项通过7.751s，最终相邻95通过3跳过/63.389s（总98，非98通过）。三跳过为主/fast收费反馈、configured-model链路。监督单项1通过、21通过、终态4通过XML已读并核对SHA；存在重叠，不累计unique。原DB/事件/用量边界见interview-failure-lock-offline.md/.json。原主p50>30、真实异步ConnectError和fast≤10未测不变；直接同步control调用方外层锁尚未逐入口证明。

E5实际冻结修订稿仍grounding通过/风格失败。新增chance/空白变体在生产建议与评测筛查间假绿灯，4失败1通过；共享有限matcher后47通过2付费跳过，含31 application-pack相邻。原文/verification/verifier不变，无新收费成稿，无人工审美通过；见cover-style-screen-offline-r1.md/.json。所有原A–F阈值及失败保留。

## 本轮 A1 共同机制与 C11 离线终态

目录完整字段身份、显式主服务输入/源span/ID、SQLite持久缓存隔离、实际attempt汇总已修复；原4报3及25bullet七次报4均有离线回归。真实provider事件与无tokens的adapter回退明确区分，失败未知用量不按零。主相邻139通过/4Chrome跳过；批量目录预检before7失败→after7通过，后续47通过+4subtests。原v3三失败/v4一失败及早期错误命令保留；详见`catalogue-attempt-offline.md`和`catalogue-attempt-offline-r1.json`。

**默认目录路线仍OPEN/pending用户选择**，未改变TYPESAFE_ENABLED=false，显式输入不算默认接入或A1质量通过。C11又复现两个保存ID指向1run却报2starts，修复后29项本地回归通过，真实模型多申请仍未测。本轮0真实API调用，不重复B6/backend/A5；A5性能用户暂缓，C16主p50失败/fast ID待用户、E5真实风格失败、A3人工待审均保留。

根矩阵全文历史启动记录已逐项注明2026-10-11终态与目录：B6最新phase4-recovery52calls/0岗位0推荐失败，#8本地Chrome勾选/未勾选两种提交链通过。没有仍在运行的收费句柄；下方各阶段失败作为历史证据保留。

## B6 真实终态与请求体积

原 analyst interval-completion：58 主调用 /511.78s，主输入 1015665、任务总输入 1040163，均超过原各 100 万门槛。GoodApple 1 岗 /1 推荐，真实分数 43.95，URL/分数/风险一致，qualified=1；仍缺第二岗，B6 失败。原 summary/transcript/acceptance 保留在 `tmp/remaining-live-analyst-interval-completion/test_long_real_search_conversa0/`，精简用量证据为同目录下 `analyst-interval-completion-failure-and-usage.json`（此文档目录）。backend 已通过，不重测。

原最后一次真实请求为 60308 字符 /48000，protected_overflow=true。离线重建修复前为 60333（25 字符重建差异），贡献 System13368 + tools739 + replay3494 + snapshot42732；归档约 102 万字符不是 provider 输入。修复保留用户指令、权限、简历、资格原文、浏览器状态及 URL/43.95，把旧进度/历史页面和有界候选摘要投影到可精确取回的 archive。完整持久拒绝表及跨工具 preflight 未删减。

实际拒绝摘要加入后重放 45404 字符；合成 8/20/58 拒绝记录为 46255/46260/46261，均在 48000 内。`tmp/remaining-request-volume-integrated.xml`：107 通过 /53.808s；`tmp/remaining-candidate-http-boundary.xml`：7 通过 /10.336s，均已由监督独立核对。原 volume 4 通过 /1 失败属于夹具覆盖真实 source hash，原失败保留。完整请求贡献见 `request-volume-final-replay.json`；原 ledger 58 次中 46 次 context+tools 超 48k 是历史观测，修复后只对保存的末轮做反事实重放，不能声称整轮预算已通过。

## C16 异步反馈、竞争与恢复

原真实主模型 acceptance-to-visible-feedback 三样本 42.889/110.097/163.649 秒，p50=110.097，超过原 30 秒。6 calls /5113 input /13719 output，完整用量见 `interview-main-feedback-failure.json`。fast ID 未配置，10 秒未测。异步局部通过不能替代真实延迟。

career 主聊天现在将答案 FIFO 保存、持久派发反馈后生成下一题；反馈在独立 worker 执行并按原 question/answer 保存，不倒退当前题，不重复计数。迟到自适应追问排在已显示问题之后，保留原父题/答案；end 等所有已接受答案反馈完成后生成完整报告。

原异步首轮 `tmp/remaining-interview-async-first.xml` 为 22 通过 /2 失败：跨仓库 CareerTask JSON 更新丢 receipt，修为版本 CAS。下一轮 `tmp/remaining-interview-async-receipt-fix.xml` 为 2 通过 /1 失败：A3 ANSWER_SAVED 后旧反馈推进版本，defer_feedback 冲突而未入队；不是已执行 end 报错。save_answer/defer_feedback 各保留最多三次数据库 CAS 重试，不重调 provider。旧 FIFO/end 随后 7 项通过。

确定性 Event 测试暂停 A3 派发，让 Q1/Q2 反馈先落库、推进版本并触发一次真实 CAS 冲突；验证答案恰好一次、三个反馈任务、完整 end 报告。另覆盖 Q2 provider 暂停期间 Q1 反馈推进版本、落库后重启的 after_answer/after_queue/after_feedback 三阶段、迟到自适应追问。`tmp/remaining-interview-async-integrated.xml`：102 通过 /3 跳过，监督已独立核对。后续显式失败反馈重试及聊天/取消/重启相邻回归 `tmp/remaining-interview-retry-cas-final.xml`：63 通过 /1 跳过 /49.30s；保存答案不重复，失败反馈不会因重启静默重试付费，用户显式重试后 queued end 得到完整报告。

Node 首轮监督独立运行 3 通过 /1 失败，新增夹具漏 `career:true` 导致生产守卫正常返回，非 UI 排序缺陷。修夹具后 `tmp/remaining-career-chat-fixture-fixed.log` 4 通过，生产守卫不变。真实 Chrome 首轮在主题 reload 返回 Chronicle 后未重选会话，1 失败 /21.28s；第二轮手机视口未打开侧栏抽屉，1 失败 /43.77s。两轮原日志/XML/数据库保留，详见 `interview-ui-fixture-failures.json`。

Chrome v3 功能链 1 通过 /14.042s，但截图手机抽屉关闭动画未结束、桌面滚到反馈底部，不能据此算目视通过。v4 等正常会话选择关闭抽屉的动画完成并滚至当前问题，1 通过 /14.86s；最终追加两条反馈标题/原问题/对应评语的分区截图，`tmp/remaining-interview-async-chrome-final.xml`：1 通过 /15.31s。截图和 `async-ui.json` 在同名目录 `test_current_question_and_late0/`：日夜×桌面/手机各当前 Q3、反馈1标题/评语、反馈2标题/评语，共20张。已目视核对四种当前题及对应反馈区域，手机内容可读、抽屉右边界≤1、无横向溢出，实际 End practice 生成报告、零 JS 错误。正常控件点击，无 force/DOM 隐藏；未引入自动选中行为。

真实主模型异步复验已自然终态失败（378.54s）：6任务calls中1连接失败，已知4116in/11474out，另1调用用量未知；仅两条完整等待34.214/51.739s，三样本p50不可算，原30秒未达标。详见 interview-async-main-connection-failure.json。计时使用生产 service.view().interviews.feedback_history 首次可见时间，包含排队；不改为仅provider耗时。终态观察器及安全ConnectError分类42通过2跳过，不代替真实延迟通过。fast ID未配置，原10秒未测；不重复收费整轮，没有重跑backend/A5。

## 完整范围与用户边界

原 1–18、E1–E6、F1–F3 以仓库根目录 `E2E_ACCEPTANCE_MATRIX_2026-10-11.md` 为准。A5 八岗 cold89.015s 失败保留，原 60 秒不改，用户要求暂缓性能优化，不再付费复测；评分准确性继续处理。A3 人工复核、#9 本人真实雇主登录投递及 F1 推送/PR 批准仍待用户，其余独立工作继续。

## Phase4 与 A3 增量

Phase4已修显式ATS租户403重复、跨浏览器/read/import/分页重试、用户turn/重启健康表、Workday带连字符site身份、实际Control结束后的缓存刷新，以及Senior-only推荐守卫和原始用户条件持久化。明确否定/询问JD/练面试不改变搜索；合法用户修改及尾部Senior only条件句可识别。完整复现/失败归因/最终局部测试/真实公网只读探针见 phase4-repair.md、phase4-and-shared-quote-evidence.json；不将本地通过写成公网搜索完整通过。

A3 r2已有6合成申请人×12公开ATS岗位、structured/flat、72组待审格式和冻结manifest评测管线；96人工复核pending、288预测缺失、质量指标null。共享quote优先atomic/人工alias的一对一度量修复22项通过，仅合成数学契约。两个真实JD分段与24文本offset通过，不替代原3.2评分差/要求数量比，也不替代A1/A2/A4。

唯一一次原analyst phase4-recovery已自然终态失败：task f01db209-c5a7-4695-9a54-9f019ded74d3，52主调用/336.75s、0保存岗位/0推荐，needs_input/no_progress；主/总715985 input、30044 output、52条账本完整。B6失败，原两岗/60calls/主总各100万门槛不变，不收费重跑。原失败与SHA256/实际最终答复/逐调用账本见 analyst-phase4-recovery-failure-and-usage.json。

末24动作（15无新证据/7搜索）不等于完整52调用轨迹。离线修复受阻待办与source_health冲突、搜索候选恢复遗漏、跟踪参数身份与存储不一致、相同结果列表重复HTTP、错误/上下文跨工具假进展及合法缓存导入被远程守卫拒绝。原search_evidence归一化本已正确，未重复改规则。95项相邻通过；新增本地Chrome/候选/拒绝25项通过0skip，均不替代B6真实成果。详情及原失败分类见 analyst-phase4-offline-repair.md。实际最后请求52846字符仍属原失败；ledger恢复52个大小观测其中46超48k，不能补造52个请求全文。修后终态反事实重建45346字符、工具schema7501，不能声称整轮已绿。

## E5 冻结实际修订稿的离线增量

原reviser事实验证通过/2calls2643in4830out保留；实际开头生硬、第1/3段重复would welcome，风格仍失败。v8消除开头视角冲突，并把实际句子/两个段落位置作为advisory style notes送入生产修订上下文；不改verifier/status、不自动付费重试，不以启发式判审美通过。58项通过、2真实模型opt-in跳过/40.38s。详情见 cover-style-v8-offline.md，完整证据 phase4-offline-and-cover-v8-evidence.json；没有收费生成新稿。

# A–F 验收精简证据

**本地提交说明（2026-10-11）**：用户已明确授权 commit；此前验收轮“未stage/commit”保留为历史记录。提交前暂存检查发现两处EOF空行，已仅修格式，未改变功能/阈值/失败结论。r4保留为提交前中间快照，链接标题对齐后的最终清单为git-review-scope-r5.json；旧r3原205哈希/206含自身check exit0保留为历史，不覆盖。只提交本地，推送/PR仍待批准，无收费重测或清理。

当前状态见根目录 `E2E_ACCEPTANCE_MATRIX_2026-10-11.md`。这里仅保留合成申请人的精简结果，不包含数据库、凭据或完整浏览器记录。原始失败和费用记录仍保存在本地 `tmp/`，Git 忽略不代表删除。

- `main-analysis-offline.md`：A1抽取/typed去重/ID隔离及A4必要内容词防护；246通过、另4subtests通过、4跳过。不是评分质量通过。
- `catalogue-attempt-offline.md` / `catalogue-attempt-offline-r1.json`：完整目录身份/可信显式输入/缓存及实际attempt汇总，保留before/v3/v4失败与最终139通过4跳过、批量预检7通过/相邻47通过+4subtests；默认路线仍pending。另C11真实SQLite同posting两个保存ID重复报starts，1失败→29本地通过。0真实API调用。

- `production-score-jobs.json`：A5 生产入口、同名需求 ID 的岗位隔离、一次 resolver 调用、新运行实例持久缓存零新调用；原文件路径和 SHA-256 可复核。provider I/O 为确定性夹具，无真实 API 费用。
- `body-fixed-failures-and-usage.json`：B6 两个原输入均失败；同时保存主任务、整个 fixture、未归属任务的预热用量。pending/unknown 不按零计费，discarded 调用仍计入费用。
- `source-recovery-failures-and-usage.json`：后续切源修复的两原输入仍失败，完整用量保留。
- `runtime-recovery-failures-and-usage.json`：analyst 26 calls、两岗评分但无推荐；backend 51 calls、两岗评分推荐但仅一岗满足全部条件，均保留 failed；原验收及主任务/fixture 费用可核对。

完整浏览器、真实模型和测试 XML 路径逐项记录在矩阵。上述局部结果不证明 A1/A2 或完整 B6 通过。没有推送或创建 PR。

- `production-score-interval-binding.json`：生产SQLite报告投影→job_summary→保存scored evidence→recommend_job的None+[20,60]契约及完成校验，synthetic provider/0收费调用；准确区间通过、捏造点分/错区间/薪资数字拒绝。对应129项与综合214项回归，不是B6真实成果通过。
- `analyst-qualification-recovery-failure-and-usage.json`：最新原analyst失败，58主calls、978020总input，1评分/0推荐/final无URL；保留完整用量。
- `real-eight-dedup-semantic-failure.json`：89.015s性能失败（用户要求暂缓优化）及实际需求误删语义失败；5primary/八岗alias和warm零调用不能替代准确性。

- `analyst-interval-completion-failure-and-usage.json`：原 analyst 1 条合格推荐 43.95，但缺第二岗且主/总输入均超 100 万，保留完整用量。
- `request-volume-final-replay.json`：实际末轮 60308 /重建 60333 字符，修复后含拒绝摘要 45404，合成 8/20/58 条拒绝均在 48k 内；只做保存末轮反事实重放，不声称整轮预算通过。
- `interview-main-feedback-failure.json`：原主聊天 acceptance-to-visible-feedback p50=110.097s>30s，含排队等待及完整费用。
- `interview-async-first-failure.json`：首轮异步/FIFO 失败后的持久 queue、receipt、session、问题、答案、反馈诊断；采集发生在 teardown 后，不能冒称失败瞬间快照。
- `interview-ui-fixture-failures.json`：Node career 标记及 Chrome 刷新/移动入口夹具失败归因，保留原日志/XML/数据库，不误计产品排序或导航缺陷。
- `latest-status.md`：请求体积、异步反馈、确定性版本竞争、恢复及完整 A–F 状态补充。
- `phase4-repair.md` / `phase4-and-shared-quote-evidence.json`：公开ATS读取、跨工具阻断、真实本地Chrome接管恢复、Senior-only原始用户约束及所有增量失败/最终回归哈希、skip原因。
- `phase4-public-probe-v1.json`：一次免费公开Ashby/Workday发现及各一目标详情读取，完整公共正文/来源/hash；不代表搜索完整或岗位匹配。
- `cover-style-first-failure.json` / `cover-style-policy-v5-failure.json` / `cover-original-revision-evidence.json`：E5原失败、seed语义判定不一致及冻结FAIL真实修订；事实修复通过但实际风格仍失败，完整账本保留。
- `../../benchmarks/fit-labels-v1-report.json` 与仓库 `evals/fit_labels_README.md`：96人工复核pending、288缺预测、质量指标null；离线契约不冒充human gold。
- `analyst-phase4-recovery-failure-and-usage.json`：最新analyst52调用/0岗位/0推荐终态失败、实际原答复、完整账本及原产物SHA256；末24动作不冒充完整52轨迹。
- `analyst-phase4-offline-repair.md` / `phase4-offline-and-cover-v8-evidence.json`：受阻待办、搜索候选、跟踪身份、跨工具无进展、缓存导入与Chrome恢复的局部修复/原失败/最终测试及请求大小边界。
- `cover-style-v8-offline.md`：冻结真实修订稿的生硬开头/重复邀请定位与策略修复；事实通过、风格仍失败，不收费重复生成。

- git-review-scope-r5.json：本轮F3只读审计、链接校正和报告改动后的当前清单；旧F2 r1/r2保持历史，r2曾独立199哈希/200含自身check通过，不用旧通过代替当前。根目录E2E_GIT_REVIEW_SCOPE_2026-10-11.md提供审阅说明。
- tmp-cleanup-dry-run-r1.md/.json：F3只读盘点、引用子树保护、精确候选路径/体积/重建依据和监督E5独立补充；完整本地清单留tmp，全部deletion_eligible=false，F3清理未完成。
- interview-failure-lock-offline.md / interview-failure-lock-offline-r1.json：生产SQLite/Event长锁before、首轮取消失败原库、after-v2及最终95通过3跳过，独立21/4项SHA与重叠边界；不是C16真实延迟通过。
- cover-style-screen-offline-r1.md/.json：重复invitation有限规则一致性before4失败1通过→after47通过2付费跳过，原冻结稿和verifier不变；E5真实风格仍失败。
- independent-acceptance-20261011-r2.json：监督四XML路径、给定/实测SHA和原始计数，不覆盖旧r1。
- f2-audit-evidence-r1.json：审计器before/after、权限/命令错误及范围边界；非收费产品测试。

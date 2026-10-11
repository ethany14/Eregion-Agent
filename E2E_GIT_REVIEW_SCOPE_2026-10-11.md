# F2 拟提交范围与未完成验收 · 2026-10-11

**本地提交说明（2026-10-11）**：用户已明确授权 commit；此前验收轮“未stage/commit”保留为历史记录。提交前暂存检查发现两处EOF空行，已仅修格式，未改变功能/阈值/失败结论。r4保留为提交前中间快照，链接标题对齐后的最终清单为git-review-scope-r5.json；旧r3原205哈希/206含自身check exit0保留为历史，不覆盖。只提交本地，推送/PR仍待批准，无收费重测或清理。

本文件是提交前的审阅材料。当前结论见 [完整 A–F 矩阵](E2E_ACCEPTANCE_MATRIX_2026-10-11.md)；没有完成整体验收。本轮未 stage、commit、push、创建 PR、批量清理或调用收费 API。

## 拟提交范围

精确路径、工作区状态、大小、SHA-256 与分组见本轮新 [git-review-scope-r5.json](docs/diagnostics/remaining-2026-10-11/git-review-scope-r5.json)。它记录本分支相对当前 HEAD 的修改和未跟踪文件，不声称全由本轮产生。清单本身列入范围，但不计算自身递归哈希；后续变化须建立新 revision。

旧 F2 r1 保留原192哈希文件/193含自身的历史快照；C16 controller 和新增路径变化后，旧 `--check` 正确失败。r2原199哈希/200含自身生成和本地/监督独立check均exit0；本轮F3与报告链接校正后也仅代表历史快照，不覆盖或拿旧通过当当前通过。`catalogue-attempt-offline-r1.json` 的33项是另一个固定归档，仍保持原哈希。

| 分组 | 保留原因 |
|---|---|
| 生产 Python / 前端 | A–F 修复、可信目录公共机制、实际 attempt 归因；默认目录路线不变 |
| 测试 / 冻结夹具 | 可复跑反例，包括真实失败的有界派生数据；不包含完整浏览器会话或数据库 |
| evals / benchmarks | 6×12 待审模板、严格离线评测、冻结输入/签名、显式 live 入口；pending 标签和空质量指标保留 |
| scripts | 复现、证据导出、免费公开读取探针、审计工具；有 live 能力不表示本轮执行过 |
| 根报告 / diagnostics | 当前矩阵、原计划、历史失败报告、精简用量、哈希索引；历史通过不提升当前状态 |
| .gitignore | 数据库、上传文件、完整浏览器记录、tmp 和历史原始输出不进入新提交 |

十份 `tests/fixtures/remaining_*.json` 是正文污染、请求体积、拒绝恢复、实际回复/评分回归所需；冻结的 `main-stability-plan-20261011/{manifest,frozen-inputs}.json` 支持指定版本重放，均保留。它们不证明真实稳定性或人工 gold 通过。

## 本地原始记录

- [首轮索引](docs/diagnostics/e2e-2026-10-10/publication-index.json)：7 文件、213130 bytes。
- [修复期索引](docs/diagnostics/repairs-2026-10-10/publication-index.json)：31 产物、1983038 bytes，含完整 JSON、日志、XML、截图和数据库。
- 以上 38 个产物共 2196168 bytes，全部保留原路径，仅忽略 Git。索引保留 SHA-256、大小和 XML 历史计数；没有删失败或覆盖原始输出。新克隆只能得到索引，无法直接打开本地原件。
- `tmp/`、`.env`、数据库/WAL、上传简历、完整浏览器会话继续忽略。旧 `catalogue-attempt-offline-r1.json` 不改写；25 产物 + 8 实现文件仍按原哈希核验。

审计检查拟提交 JSON 中的非空凭据字段、忽略/跟踪状态及固定证据完整性，未读取 `.env`。公开 JD 的公司联系信息和合成申请人夹具保留；这不是对任意格式、所有个人信息的全面保证。

## 独立结论与审计器修复

监督提供的四份 XML 已只读核对，SHA-256 全部与给定值一致，见 [独立证据 r2](docs/diagnostics/remaining-2026-10-11/independent-acceptance-20261011-r2.json)。XML 留在监督工作区，不伪装成本轮重新执行。

| 结论 | 范围 |
|---|---|
| 目录 batch + fixed catalogue：16 通过，XML 3.659s | 显式输入/预检；默认绑定仍待用户选择；此前无输出探针不是产品失败 |
| C11：1 通过，XML 5.422s | SQLite + 合成浏览器；有效岗位 + 缺 URL 岗位，requested2/started1/opened1/resolved1，第二项错误；重放 started0、错误保留。不是实际模型多申请对话通过 |
| 审计器 before：10 失败 /2 通过 /0 error | 9 个校验缺口 + 1 个新增返回字段契约，不能称为 10 种产品语义缺陷 |
| 审计器 after：12 通过 | 监督 XML 1.301s，本地针对性回归也 12 通过；只证明审计器契约 |
| 33 个 r1 文件、38 个历史原件 | 监督独立核对哈希一致，本轮审计器也核验；不等于评分质量或真实模型通过 |

原 `--check` 只校验哈希/路径，会把失败审计清单复核成通过。现在原失败、缺失/无效 checks 必须失败，并重新执行当前忽略规则、已跟踪原始文件、凭据字段、33 文件及 27 行矩阵门槛；修改清单哈希也不能绕过当前门槛。首轮 Temp 权限错误和 `check-ignore -z` 参数错误分开保留，不算产品回归。详见 [F2 before/after](docs/diagnostics/remaining-2026-10-11/f2-audit-evidence-r1.json)。

只读复核（不写 Git 索引、不调用模型）：

```powershell
.venv\Scripts\python.exe -X utf8 scripts/audit_e2e_submission_scope.py --check docs/diagnostics/remaining-2026-10-11/git-review-scope-r5.json
```

文件变化后用新的 `--output ...r6.json`，不覆盖 r1/r2/r3/r4/r5，不拿旧通过代替当前复核。实际计数、关键审计门槛和 errors 见新清单及命令输出；审阅材料先落盘后才生成/复核清单。

本轮F3只做只读候选审计，精简 [报告/重建依据](docs/diagnostics/remaining-2026-10-11/tmp-cleanup-dry-run-r1.md) 与JSON拟提交，完整逐文件盘点留tmp并记录SHA，不进入Git。保护所有现有目录引用子树；未知库、失败、用量和截图不因未引用而删除。15项审计器契约通过，不执行重建命令。矩阵A5证据链接producti0→product0校正，未重跑测试。F3清理仍未完成，全部deletion_eligible=false。

## 本轮 C16 / E5 增量

C16 的下一题 RPC 阻塞导致反馈失败等待落库已用生产 SQLite + Event 复现，缩小 deferred 路径锁范围；首轮 after 暴露取消后晚草稿把 cancelled 改回 failed，原 DB/事件保留并补终态保护。before3失败→after3通过1失败→after-v2原4项通过；最终相邻 **95通过3跳过/63.389s**，总98不能写98通过。监督21项及终态4项 SHA 已核对，有重叠，不算25 unique。详见 [C16证据](docs/diagnostics/remaining-2026-10-11/interview-failure-lock-offline.md)。没有新真实延迟通过，直接同步control外层锁尚未逐入口证明。

E5 新离线反例是生产修订建议与评测筛查对 chance/空白变体不一致；统一有限规则后47通过2付费跳过，before4失败1通过保留。没有生成新稿；原 grounding 通过、风格失败原样保留。[E5增量](docs/diagnostics/remaining-2026-10-11/cover-style-screen-offline-r1.md)。

## 仍缺的工作与输入

| 原项 | 当前缺口与下一步 |
|---|---|
| A1 | 无已保存 Jev 目录时的默认策略待用户选择；共同可信输入机制已完成。真实四冷 spread≤8、典型≤30 要求、32 次/6 并发/0 timeout 未测，须在路线和版本冻结后安排；本轮不收费启动 |
| A2/A4 | 尺度/告警阈值、partial 准确率/AUC 需要已审核 gold 和冻结 baseline。0.5 权重、原阈值不变；确定性防护不能代替质量指标 |
| A3 | 审阅 `fit-labels-v1-review-units.json` 的 12 来源 + 12 要求目录 + 72 人岗标签，共 96 项。288 预测缺失、quality_metrics=null；模型标签不能代替人工 gold |
| A5 | cold89.015s 超原≤60s，用户要求暂缓性能优化；不重复付费，不记通过 |
| B6/#7 | analyst 最新 52 主调用、0 保存岗/0 推荐失败。已离线修候选恢复/受阻源/跨工具循环；仍欠两条真实合格评分持久推荐及预算/最终证据同时达标。本轮不自动重跑，backend 已过不重复 |
| #11/#17/#18/E1 | 部分失败计数、来源/受阻恢复、Senior-only 和内部代码防护有局部证据；真实模型最终行为与覆盖仍欠验收。两公开源可读不等于完整搜索通过 |
| C16 | 主模型 acceptance→反馈可见 p50=110.097s>30s；异步真实复测连接失败，仍未通过。快模型 ID 待用户、≤10s 未测；deferred 长锁及晚草稿终态已离线修复，直接同步control外层锁仍待核对 |
| E5 | 原修订稿 grounding 通过，但开头生硬、重复 would welcome；v8策略及本轮筛查一致性仅离线通过。需有新增修复依据的新成稿与人工风格审阅，禁止自动付费循环 |
| #9 | 本人登录和真实雇主投递由用户操作，不代为提交 |
| F1/F3 | 推送/PR 等待批准；F3只读dry-run已做，实际清理未执行。精确候选与保护理由见F3报告；失败、账本、恢复库和截图保留，不批量删除 |

并非所有剩余工作都只依赖用户输入：C16 主模型瓶颈分析、E5 策略核对及新离线反例仍可独立推进。人工标签、默认路线、fast ID、未来真实验收与本人投递分别记录，不混为整体阻塞。

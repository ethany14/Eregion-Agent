# R1 收尾与 R2 放行报告 — 2026-10-12

**当前结论：迁移准备门允许进入 R2；最终业务门仍未通过。** 用户已明确确认[门槛调整](../specs/r1-r2-api-first-gate-amendment-20261012.md)：旧 browser-first B6 失败不再阻挡采用新来源的迁移。原报告在旧规则下判定 FAIL，原始失败/用量记录保持不变；此次是规则调整，不是新的测试通过。

风险：新架构尚未证明真实搜索能交付两条合格推荐；材料 full 的真实修复后验收也未完成。R2 仅获得迁移准备放行，不等于业务发布或 optimization 全部完成。运行代码基线仍为下述修复版本；开始 R2 时核对后续变化。

## 版本与结果

- 付费测试及全量离线基线：`57c63ab4b9812ddcb0d9bc8e9f3760d1539f8a45`。
- 收尾修复：`158e55781c0467fb97d70710471d3444090af596`。只有预算停止交付、材料测试绑定、五个回归用例和说明链接；没有启动迁移。
- 旧 13 个失败/错误节点：13 passed，12 passing subtests。
- 基线全量离线：2136 passed，134 skipped，16 passing subtests，无失败或错误。
- 修复后受影响回归：53 passed，2 paid skips，无失败或错误。全量及真实结果不冒充修复后结果。
- L1 B0：10 次请求，冻结来源不足，no_progress；停止本组。B4、L2 未跑。
- L3 full：1 次请求，needs_revision；修正测试验证器绑定后仅离线回归，patch/人工评审未跑。
- L4 B0：60 次 provider 请求，provider_budget；一条内容合格且已推荐，另一条不符合 junior。因终止回复漏链接/分数，原验收完整交付计数为 0。修复此交付缺陷仍不能补出第二条。

## G1–G7

| 门槛 | 状态 | 证据及限制 |
|---|---|---|
| G1 可恢复基线 | 满足 | 隔离 checkout、原 bundle、修复 commit、新重建 bundle/manifest；原 HEAD 与其他改动保留。见 baseline 报告和交付清单 |
| G2 离线正确性 | 满足限定范围 | full + 13-node + 修复后 affected regression；opt-in skips 如实保留，不称全浏览器场景通过 |
| G3 采用决定 | 已明确 | adoption 表全部逐项关闭/延期；不在迁移中继续无界实验 |
| G4 失败与后续验收交接 | 已明确移交 | 旧 L4 仍 FAILED；API 优先 B6 归 R6/R9，材料 full 归 R3；此行不代表业务通过 |
| G5 账目 | 本轮完整，历史保留 | 本轮 71 attempts，741,045 input / 48,953 output；无新 unknown，美元费用未知；旧 L1 29,997 保守预留不释放，累计 402,777 / 2.5M。历史其他 lane 见原报告，未重置或转用额度 |
| G6 未决问题归属 | 已列明 | 历史搜索失败供迁移回归；API-first、Treg close、旧 Session 保护归 R2；材料 full 归 R3 |
| G7 配置与回滚 | 满足限定范围 | README/configuration 指向本报告与采用表；默认开关未开启，`.env` 未改；修复后已补对应离线验证，未重复收费 |

迁移准备 G1–G7 按新规则满足。旧真实业务门维持 FAILED，新的 API 优先业务门为待执行。

## 下一步执行顺序

1. R2/M1：核对当前工作区与修复基线，处理 API-first 指令一致性、Treg 关闭、旧 Session 响应保护及公共契约，补离线回归。
2. R3–R5：统一 Loop/确定性工作流与生命周期迁移，保留取消、预算、恢复和身份边界。R3 接手 full 材料 grounding 与真实验证；材料 patch 保持关闭。
3. R6：招聘板 API＋用户自配 Treg 在新体系回归，离线通过后按有界计划做 API 优先 B6。旧 L4 transcript 用于定位候选覆盖和重复成本，无需先花钱跑通旧浏览器路线。
4. R7–R8：LinkedIn MCP 验证后才可采用；未验证或未配置不影响基础来源继续。冻结来源配置。
5. R9：确认最终配置的 B6 至少两条合格推荐、完整交付与预算均通过；配置与 R6 相同则引用已有证据，有变化只补必要验证。full 材料验收及其他原业务门不能被此修订豁免。

本次仅更新文档依赖，不启动迁移代码、付费复验、账号操作或数据库迁移。旧 L1/L3/L4 失败样本及历史预算保留，实验开关未自动开启。完整执行约束见门槛修订。

## 证据入口

- [基线与修复版本](r1-baseline-freeze-20261012.md)
- [离线复验](r1-offline-revalidation-20261012.md)
- [真实 lane 与账本](r1-live-validation-20261012.md)
- [采用与回滚](r1-adoption-decisions-20261012.md)
- [可重建证据包](../benchmarks/r1-closeout-20261012/README.md)
- [R1 任务与放行标准](../specs/r1-optimization-closeout-and-r2-gate-20261012.md)
- [后续路线](../specs/execution-roadmap-linkedin-mcp-20261012.md)

原始测试文件留在隔离 checkout 的 `.r1-evidence/`，项目证据包为脱敏副本；不发布 `.env` 或真实用户数据。原始失败记录不会随修复而改写。

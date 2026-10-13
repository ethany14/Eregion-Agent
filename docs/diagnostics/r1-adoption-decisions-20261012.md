# R1 采用决定 — 2026-10-12

结论：不新增开启任何实验；旧 R1 真实业务门失败保留。按用户确认的[门槛修订](../specs/r1-r2-api-first-gate-amendment-20261012.md)，迁移准备门允许 R2，API 优先业务验收归 R6/R9。运行基线 `57c63ab4`，收尾修复版本 `158e55781c0467fb97d70710471d3444090af596`。

| 能力 | 决定及有效配置 | 证据与未测部分 |
|---|---|---|
| 已有计量、预算、决策持久化、重复读取保护 | 保留基线实现 | 最终基线全量离线通过；不据此声称真实搜索目标通过 |
| BOARD_RESPONSE_CACHE / CANDIDATE_BATCHES | 保持 `0` | 本轮不扩大采用；原离线/实验记录保留 |
| JOB_API_FIRST | 保持 `0` | prompt/tool/snapshot 顺序冲突归 R2/M1，启用前必须修复并测 on/off |
| VERIFY_AND_SCORE | 保持 `0`，采用延期 | L1 B0 受冻结源覆盖限制失败；B4 未跑，不能推断收益或回归 |
| SNAPSHOT_REFS / STABLE_TOOLS / SCOPED_CONTEXT / STATE_DELTAS | 全部保持 `0` | 本轮无充分采用证据，不与迁移并行调整 |
| PROMPT_TRIM / HISTORY_POLICY | `0` / `current` | L2 因比较基线未建立而延期；不声称无收益 |
| MATERIAL_PATCHES | 保持 `0`，采用延期 | L3 full 失败，发现测试绑定缺陷并离线修复；patch 和人工风格评审未测。full 真实验收也未关闭 |
| TREG_ENABLED / TREG_CRAWL4AI_SCRAPE_ENABLED | 保持 `0` | 不重跑已完成 Treg 比较；用户自配 key，不集中托管；本轮无 Treg 请求 |
| 预算停止的已保存结果交付 | 采用最小修复 | 本地读取，无新增推理；保留 incomplete / needs_input。三个离线边界通过，真实修复后结果未测 |
| 材料 live lane 的 writer/verifier 绑定 | 采用测试修复 | 与生产初始化一致；支持/不支持引文改写的两个测试通过；不放宽 grounding |

以上是本轮测试进程配置和项目发布默认决定，不修改维护者 `.env`。每个付费样本的 invocation.json 保留实际显式设置；未显式设置的实验采用源码默认 `0`。analysis warmup 在真实测试中为 `0`。

回滚：实验仍可设 `0`，history 恢复 `current`；两处修复可在审查版本中回退修复提交，或只逆向应用对应补丁，不删除持久状态、用量、授权和失败证据。不得在原脏工作区用 reset/clean 回滚。

后续责任：R2 实施者接手 API-first 指令一致性、Treg 生命周期、旧 Session 模型元数据保护；full 材料未决验收归 R3，API 优先搜索业务验收归 R6/R9。LinkedIn MCP 安装与外部来源扩展继续按总纲后续阶段执行。

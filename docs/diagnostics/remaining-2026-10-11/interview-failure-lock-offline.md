# C16 反馈失败持久化与晚到问题 · 离线增量

完整状态仍以根目录 1–18/E/F 矩阵为准。**C16 真实延迟仍失败**；这里仅验主聊天 deferred 路径的并发和持久化。没有网络、付费模型或真实投递。原始日志、XML、数据库和事件快照留在 `tmp/`，哈希/精简状态见 [不可覆盖证据 r1](interview-failure-lock-offline-r1.json)。

## 复现输入、根因与修复

生产 CareerService + SQLite 接收 A1，暂停下一题 Q2 的 question provider；Q1 feedback provider 立即抛 ConnectError。用 Event 确认 provider 已失败，要求在释放 Q2 前 2 秒内持久化 FEEDBACK_FAILED，并保留原 answer_id/question_id。独立 v2 和本地 before 均有效复现。

原 `answer_deferred` / `evaluate_deferred` 持 transition_lock 跨 `_ask` 模型调用；错误落库也需同锁，因此等待 Q2。现在问题草稿使用独立 mutex，deferred 路径在 RPC 前释放 transition_lock，仅数据库提交保留短锁和有界 CAS 重试；重试写入不重调 provider。同控制器的竞争调用不重复生成问题。

首轮修复又发现取消被晚到草稿覆盖：实际 SQLite 事件 7=CANCELLED，事件 8=QUESTION_FAILED，最终 failed/version8，queue failed/ValueError，答案与 receipt 各一。原诊断是 teardown 后只读快照，不冒称失败瞬间状态。问题 CAS 冲突刷新到 cancelled 后，异常处理错误使用新版本写 failed。现在刷新发现 cancelled/completed 或当前题已改变就丢弃草稿，异常路径也保留终态。

## 保留的 before/after

| 产物 | 真实结果与边界 |
|---|---|
| `tmp/c16-lock-before-20261011.xml` | 3 失败；两 deferred 入口的失败落库等待 + transition_lock 被 RPC 占有，属于同一锁范围问题 |
| 监督 `feedback-lock-before-independent-v2.xml` | 1 失败 /7.412s；更早 cwd/setup 错误不算产品 before |
| `tmp/c16-lock-after-20261011.xml` | 3 通过 /1 失败；取消晚草稿缺陷及原 DB/诊断保留 |
| `tmp/c16-lock-after-v2-20261011.xml` | 原 4 项全通过 /7.751s；未延长 wait 或放宽 cancelled 断言 |
| `tmp/c16-lock-integrated-20261011.xml` | **95 通过 /3 跳过 /0 失败 /0 error /63.389s**，总98不能写98通过。含新7项及 FIFO/CAS/聊天/结束/取消/重启/晚反馈相邻回归 |
| 监督 `feedback-lock-after-independent.xml` | 1 通过 /4.415s，原反例复测 |
| 监督 `c16-lock-regression-independent.xml` | 21 通过 /28.205s，用户报告墙钟28.21s/exit0 |
| 监督 `c16-terminal-independent.xml` | cancel/end × late draft/failure 四项通过 /7.938s；与21项有重叠，不能算25 unique |

三个跳过分别为收费主反馈、收费 fast 反馈和 configured-model 工具链。四终态组合要求严格 cancelled/completed、队列 done、答案恰好一次、无晚到新题、questions_completed 恰好一次；没有删除 end/cancel 断言。监督 XML 只读核对 SHA，与用户给定值一致；没有把监督运行写成本轮执行。

## 真实链路与剩余边界

原真实 DB 显示反馈失败后约6.976s才写 FEEDBACK_FAILED，紧随并发下一题完成。该时间关联本身不是因果证明；上述 Event 测试补充了因果反例。原用量和失败没有改写。

原主模型接收到反馈可见 p50=110.097s>30s；异步真实轮连接失败，存在未知用量，仍失败。fast ID 缺失，≤10s 未测。此次离线通过不证明延迟达标，也没有重复付费。修复覆盖主聊天 deferred 路径；直接同步 control 的外层锁范围尚未逐入口证明，不能声称所有调用方均无长锁。

A5≤60s 保持 FAILED/user-deferred；A1 默认路线、A3 人工 gold、B6 两岗成果、E5 真实风格等原缺口不变。

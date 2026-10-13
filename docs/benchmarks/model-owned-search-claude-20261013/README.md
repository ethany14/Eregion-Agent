# Claude 接手轮次证据（2026-10-13）

入口：[交接报告第 7 节](../../diagnostics/model-owned-search-handoff-20261013.md#7-claude-接手执行结果2026-10-13)。

- `evidence-summary.json`：16 次真实验收（`default-batch-claude-model-owned-01`…`16`）逐次的代码版本、结论、失败原因、按路线（主模型 / 资格判断 / Jev）的调用与 token、盲审用量、耗时、LinkedIn MCP 调用数、推荐清单（标题、公司、地点、公开 URL、分数、盲审结论、模型给出的风险）；以及全部付费探针。不含岗位正文、简历、凭据、会话或 SQLite。
- `offline-validation-68db2c9.txt`：最后一次真实运行所用版本的离线回归结尾（本地路径已替换为 `<repo>`）。

美元成本：没有账单证据，记为未知（`null`），不是 0。`unknown_usage_calls > 0` 的条目 token 合计只是下界。

原始资料只在本机 `.codex-runs/` 下：`default-batch-claude-model-owned-NN/`（transcript、provider/source 账本、盲审、隔离 `career.sqlite3` / `fit.sqlite3`）、`claude-*-probe-*`、`semantic-qualification-probe-claude-strict-01`、`claude-c1/offline-*.log|xml`。不得提交或上传。

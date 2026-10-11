# 历史首轮诊断 · 本地原始记录索引

当前验收以 [完整 A–F 矩阵](../../../E2E_ACCEPTANCE_MATRIX_2026-10-11.md) 为准。本目录是 2026-10-10 首轮诊断，不是当前通过结论。

[publication-index.json](publication-index.json) 列出 7 个原始文件的路径、大小和 SHA-256。完整输出仅留本地并由 Git 忽略，未删除或改写；新克隆只能得到索引，不能直接打开这些原始输出。

首轮根因、复现及失败见 [根因分析](../../../E2E_ROOT_CAUSE_ANALYSIS_2026-10-10.md) 和 [原测试报告](../../../E2E_TEST_REPORT_2026-10-10.md)。后续需要复跑的冻结反例位于 `tests/fixtures/remaining_*.json`，随测试纳入拟提交范围；它们不是完整浏览器会话或数据库。

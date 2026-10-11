# 修复复验数据索引

完整说明见仓库根目录 `E2E_REPAIR_REPORT_2026-10-10.md`。

**F2 发布范围（2026-10-11）**：本目录仅拟提交本 README 与 [publication-index.json](publication-index.json)。索引记录31个原始产物的路径、大小、SHA-256及XML原始计数；下列JSON、日志、XML、数据库和截图全部留在本地、由Git忽略，未删除或改写。新克隆不能直接打开这些本地原始产物。历史1300通过不等于当前完整A–F验收通过，当前结论见根目录矩阵。

- `matrix/comparison.json`：24 组真实评分输出，四位匿名虚构申请人和三类合成职位；保留执行时人工参考标签。两处 Python API 参考标签经复核修正于复跑脚本，未改写原始输出，不据此计算准确率。
- `matrix/format-variants.json`：简单 JD 换行和平铺的缓存一致性结果。
- `refined/jev-*.json`：最终有界澄清策略对复杂公开 JD 的三次冷请求。上级同名文件是策略调整前的中间探针。
- `repair-final-full.xml/log`：最终完整 Python 套件；包含浏览器测试。
- `repair-node-final.log`：23 项前端测试。
- `repair-ui-final.xml`：34 项上下文及 UI 专项，全过。
- `repair-source-verified.xml/log`：25 项结构、PDF、材料版本专项，全过。
- `repair-control-error.xml/log`：直接控制异常专项，全过。
- `repair-interview-verified.xml`：中间面试专项，原先两个面试浏览器用例已过；还有一个新增上下文断言失败，后续已修复并在 `repair-ui-final.xml` 中通过。不可将此文件当成最终全绿套件。
- `repair-live-career.xml/log`：真实规划首次运行的夹具失败（模拟 URL 意外导航到真实 404）。
- `repair-live-career-verified.xml/log`：补全浏览器模拟后的真实规划复验，通过。
- `screenshots/`：两页面 × 日夜主题 × 桌面/手机，八张已检查截图。

这里的测试数据库和缓存由 Git 忽略；原始诊断数据库与生产数据未被改写。

# Phase4：来源恢复与资历约束

当前范围为原 #17/#18。以下局部通过不替代 B6 原输入两条合格推荐、60 主调用、主/总输入各 100 万及完整 ledger；A5 ≤60s 仍失败并按用户要求暂缓。未登录/投递真实雇主、未推送/PR。

## 复现、根因、修复

| 输入/失败 | 根因 | 生产修复 | 证据 |
|---|---|---|---|
| Ashby synthetic-blocked 403，换 query/新 harness 仍四次 HTTP | board 错误无 source，boards 分支忽略 exclusions | platform/company/host/site 稳定身份；整个用户 turn 持久健康表；不封禁 Ashby 共享 API 全域；原始表不裁到8条 | remaining-phase4-before.xml，board 4≠1；首轮 seniority 用例缺 read，另列夹具失败 |
| 完整 read→import→score→recommend 接受 Staff，用户 Senior only | recommend 入口不核对用户级别 | 原用户消息确定性提取并持久化 search_constraints；严格 only 冲突拒绝；非exclusive mismatch 自动持久化真实 caveat；模型 query/计划不具有修改权限 | remaining-phase4-seniority-before.xml；修后 SQLite 路径、重启/150消息裁剪、用户明确修改及尾部两语序回归 |
| 否定 include / 询问 JD / 练面试误改约束 | 广泛关键词匹配把引用当指令 | 限直接搜索与明确条件修改；独立后续 Senior only 条件句；不采纳 JD 解释或否定添加 | intent-before 3fail，tail-before-v2 2fail/1pass；修后 complete-local 81pass。tail-before 为 pytest 保留参数名收集错误，保留且不算产品失败 |
| Workday External-Careers 与 Other-Careers 身份碰撞 | 任意带“-”首段被误认 locale | 使用与详情读取一致的严格 xx-XX locale 规则，API/browser同身份、不同站隔离 | workday-identity-before 1fail；后续本地集成通过 |
| Ashby/Workday 只发现列表，无法读取公开详情 | job() 未实现两种 ATS 详情路径 | Ashby 唯一 jobUrl 绑定的单条 record；Workday public CXS 单岗 GET，校验返回 externalPath。保留完整目标 body、标题/地点和正文/歧义保护 | detail-before 2fail；修后实际SQLite search→read→import→score，synthetic HTTP；真实公网另见下文 |
| 浏览器 open/read 更换 query/page 反复受阻 | research_pages 只记录 blocked，没有入口预检 | 用户 turn+source 持久阻断；内部 revision 不重置；浏览器、read_job/import_job 远程采集同一守卫；首次 HTTP 401/403/429 和内部 rendered/分页阻断落库 | browser-before 1fail；cross-tool-before 2fail；acquisition-after 55pass8skip（8项全部 job_body Chrome opt-in，不计通过） |
| 已人工解除但 inspect 仍为旧登录页 | BrowsingManager 控制只清 session observation/更新 preview，没有更新 states | 明确用户 Control end 时一次实际 read 更新缓存；新观察确认同源不再 blocked 后允许恢复；不增加模型轮询或绕过验证 | chrome-before 1fail（真实本地Chrome）；chrome-after 1pass；新 wrapper 下 acquisition-final 4pass0skip，再验证实际控制恢复 |
| 诚实 “Indeed was blocked” / “DuckDuckGo was blocked” 被拒绝 | 前者仅接受完整 host；后者误取 html 子域为名称 | 绑定实际持久 source 的完整域名/主域名称；Bing/HTML 不能代替 DuckDuckGo。受阻来源只披露一次，但不能宣称不存在职位 | final 131pass1fail1skip；disclosure-fixed 53pass；ddg-before 1fail→ddg-after 2pass |

健康状态绑定持久 `user_turn_id`，不是内部 `chat_revision`。完整表用于跨工具预检；模型观察仅展示有界8条与数量。实际新用户消息可重试；已验证的新浏览器观察可恢复；无法用 query、分页或工具切换制造解除阻断。原文 job_text 无需远程访问，但仍必须引用真实用户消息中的逐字正文。`pasted_job_text` 的测试语义判断是显式离线 fixture，不冒充真实模型。

最终补充：`remaining-phase4-acquisition-final.xml` 4pass/0skip/9.456s，含首次403、新turn重试、字面正文合法导入、内部首阻断及真实本地Chrome控制恢复；`remaining-phase4-acquisition-boundaries.xml` 2pass/5.83s，含伪造正文/消息拒绝与分页阻断后零额外内部采集。截图 blocked.png/recovered.png 已目视，保存在原 chrome-after 和 acquisition-final 子目录。原失败 XML/log/数据库路径未删除。

## 免费公网与真实流程范围

`phase4-public-probe-v1.json`：2026-10-11 公开 Ashby linear、Workday nvidia 各一次 search 和首个目标详情读取成功（约1.04s、2.47s），记录完整公开目标正文、URL、标题、地点、body scope/hash。0 provider calls；没有候选人数据、登录或投递。仅证明这两个公开租户在当时可读，不能证明所有站点、全部岗位或搜索成果合格。脚本 `scripts/phase4_public_probe.py` 不覆盖原证据。

唯一一次原 analyst 付费复测已自然终态失败：52calls/336.75s、0保存岗位/0推荐、needs_input/no_progress。主/总输入均715985，输出30044，完整52条账本；原门槛未改，不收费重跑。末24动作与52用量边界、SHA256、实际最终答复及后续离线修复见 [失败离线报告](analyst-phase4-offline-repair.md)。backend/A5不重跑。

## A3 共享引用度量修复

原并集匹配使两条原子要求共享 source quote 时均匹配两个 gold，144/144 合成反例 precision/recall/status/level 为0。现在优先唯一 atomic/人工确认 alias，再唯一 quote 回退；所有 gold（含已使用项）参与身份判断，防止重复预测借共享 quote 偷占另一要求。真歧义仍拒绝，漏项/重复计罚。

`remaining-fit-shared-quote-before.xml` 3fail1pass；修后含结构/PDF相邻65pass，增加人工别名与真alias歧义后 `remaining-fit-shared-quote-final.xml` 22pass/3.48s。这些标签仅测试内存中的合成数学夹具，未写入真实数据集。12来源+12要求+72匹配人工复核仍96pending，288预测缺失，质量指标仍null；原3.2评分差/数量比及A1/A2/A4门槛未改、未判通过。

所有局部 XML 哈希、失败摘录、skip 原因和范围归档到 `phase4-and-shared-quote-evidence.json`；原始文件继续保留在 tmp。

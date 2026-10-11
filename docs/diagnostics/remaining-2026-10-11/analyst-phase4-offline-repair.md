# B6 Phase4 失败与离线修复

本轮真实模型仍 **失败**，没有再次付费复测。task `f01db209-c5a7-4695-9a54-9f019ded74d3`：52 主调用、336.75 秒、0 保存岗位、0 推荐，`needs_input/no_progress`。主/总输入均 715985，输出 30044，52 条账本全部 completed、用量完整。两条合格、已核实、评分且持久推荐的原成果门槛未达到；60 次/主总各 100 万门槛未修改。

原始 summary、transcript、acceptance、XML、日志、实际最终答复及逐调用账本的路径/哈希在 [失败与用量归档](analyst-phase4-recovery-failure-and-usage.json)。实际最终答复是停滞通知，不是交付完成。原始文件未改写。

## 证据范围

`history` 只保留末 24 条：15 条 no_new_evidence、7 次 search_jobs；不是完整 52 次工具参数/结果轨迹。另有 52 条 action 名称/时间/成功失败标签和 52 条 provider 用量记录；这些不能补造被裁掉的早期动作参数。冻结离线夹具是 `tests/fixtures/remaining_phase4_analyst_failure.json`。

6 个实际 Joblist URL 只有 msockid 不同：修复前 job_key 有 6 个身份，但 **已有 search_evidence 指纹只有 1 个**。原搜索进展归一化正确，未将其错误归因为搜索假进展。问题在 URL 候选存储和跨工具持久身份不一致。

## 复现、根因、修复

| 真实/合成复现输入 | 根因 | 修复与针对性边界 |
|---|---|---|
| 冻结 recovery 返回 8 个 Indeed 待办，8 个源均已 blocked | 恢复只读浏览器候选，不检查持久 source_health | 恢复与执行守卫共用同用户 turn 健康；健康搜索结果也能进入有界 read_job；新 turn、用户 Control 后真实正向观测恢复。snippet 不自动导入或推荐 |
| 真实搜索结果单独留在 search_candidates，恢复无候选 | 恢复遗漏搜索工具观测 | 统一两种观测入口，输出实际 URL 的有界读取参数；验证/资格门槛不变 |
| 6 个 msockid URL | job_key 未去该跟踪参数，存储按原 URL | 候选按规范身份存储；仅去明确跟踪字段，保留 jobId/jk/q/location/page。screen_jobs 消费者同步规范身份，旧拒绝键保留 URL 回查 |
| 冻结同 query 改 limit，反复返回同 6 条 | 无同 turn 请求结果复用 | 相同 query/location/boards/健康状态复用已取得的非截断列表，不再 HTTP。确实截断列表增加 limit 可扩展；新 turn/来源状态变化可重查 |
| 已 blocked 的 read_job、跨工具 repeated_action | 普通错误首次指纹被当作进展；部分 repeated_action 未带 no_new_evidence | 结构化 source_blocked 与 repeated_action 明确无新证据；停止阈值仍 3，未靠降阈值修复 |
| 完整读 parent 后再读 jobs 子字段、历史裁剪后重读 | 投影视图/短期历史窗口允许重新计进展 | 完整祖先覆盖的子读取仍返回原文，但不算新证据；浏览/上下文观测指纹持久化。真正未读范围、新详情仍可推进 |
| 有合法 Indeed 已保存正文，恢复提示 import，却被外层 source guard 拦截 | 将本地缓存导入当远程访问 | 同身份缓存正文导入走本地生产链；候选 preflight、正文资格及原拒绝保护继续执行；无缓存读/导入仍阻断，无效 JD 拒绝 |
| 实际 Zippia 文案 Verifying you are human | BrowserSession 只识别 verify，未识别 verifying | 本地真实 Chrome 复现后修 stem；标记挑战后切源，未操作真实验证码；用户 Control 的新正向观测可恢复待办 |

## 回归及失败保留

- `tmp/remaining-phase4-replay-before.xml`：12 失败。身份 6 项、恢复/来源/停滞/上下文反例失败；其中一项先在夹具 recommendations=null 失败，**不能当作候选过滤前证据**。
- 夹具已按真实缺省列表修正；`tmp/remaining-phase4-recovery-before-v2.xml` 使用冻结修复前函数体，1 失败，实际断言明确 **8/8 待办受阻**。不是改写原失败或回滚生产代码。
- `tmp/remaining-phase4-replay-after.xml`：11 通过/1 夹具失败；after-v2：13 通过。
- `tmp/remaining-phase4-cached-import-before.xml`：真实 SQLite 同岗缓存导入被 SourceBlocked 拒绝，1 失败；修后合法缓存、无缓存阻断、无效正文拒绝通过。
- `tmp/remaining-phase4-replay-integrated.log`：测试文件名错误，未执行测试；保留，非产品失败。修正入口后 integrated-v2：**95 通过/50.75 秒**，含 TaskLoop、权限、原请求体积和告警。
- `tmp/remaining-phase4-challenge-before.xml`：本地 Chrome 文案识别 1 失败；修后 `tmp/remaining-phase4-replay-chrome-final.xml`：**25 通过/0 skip/20.965 秒**。包括实际 Chrome Control 恢复、身份消费者、持久拒绝；截图见同名目录。监督已独立核对截图及缓存 SQLite 链。

## 请求体积边界

真实最后请求 52846 字符，超过 48000，protected_overflow=true。只读 ledger 又恢复了 **52 次请求的大小**：46 次 context_chars+tool_schema_chars 超 48000；这提供大小证据，不提供缺失的早期请求全文。原归档 1418233 字符不是 provider 输入。

终态反事实重建见 `tmp/remaining-phase4-request-replay-v2/request-volume.json`：45346 字符；system13924、tools7501、replay1233、snapshot22688。保持实际浏览器依赖的工具组、current_request、简历、浏览器、已读 context_evidence 原文及缓存岗位入口。search_recovery 从原记录4089变为1762字符，去掉不可执行受阻待办；旧历史按原压缩策略取回。v1 遗漏浏览器工具 schema，不作为最终体积证明。**终态重建不等于修复后整轮真实预算或成果通过**。

backend 不重复收费；A5 原 60 秒失败继续按用户要求暂缓；其余 A–F 状态见根目录完整矩阵。

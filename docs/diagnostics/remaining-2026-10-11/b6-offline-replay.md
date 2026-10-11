# B6 离线回放验收（2026-10-11）

已将中断草稿落地为 `tests/test_b6_offline_replay.py` 和
`tests/fixtures/b6_offline_web.json`。四条回放均运行真实 CareerService、TaskHost、
loop engine、CareerHarness、SQLite、read/import/score/recommend、完成校验及原版
`scripts.remaining_search_acceptance.evaluate_search`。主模型只发出脚本工具调用，
公开 web 由严格冻结 double 提供。本轮没有生产代码修改。

离线正确路径通过不替代真实 B6 两岗验收。真实 r1/r2/r3 及其原始失败记录保持，
B6 live 仍失败。

## 证据来源与 fixture

以下路径是原始来源；每组均引用 `summary.json`、`transcript.json`、
`acceptance.json`、`career.db`：

- r1：`tmp/remaining-live-analyst-20261011-claude/test_long_real_search_conversa0/`
- r2：`tmp/remaining-live-analyst-20261011-claude-r2/test_long_real_search_conversa0/`
- r3：`tmp/remaining-live-analyst-20261011-claude-r3/test_long_real_search_conversa0/`

原目录的 owner-only ACL 使沙箱不能读取。本轮只读取用户提供的逐字节相同副本
`.codex-runs/b6-evidence/r1|r2|r3/`；没有读写原件或改变 ACL。fixture 的
`provenance.sources` 记录全部 12 个原路径、实际读取副本路径、字节数和副本 SHA256。
提取前后副本 SHA256 一致。数据库使用 SQLite `mode=ro` 打开。

fixture **203,896 bytes（199.12 KiB，低于 300 KB）**，SHA256：
`76be3eab84f6249c7c43134272e1438a4d46b68c79a49b62fee0cf11931821b0`。
它包含 14 个公开浏览器观察、两个公开搜索查询、12 个 HTTP/API 记录或错误投影、
两份真实岗位正文及 gainam 的公开人才库正文投影。来源标签为：

- `real_recorded`：r1 `retrieved_jobs` 中 GoodApple Data Analyst（0-2 years）及
  Associate Data Analyst（minimum 1 year preferred）的真实正文。
- `recorded_projection`：公开搜索、登录/Cloudflare 观察、gainam/Joblist/Jooble/
  ZipRecruiter 等公开页面，以及从保存结果重建的 board API 形状/错误。
  移除导航 tracking 与 Cloudflare challenge 参数，不携带 cookies、tokens、
  provider 凭据、个人申请数据或 provider 账本；只保留脚本所需的公开工具决策。
- `synthetic`：**唯一**虚构岗位 B6 Synthetic Analytics / Junior Data Analyst，
  New York, NY，明确 1-3 years of experience。list/detail 两个响应指向同一岗位，
  用于 board 过滤正例和正确路径第二岗，不代表真实在招。

申请人使用既有合成 `APPLICANTS['analyst']`。评分复用
`test_remaining_fixed_catalog.main_handler`：ResumeAnalysis/SkillAssessment 是离线
double，需求目录、匹配分数计算、保存与推荐均使用生产流程。double 把所有需求
标为 missing，因此本次保存点分是 **0.0**；这是绑定/流程验收，不是评分质量判断，
也不复刻历史 live 的 42.18/48.18。生产代码没有固定分数。

## 回放断言与结果

| 回放 | 主要断言 | 实际结果 |
|---|---|---|
| r1 | 原 20 步工具名及顺序；gainam 由生产校验拒为人才库；Associate 推荐有 Level unverified，且 caveats 前置警告；GoodApple 全部资格检查通过；Associate seniority 不通过 | 20 calls，completed，2 保存/评分/推荐；qualified_count=1，evaluator 按预期 failed，唯一失败为 fewer_than_two_verified_scored_qualifying_recommendations |
| r2 | 第二次已见公共搜索立即 no_new_evidence 并给 boards 指引；后续重复及 limit=2 的子集仍不算进展；保持候选拒绝；原 60 calls 之前停止 | 11 calls，needs_input/no_progress，0 保存/推荐 |
| r3 | 真实 board parser 过滤 r3 保存的 20 个噪声行；包含 Accounts Payable Analyst 和 AI Research Scientist - Datadog AI Research (DAIR) 的原记录都不进入结果；同一 parser 加唯一合成 board 后只返回 Junior Data Analyst；保留 Ramp/Plaid 错误类型 | 2 calls，completed，真实记录投影返回 0 匹配；正例返回 1；错误为 Ramp ValueError、Plaid HTTPStatusError |
| correct | LinkedIn 阻断披露→四家原 board 加合成 board→read/import/score GoodApple 和合成 junior→recommend 两岗→finish_task；最终逐岗 URL 和分数与实际保存值精确一致，无资历警告 | 11 calls，completed，2 保存/评分/推荐，qualified_count=2，原 evaluate_search status=passed；两岗保存和最终点分均 0.0 |

所有回放都断言 provider ledger **0 calls**，无申请运行、无日程。
未知 HTTP URL、公共搜索查询、浏览器 URL/动作必须失败，错误即使被生产 loop 捕获，
teardown 的 `unexpected`/IO attempt 记录也会使测试失败。
额外两项测试验证未知 IO 必须失败，以及冻结登录/Cloudflare/聚合页错误仍产生
记录中的阻断值和生产异常类型。

网络守卫禁止 DNS、socket connect/connect_ex、真实同步/异步 HTTP transport、
provider 初始化和 provider_call，并检查尝试记录为空。Windows asyncio 内部
socketpair 自唤醒允许本地 IPC；直接 loopback 和外部连接仍禁止。
简历保存的既有模型 warmup 在 fixture setup 前禁用。
evaluator 使用明确标识的 scripted 零 token 决策账本，实际 provider ledger 单独为空；
不将 scripted calls 冒充真实 provider 用量。

同文件包含 `JOB_AGENT_B6_REPLAY_LIVE_MODEL=1` 的配置模型 lane：真实 TaskModel
对同一冻结 web 与离线评分运行；默认跳过，本轮未运行任何付费/live lane。

## 生产问题与既有修复

本轮没有发现需要额外修改生产代码的 bug，也没有改变 evaluator、门槛、预算或既有测试。
本轮验证了任务开始前当前分支已有的三个修复：

| 原问题 | 已有修复提交 / 生产位置 | 聚焦回归 |
|---|---|---|
| 无级别词标题被静默当 junior；preferred minimum 1 year 不证明岗位资历 | `fa214ad` / `agent_runtime/career/search_policy.py`，正文有明确 junior/entry-level 或有上界年限才验证级别；否则推荐前置 Level unverified | `test_e2e_followups.py::test_level_free_title_needs_opening_level_evidence_for_junior_request`，新 r1 回放 |
| 重排、截断、窄化已见搜索结果被计为进展 | `6808c7e` / `agent_runtime/task_host.py`，按本请求已见候选 identity 判定子集并提供 board 指引 | `test_remaining_search_runtime.py::test_narrower_or_truncated_repeat_of_observed_search_links_is_not_progress`，新 r2 回放 |
| board 任一共享词匹配，使 Accounts Payable Analyst / AI Research Scientist 入围 | `616c01a` / `agent_runtime/career/discovery.py`，共享公开搜索 role-term 规则，排除级别及填充词 | `test_e2e_followups.py::test_board_search_needs_role_terms_not_one_shared_word`，新 r3 回放 |

## 不能逐字复现的部分与处理

数据库归档是 `career_tasks.state_json.loop_runtime.context_archive` 中的公开观察和
工具结果，不含原始 HTML、原始完整 board JSON 或 HTTP 响应。Greenhouse 只保存了
搜索工具截断后的 Datadog 17 / Braze 3 行，全部不匹配 data+analyst。
按保存的 URL/title/location 构造 API 形状的 **recorded projection**，让生产 parser
执行过滤；不宣称能复现四家公司完整职位目录或其全部合格岗位。
唯一合成职位同时提供过滤正例，避免把空结果当作充分证明。

Ramp 只留 ValueError，Plaid 只留 HTTPStatusError；精确状态码、原始错误正文不在
归档中。double 抛同类错误，HTTP response status **0** 明确表示未知，不推测 403/404。
其他聚合列表的 read_job 错误也使用记录的异常结果投影。冻结浏览器保留来源中
实际分类：r2 Indeed 观察被标为 credentials，hiringcafe/ZipRecruiter 为 bot_challenge，
不重新解释成不同历史结果。gainam 只投影真实 Job description 区间，排除周围导航 CTA，
再交给生产当前岗位校验，得到 not_current_vacancy。

r1 的 observation_id、application_id、context_ref 是一次运行的身份，重新绑定为
当前生产循环生成的身份。模型从 ToolMessages/当前 snapshot 读取新 refs，仍由真实
read_context 访问归档；第 10 步读当前 controls path，第 17 步改读当前评分结果，
原来的 transient recommendations projection 已在 snapshot 中可见，不重造旧 ref。
最终文本使用当前保存点分，并诚实披露 Associate 级别未验证；不重放历史误称两岗 junior
或把历史 live 点分粘到新报告。保持原 20 个工具名和顺序。

r2 采用记录中的前 8 步，再接第 8/15/17 步重复搜索，最后一个 limit 改为 2 的
明确回归变体；不声称复刻全部 24 次 live 调用。r3 隔离原 history[20] 的 board 搜索，
不重演后面的浏览器超时或实际 provider 决策。
同一公共查询采用首次保存的结果，并按 blocked hosts/limit 投影；不重现各次实时搜索
的标题或 tracking 参数漂移。

## 验证与提交

使用 `.venv/Scripts/python.exe`。
最终新文件连续三次运行：每次 **6 passed / 1 skipped / 0 failed / 0 errors**，
pytest 用时 **11.66 / 11.20 / 11.18s**。
日志/XML：`.codex-runs/b6-offline-replay/replay-final-1|2|3.log|xml`。
新增跳过仅 opt-in 付费模型 lane。

全量命令：

```text
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --junitxml=.codex-runs/b6-offline-replay/full-suite.xml
```

全量实际结果：**1763 passed、132 skipped、9 failed、4 errors、4 subtests passed，
586.09s**。XML suite 用时 585.880s；1912 个 XML testcase 含 4 个 subtest，
不将这四项重复累加到 pytest passed 数。
131 个既有跳过不变，仅新增本次 opt-in 付费 lane 的一个跳过。

全部 13 个失败/错误都是用户指定 14 项例外集合的子集：

- `test_browser_runtime_recovery.py`：4 failed。
- `test_mcp_app.py`：1 failed（`test_fastapi_lifecycle_health_effective_tools_and_snapshot`）；
  原基线失败的 `test_sync_session_execution_does_not_block_fastapi_event_loop` 本次通过。
- `test_mcp_runtime.py`：4 failed。
- `test_auto_apply_review_fixes.py::ChromeChecks`：4 setup errors。

其中 12 项 JUnit 堆栈直接包含 Windows named-pipe `CreateFile` 的
`PermissionError: [WinError 5]`。local stdio end-to-end 的表面断言是工具 denied，
因为 MCP manager 吞掉 optional server 启动异常，工具没有注册；同一配置的独立
StdioMcpClient 启动诊断确认其异常链同样为 `windows_utils.py / CreateFile / WinError 5`。
没有修改这些测试或生产 MCP/浏览器代码。其余测试通过；按用户本轮指定标准，
**离线测试验收通过**，全量不能表述为无例外全绿。reviewer 仍须在沙箱外复跑。

完整本地记录：`.codex-runs/b6-offline-replay/full-suite.log|xml`、
`verification.json`、`mcp-named-pipe-diagnostic.json`。

Windows Python 3.13 的新建 0700 临时目录同样受沙箱 ACL 限制。验证沿用上次中断的
局部 bootstrap：只将本次验证根目录内新建目录的 mode 改为 0777，以继承 ACL。
它不修改任何现有目录或 tmp 证据 ACL，不作为测试/生产代码提交。
`PYTEST_DEBUG_TEMPROOT`、TEMP、TMP 和 PYTHONPATH 只在验证进程中设置；
所有 `JOB_AGENT_LIVE_*` 和本次付费 lane 的 opt-in 在验证进程中移除。

测试/fixture 提交：`e2c613808bc5a0bb0ac4060c800f5afad7ddc80d`，
`test(search): add deterministic B6 offline production-loop replay`。
报告与矩阵作为后续独立文档提交，最终两项 hash 记录在本地恢复报告及交付汇报中。
这些提交位于下面的提交包分支。主仓库当前分支
`codex/remaining-e2e-fixes-20261011` 的 HEAD 仍为 `28c39d4`。
本次运行的权限配置将主仓库 `.git` 设为只读，实际 `git add` 返回
`Unable to create .git/index.lock: Permission denied`；不能写索引、对象或分支引用。
没有修改 ACL 或尝试越过权限配置。在可写的
`.codex-runs/b6-offline-replay/submission.git` 中生成基于同一 HEAD 的同名分支提交，
导出增量 `.codex-runs/b6-offline-replay/submission.bundle`，供可写会话获取和 fast-forward。
bundle 以 `28c39d4d683f08d49ef7a039d8530897dbef4ef5` 为 prerequisite；包含测试/fixture
与报告/矩阵两个提交，范围仅本次四个文件。主仓库的 bundle verify 可只读执行。
**提交包不等于主仓库当前分支已更新**。仅精确 git add 本次文件，不 push、不开 PR。
未触碰 `.env` 或用户已有的未跟踪 LIVE benchmark / optimization-plan 文件。

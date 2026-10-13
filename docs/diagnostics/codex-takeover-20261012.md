# Codex 接手核查（2026-10-12）

用户已要求 Codex 接手实现，结束对 Claude 的定时监督。监督自动化 `claude-jobhunteragent` 已删除。本记录以 Claude 交付提交 `db9fb51` 为基线；已有未提交 README、configuration 和 optimization-plan-v3 修改保持原样。

## 已核对的结果

- 统一 loop 迁移离线验收沿用原证据，不重复实施。
- 原始 `execution-roadmap-final-20261012/full-suite-0e2279f.xml`：2420 个 XML 测试项，135 skipped，0 failures/errors；对应报告 2269 passed + 16 subtests。该全量只属于 `0e2279f`。
- 原始 `affected-84ab70f.xml` 和日志：62 passed，0 failures/errors/skips。检查 `c31e0fe` 后，详情仅取 job_posting，相关错误不再算完整 JD；检查 `84ab70f` 后，配置组合确实走配置文件、loader、runtime 和 manager 的假客户端测试。之前两项反馈已修复，真实服务/账号尚未验收。
- R6 两次真实 API-first B6 均失败，合格推荐为 0。第二次正常结束不等于业务成功。Treg 已用完既定 20 次请求额度；低美元消耗不代表仍可追加请求。
- R7 MCP 尚未接入生产来源选择，T1/T2 未跑，保持可选关闭。R8 最终来源策略及 R9 业务交付未通过。
- 材料 full 仅完成一次真实生成，人工风格审核待办，patch 保持关闭。实际用户库迁移/部署不在本次接手授权内。

## 接手后的第一项修复

发现 `details()` 的 URL 正则只查子串：错误域名、搜索页查询参数或 fragment 中包含 `/jobs/view/<id>/` 也能通过岗位身份校验。改为解析 URL，要求 HTTPS、LinkedIn 官方主域或 www、无嵌入凭据、标准 HTTPS 端口和精确岗位路径；保留合法跟踪查询参数。补充错误域名/参数/fragment/协议/凭据/端口/子路径/畸形 URL 反例，以及合法 URL 对照。此适配器仍未启用。

## 后续执行顺序

1. 从 R6 run-2 的现有 transcript 离线归因重复 read_context：区分合法分页与重复读取，先建立可复现证据，再修改进度管理；不以少返回必要 JD 来降低 token。
2. 检查已记录 scrape verdict 与 Treg 原始返回契约。历史两次抓取未保存 verdict，不能凭猜测断言拒绝原因；新真实请求需要明确追加次数和费用上限。
3. 在获得追加额度后先做小范围抓取归因，再运行 API-first B6；保持原 seniority/location/JD/评分/持久化/两条推荐门槛。
4. LinkedIn MCP 的账号选择、用户自行登录及 T1/T2 单独推进。没有真实验证前不替换浏览器、也不作为必需依赖。
5. 来源配置通过 B6 后再冻结 R8、完成 R9；材料人工审核与真实库部署分别记录，不冒充整体完成。

当前接手修复的离线回归结果另附原始 XML；未发起新付费请求。

## 本次验证结果

- db9fb51 基线加本次未提交 URL 修复：LinkedIn T0 + R8 配置回归 **34 passed，0 failures/errors，12.34s**。原始 XML：../benchmarks/codex-takeover-20261012/focused.xml。
- 最初包含 test_mcp_app 的组合运行在输出 34 个通过标记后未继续输出，已中断该次测试，不能当作通过；原因未归定。随后上述两项直接受影响套件单独完整通过。原有 MCP app 证据仍属于 Claude 的 84ab70f，未声称新版本全量通过。
- 未运行任何真实模型/Treg/LinkedIn 账号请求。

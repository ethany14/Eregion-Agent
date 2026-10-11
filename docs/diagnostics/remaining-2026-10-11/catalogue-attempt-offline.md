# A1 目录身份、显式匹配输入与实际 attempt 汇总

**原 #1 仍失败，默认接入路线 pending。** 用户尚未选择首次缺少 Jev 目录时的策略。本轮未改变默认行为，未启用隐藏 Jev 请求，也未进行付费测试、B6/backend/A5 重跑、真实投递或推送。原 A1 四冷 spread≤8、典型≤30 要求、32次6并发0timeout及A2/A4质量门槛不变；这些真实评分指标仍未测。

## 复现、根因、修复与最终证据

| 项目 | 复现输入/根因 | 修复/回归与证据边界 |
|---|---|---|
| 完整目录身份 | 同REQ/source/atomic/typed，只把canonical python→rust；旧FIELDS遗漏canonical/display/original，哈希及agreement不变 | 冻结完整`JobAnalysis.model_dump`：包括全部JobRequirement字段、title/summary/responsibilities、原正文SHA和版本。provenance另存，不决定语义身份。逐字段变化、重复ID、旧不完整格式、篡改audit对象拒绝；合法重放一致 |
| 可信来源与显式主服务绑定 | 手工MATCH step不等于服务/default绑定；正文其他位置的相同词也不能证明源span | 内部`FrozenRequirementCatalog.from_jev_result`验证Jev算法、完整正文SHA、全部ledger span范围/唯一ID、需求与assessment ID/level一致，以及生产明确的前缀清理后的exact span。单岗async/sync、batch显式输入直接匹配，不再抽取目录；四个独立冷服务保持完整payload/ID/typed/source。不是默认接入通过 |
| 缓存隔离 | 同正文但目录/producer版本不同不能复用旧match | 完整目录hash+producer signature进入进程缓存及持久match签名；真实SQLite新服务重放0新attempt，改变producer重新匹配。校验返回独立副本，结果突变不改变冻结输入；正文/版本/ID/typed变化在调用前拒绝 |
| 单次retry计数 | 1 resume+1 job+matching首次timeout/重试=4，旧`_compute`报3 | 捕获每个provider boundary及失败/重试；嵌套adapter不双计。带tokens的实际合成provider记录和无tokens的adapter回退分别覆盖；终态异常附attempt/usage，不吞失败 |
| 真正多抽取batch | SharedModelAnalyzer→extract_job，25条bullet完整保留；resume1+ReferencedJobExtraction4+CompactSkillAssessment2=7，旧报4 | ContextVars跨抽取/匹配线程，分别捕获7次structured transport。真实provider边界夹具为7个provider事件；未计量stub为7个显式adapter事件，unknown_usage_calls=7，不能说零token/零成本 |
| 混合路由/warm | 原逻辑用三个阶段和routing摘要猜调用数 | fast HTTP边界明确`model_route=fast`；主/fast分别按attempt汇总。命中快决策缓存/简历缓存不增加调用；完整warm空attempt、当前calls0，不把旧成本复制进新请求。ledger写失败不会重试请求或丢内存观测 |
| batch目录被忽略 | uses_jev分支直接把jobs交给调度器；main混合valid/invalid也可先执行valid | 7项调度spy反例before全部失败。现在先验证整个batch，再启动任何worker/调度；Jev拒绝任何显式固定目录，主路由拒绝非法类型/过期版本/正文不符。after7通过，相邻47通过+4subtests，0真实API |

`provider_attempts`中`source=provider`表示实际计量边界，`source=adapter`仅表示没有子provider观测时的一次adapter/structured transport调用。后者不伪造持久provider账本；缺失input/output字段仍未知。汇总来自attempt事件，逻辑阶段不再被称作provider调用。原SDK内部HTTP自动重试在该边界下不可独立观察，冷runner继续强制SDK重试0，不将其当精确wire次数。所有本轮token数字均为离线合成夹具，不是付费成本。

## 保留的失败与最终结果

- `tmp/catalog-attempt-before-20261011.log`：误用系统Python，缺pytest，无测试运行。
- `tmp/catalog-attempt-before-v2-20261011.xml`：10失败/9通过，目录字段/provenance及retry少报实证。
- `tmp/catalog-attempt-local-v3-20261011.xml`：3失败/37通过；raw span与合法Required前缀清理不相等。修为生产明确转换的精确绑定，未接受任意子串。
- `tmp/catalog-attempt-local-v4-20261011.xml`：1失败/39通过；需求之外的坏ledger span未拒绝。已验证全部ledger span及唯一身份。
- `tmp/catalog-attempt-integrated-v1-20261011.xml`：133通过/4跳过，不能算137通过。
- `tmp/catalog-attempt-integrated-v2-20261011.log`：误写不存在的`tests/test_model.py`，收集失败，无测试运行。
- `tmp/catalog-attempt-integrated-v3-20261011.xml`：139通过/4跳过，21.60s。4项Chrome opt-in跳过，不算浏览器通过。
- `tmp/catalog-batch-before-20261011.xml`：7失败；after7通过。`tmp/catalog-batch-adjacent-final-20261011.xml`：47通过、另4subtests通过，5.41s。

原`tmp/remaining-fixed-catalogue-offline.xml`三项中，默认目录gap测试刻意断言Jev1/main2。当前仍保留该测试为OPEN证据。显式主服务目录输入、四冷目录一致及缓存隔离证明共同机制成立，**不能替代原用户默认路径绑定，也不是真实分数稳定性或评分准确率通过**。

## C11 后续离线实际缺陷

两个真实保存application_id指向同一posting，经生产`CareerHarness.execute(start_application)`只有一个持久run，旧batch相对开始前固定集合计算，第二条复用同run仍标started。`tmp/plural-identity-before-20261011.xml`1失败，实际2≠1保留。现逐条更新已遇run集合；starts及opened/reused统计唯一run，成功请求行另用`resolved_request_count`，不把2请求说成2申请。`tmp/plural-identity-after-20261011.xml`29通过，含重放0新starts、原状态/部分失败守卫。使用真实SQLite及合成浏览器，不当作真实模型多申请流程通过。

所有原XML/log不覆盖。精简汇总、SHA-256和原主分析/partial失败索引见`catalogue-attempt-offline-r1.json`，复跑导出器`scripts/export_catalog_attempt_evidence.py`使用独占创建，不静默覆盖旧revision。完整1–18/E/F状态见根矩阵。

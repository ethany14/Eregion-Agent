# E5 风格筛查与生产建议一致性 · 离线增量

**E5 仍失败**。没有新生成的真实求职信，没有人工审美通过，没有收费测试。冻结真实修订稿仍事实通过、开头生硬、两次 would welcome。此前事实/费用/失败均保留。

复现输入是在已有冻结稿的修订上下文中，将重复 invitation 改为 `would welcome the chance`，另加多空格/换行/大小写的合成变体。生产 `cover_revision_notes` 已报告重复及段落位置；评测 `screens.no_repeated_invitation` 却通过。根因是两套 regex 的词形/空白规则不一致，不是新真实模型误答。

修复共享有限 `cover_invitation_occurrences` matcher，供生产建议与离线筛查调用。单个未来 invitation 与有据过去经历仍允许；原事实 repair target 继续进入生产 revision context，grounding verifier 不变。没有宣称能识别所有同义重复，也没有拿启发式筛查代替人工审阅。

| 产物 | 结果 |
|---|---|
| `tmp/e5-screen-before-20261011.xml` | 4失败/1通过；3纯变体 +1实际生产修订上下文不一致；合法单次未来表达通过 |
| `tmp/e5-screen-after-20261011.xml` | 47通过/2收费 opt-in 跳过；含31项 application-pack 相邻回归，原不支持句仍被拒绝 |

原文、原 verification 不改写；当前筛查仍判真实冻结稿重复 invitation/非第一人称开头失败。[精简结果与 SHA](cover-style-screen-offline-r1.json) 包含 before/after、冻结稿 hash、原用量与实现 hash。下一步仍需有新增修复依据的新成稿及人工风格审阅，本轮不自动收费复验。

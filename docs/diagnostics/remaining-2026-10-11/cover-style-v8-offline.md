# E5 冻结真实修订稿的离线增量

E5 仍 **失败/待人工风格审阅**。本次没有再次调用 writer、reviser 或 verifier API。原 writer 通过、原失败 seed 判定不一致和原 reviser 实测失败均保留，不改最终事实验证门槛。

输入为 `cover-original-revision-evidence.json` 的实际修订成稿，冻结在 `tests/fixtures/remaining_cover_style_revision.json`，含来源 SHA256、原事实验证及原账本：2calls/2643input/4830output、usage_complete=true。原有“supports efforts to improve reliability”无据过去效果已删除；事实验证通过与风格未通过分开记录。第1段含“Python Engineer … focuses …”和一次“would welcome the opportunity”，第3段再次重复该邀请。

根因不只是重复词：原提示同时要求“以岗位/公司需求开头”和“第一人称申请开头”，有视角冲突；revision 只有事实 repair targets，没有将这份稿的重复意图具体定位给编辑。原 v7 的一般去重复说明不能证明生成效果已改善。

本次 v8 修复：

- 开头明确一个自然第一人称申请句，岗位/公司只能取已核实信息；公司需求可另成句。过去事实、未来任务各自成段，证据稀少时保持简短，不重复换词表达邀请。
- production `_revision_context` 在不变的事实反馈之前加入 **advisory** 风格建议：实际首句、paragraph-1/paragraph-3 两个邀请位置和合并目的；不能通过换同义词继续重复。
- 建议不改原文、不改 verification/status、不自动加付费重试，不属于事实验证或审美判定。未来与过去涉及同一技术仍合法；原无据效果仍由未修改的 verifier 拒绝。
- prompt 版本递增 `application-pack-v8`，新生成快照与旧版本可区分，原冻结文本/失败不静默替换。

`tmp/remaining-cover-v8-offline.xml`：60项，**58通过/2跳过/40.38秒**。两 skip 是需显式 opt-in 的真实生成/修订；没有把它们算通过。包含冻结真实稿的缺口定位、生产修订上下文、原 unsupported clause 拒绝、保留证据/原失败及 application_pack 相邻回归。

这些仅证明策略和数据传递正确，**不证明新模型稿已自然、不证明人工审美通过**。未再次生成成稿。证据与所有原失败分类见 [精简离线证据](phase4-offline-and-cover-v8-evidence.json)。完整 A–F 状态、人工待审、A5 用户暂缓和 C16 原延迟门槛均不变。

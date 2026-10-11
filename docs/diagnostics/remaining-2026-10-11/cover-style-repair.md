# E5 求职信失败、修复与复验

状态：失败，等待本次针对性真实复验及人工风格审阅。完整 A–F 以根目录验收矩阵为准；不重复 backend 或暂缓的 A5 性能实测。

## 复现输入与原失败

合成申请人唯一候选事实为 `Built Python APIs.`；岗位为 Synthetic Harbor Systems / Python Engineer，雇主希望改善 API reliability 并测试 error responses。真实模型生成和修订后，第二段仍为：

> Prior work has included building Python APIs, which corresponds to the stated requirement for Python API development and supports efforts to improve reliability.

引用只支持 API 开发，不能支持改善可靠性的效果。真实 grounding 拒绝此完整句。修订仅换开头，问题句不变；三段重复 API 经验，开头及贡献段生硬。原失败不是风格通过。

原正文、两版本、精确 evidence/version/requirement ID、验证结果和完整账本：`cover-style-first-failure.json`。原始 JSON/MD/数据库/XML/log 保留于 `tmp/remaining-live-cover-style/`。3 calls，3290 input，8508 output，usage_complete=true。

## 根因与修复

旧 writer 要求解释经验与雇主需求的关联，但没有清楚区分已证明的过往事实和未来贡献意图。旧 reviser 接到失败反馈后仍可能只改开头，原 unsupported clause 原样保留。

`application-pack-v5` 明确：过往行动/效果只能来自候选证据；雇主目标不能证明过去成果；独立未来句表达申请或贡献意图；自然第一人称；稀疏证据只写三个短段落，同一经验只说一次。修订政策要求处理每项具体问题句及原因，删除无依据因果/效果部分，并检查其他段落有无重复同一错误。

生产 `_revision_context` 保留原 artifact 和完整验证反馈，同时按问题列出 block_id、unsupported_text、reason、revision_instruction，以及仅从不可变 snapshot 解析出的候选原句/精确引文/引用 ID。此投影不产生新证据，也不改变 verifier 或通过门槛。

## 离线回归

`tests/fixtures/remaining_cover_style_failure.json` 保存真实失败。`tests/test_remaining_cover_style.py` 检查实际 writer/reviser 有效政策，并从模型草稿入库→原验证器→needs_revision→continue_item 进入实际修订路径；保留原问题句仍拒绝，去掉无据效果且保留精确引用的确定性夹具可通过。后者只证明修订路由和验证契约，不是实际生成或风格效果。

首轮 `tmp/remaining-cover-failure-policy.xml`：34通过/2失败/1未选。两失败因新建 generating item 被夹具当作 user_edit，生产仓库正常拒绝，未触达 reviser。原失败保留。改为 origin=model 持久化，并通过原验证器与仓库 verify 建立 needs_revision；不改数据库状态、不放宽 user_edit。`tmp/remaining-cover-failure-policy-v2.xml`：5通过/1未选/5.58s。

## 本次真实复验约束

离线集成全绿后仅启动一次场景：一份新 writer 草稿（max_revisions=0，不自动付费重写）和一份原失败草稿的真实 reviser 修订（上限一次）。两条链均经未改的生产 grounding 验证，保存全文、所有版本、有效修订上下文、岗位/简历引用、各 purpose 账本与检查结果。失败不自动重复整轮；人工可审自然性、意图/事实分离及去重复，不能由关键词检查替代。

## 已取得的真实终态与限制

policy-v5整轮1fail：writer自动awaiting_review，但原失败seed再问语义验证竟通过，未执行reviser。3calls/2360in/7334out完整保留，实际两项passed verification持久结果见 cover-style-policy-v5-failure.json；未保存的原始语义理由不补造。独立审阅发现Experience只是栏目fallback，不得写成职位。

之后只补尚未执行的reviser：重放原冻结FAIL verification，仅重绑同一精确本地证据ID，明确replay provenance；不是手工PASS。真实修订和未改的最终grounder通过、2calls/2643in/4830out完整；旧无据reliability效果和Experience职位混淆已删。整项测试仍fail，旧重复API正则误把过去事实和未来贡献同时计重复；离线检查已区分时态，但实际稿仍重复“would welcome the opportunity”，且开头“Python Engineer ... focuses”生硬。全文/两版本/最终验证/费用见 cover-original-revision-evidence.json 和同名md。

v7新增自然第一人称开头、意图表达只一次、过去与未来任务匹配分开；writer证据投影不把通用section名当职位。原verifier及最终真实验证门槛均不变。没有重复已绿writer或继续盲目付费；v7尚无新的真实风格通过证据，E5继续失败。

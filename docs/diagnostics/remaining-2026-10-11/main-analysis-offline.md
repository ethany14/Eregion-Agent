# A1 / A4 主分析离线修复与验收入口

**整体未通过。** 本轮没有付费模型、B6/backend 重跑、A5 性能重测或真实投递。A1 四冷 spread≤8、典型 JD≤30 要求、32 次实际 6 并发/0 timeout 尚无真实模型证据；A2/A4 准确率、AUC 与冻结 baseline 仍待人工 gold，partial 权重保持 0.5。

## 复现、根因与修复

| 路径 | 复现输入及根因 | 修复与针对性证据 |
|---|---|---|
| 背景清洗 | 仅 `We are an equal opportunity employer.`；全部被判背景后 `ids=[noncontext] or all` 又把背景交给 provider | 去掉回退；空白、标题、heading、全背景零 provider。主抽取直接复用生产 `job_units`，原句 verbatim、24 structured/flat 正文 offset 一致；保留资格/授权/relocation，不按 30 截断 |
| expand 去重 | 相同 atomic_text=`Python experience`，2 年/5 年，原键只有 text+level | 同源格式去重必须同时同 category、mode、minimum_years、level；不同硬条件保留。否定、C/C++、数字和不同源不按近似文本盲合并 |
| 下游 normalization | 上述两条经 expand 后仍被 `canonical_name` 合并，只剩 2 年；另两个 Python predicate 被合并 | 改为完整 atomic predicate+typed constraints。来源解析与已供 duration 矛盾时明确拒绝，不静默改弱；碰撞 ID 补类型稳定身份。简单同 predicate 的 required/preferred 重复仍保留较强 required |
| 抽取批次重试 | 监督三批 timeout 实测 attempts1/2/1，本来正常；包装 RuntimeError→TimeoutError 另一路径不识别 | 仅失败 batch 一次 transport retry，追溯异常 cause；成功批次不重跑，持续 timeout 两次后抛错。保留 attempt 归因，不重试 schema 错误 |
| matching 批次重试 | 首轮夹具缺 original/source 导致 ValidationError，不能算产品 failure；补正后 r24 批首次 TimeoutError 直接失败 | 已保存补正 before；共用有界 retry，每条原要求/ID 都保留，无整轮重试 |
| assessment 身份串用 | 两 distinct REQ 共用 canonical Python，只供 API 的 matched，部署或 5 年要求也借用同证据 | 有 ID 只按该 ID；未知 ID 不做 name fallback；重复 ID 明确拒绝。无 ID 内部 legacy 仅唯一目标+唯一记录时兼容；公共 schema 仍要求 ID。生产 handler 及 chunked 入口分别覆盖 |
| partial 无关引文 | `Financial forecasting` + 原文引文 `Built Python APIs.`，结构合法却得 partial/50 | 主流程与可选 resolver 加必要内容词/有限显式 alias overlap；泛词不算支持。无重合改 missing，保留原引文和解释；伪造引用仍 unknown。支持 C/R、C++/C# 区分及 k8s/SQL 等列明 alias；不是语义正确性或 AUC 证明 |
| 1500 请求压力 | 相邻旧测试研究页 links 消失，未受本轮 extraction 直接修改影响 | 既有压缩把没有 browser 观测的最新 HTTP 页也归档。保留最新来源页的行动链接，受保护原文可能超小预算仍如实记 overflow；原请求/拒绝增长 48k 回归继续通过 |

主抽取、main routing、FitAnalysisService 和 Jev resolver/settings 的签名覆盖修改后的实现/partial helper，旧结果不会静默混入新评分验收。

## 原失败与最终证据

所有路径均相对仓库根目录，原文件保留未覆盖。

- `tmp/remaining-main-analysis-before.xml`：15 tests /13 fail /2 pass /2.325s，其中 matching 一项为无效夹具，非产品行为证据。
- `tmp/remaining-main-matching-before-v2.xml`：1 fail，有效 fixture 到达实际 TimeoutError，无重试。
- `tmp/remaining-main-analysis-after.xml`：15 pass；后续补终态、24 原文及 normalization，总共 18 项纳入最终集。
- `tmp/remaining-main-analysis-adjacent-first.xml`：153 tests /114 pass /2 fail /33 setup errors /4 skip；33 为系统 Temp 权限，非产品缺陷也非通过。
- `tmp/remaining-main-analysis-adjacent-v2.log`：换工作区 basetemp 后仍被 Windows sandbox 拒绝，含 teardown 权限错误；不推算测试通过数量。
- `tmp/remaining-main-analysis-adjacent-v3.xml`：163 pass /4 skip /33.226s。采用新唯一工作区 basetemp，本地离线权限提升；句子引用明确保留 Python required、SQL preferred 和 Build APIs 责任的原文，而非删除断言。
- `tmp/remaining-main-normalization-before.xml`：1 fail，实际下游再次丢 5 年要求。
- `tmp/remaining-partial-overlap-before.xml`：4 fail /5 pass；无关内容及泛词错误 partial，含八岗扇出/持久缓存。
- `tmp/remaining-match-identity-before.xml`：6 fail，覆盖两 predicate、两年限、未知/缺失/重复 ID 和 legacy 歧义。
- `tmp/remaining-main-partial-integrated-first.xml`：129 pass，另 4 subtests pass /15.62s；离线。
- `tmp/remaining-main-partial-final.xml`：246 pass /4 skip /39.59s，另 4 subtests pass。覆盖 extraction、production normalization/matching、resolver、持久缓存、评测、请求压缩与相邻回归；四项为 Chrome opt-in，不能算浏览器通过。
- `tmp/remaining-main-offline-final-v2.xml`：51 pass /6.87s；追加最终 runner 历史离线重核、用量保留、生产 matching 入口与 C/R 边界；不替代真实主模型稳定性。

## 新验收入口

见 [main_stability_README.md](../../../tools/evals/main_stability_README.md)。默认 offline plan；显式 `--live` 才收费。本轮仅离线测试：同一冻结输入/实现、真正无结果缓存的生产服务、6 worker、32 次完整失败收集、每个 provider attempt 的 task 账本、未知用量拦截和历史重核。SQLite 集成使用真实 FitAnalysisService + 合成 provider：四次独立服务，每次 4 次调用含 1 个 timeout/1 个 retry，已知 40 input/20 output；这是测试计数，不是真实 API 成本。

原 A–F 范围保留：B6 analyst52 calls/0 推荐仍失败，不收费重跑；backend 已过不重跑；C16 主模型延迟仍失败；A3 的 72 组/96 项人工复核 pending；E5 实际成稿风格仍失败；A5 89.015s 超 60s 的失败保留并按用户要求暂缓；推送/PR 等待批准。

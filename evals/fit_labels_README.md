# Fit labels v1：独立人工要求与匹配评审

当前 **12 真实公开 JD × 6 合成申请人 = 72 组**。这是待审数据和评估管线，不是已获人工确认的 gold，也不代表评分准确率通过。禁止用模型生成标签、自己的预测或材料排版质量评审冒充这套人工标签。

## 数据与来源

`fit_labels_v1.json` 包含六份完整合成简历、12 份 structured/flat 岗位正文、来源标题/公司/地点、时间、原响应/两种正文 SHA-256、72 组独立待审记录。

四领域各三份：软件工程（CaseGuard、Pipe、Coursera），业务分析（Capco、Blockchain.com、Backbase），设计（In The Pocket、Livefront、Co-Star），数据科学/ML（Closure Technologies、Awin、Lynx Analytics）。国际/高级/安全许可要求保持原样，不把这些职位冒充 NY 初级合格结果。

来源为雇主公开 Greenhouse 单岗位记录的 content 字段；不抓整张申请表，也不使用旧污染的 python.org/8113 或标题不明确的 Tuniform。原污染版本、clean-r1 以及 malformed 数据库读取失败仍在 `docs/diagnostics/remaining-2026-10-11/a3/` 的历史记录中，未覆盖。首轮 Backblaze HTTPStatusError 保留在 `fit_labels_v1.sources-first.json` 和主数据 read_errors；那轮只有11岗/66组，未当空样本或通过。r2 增量补 Coursera，已取得的11源未重复抓取。

`docs/benchmarks/fit-labels-v1-review-units.json` 是可选的逐段审核辅助，含每段原文和 offset、空的 candidate/level/notes。**units 不等于 requirements**，该辅助文件不是 gold；同一资格跨段或同段多项需要人工划定，不应按单位数量推断评分或要求数量。

## 具体待人工复核

共有96个待审环节：

1. **12 份来源**：逐一核对链接实际标题/公司/地点、目标 vacancy 正文范围；排除侧栏、其他公司岗位、申请表。按 `source.human_review.checklist` 复核；ATS 单记录身份检查不替代人工确认。
2. **12 份要求目录**：在 `requirements_review.requirements` 中人工写每项 `requirement_id`、`atomic_text`、`level`（required/preferred）、原 structured 的 `source_start/source_end/quote`。quote 必须逐字符对应正文。必要时填写人工认可的 `accepted_prediction_texts`；不能根据评估预测自动加入别名。`excluded_context` 记录福利/公司介绍/EEO/No Agencies 等排除理由。
3. **72 组匹配**：为目录每项填写 `requirement_statuses` 的 ID、status、rationale，以及 matched/partial 对应的精确 `resume_quotes`。保留不确定性，不用邻近泛技能补出缺失技能。分别给 `labelled_score`（0–100）及 `fit_label`（fit/mismatch），不能从系统自身分数拷贝。

三种 review 都要显式改为 `status: confirmed`，并记录 `reviewer: {kind: human, name: ..., confirmed_at: ISO时间}`。未确认的一律保持 pending/null。不要只把状态翻为 confirmed；缺要求、缺匹配项、错引文或缺评分会严格失败。

格式示意（仅示意，不是任一实际岗位的已审标签）：

```json
{
  "requirement_id": "human-r1",
  "atomic_text": "人工确认的原子资格",
  "level": "required",
  "source_start": 0,
  "source_end": 12,
  "quote": "必须精确对应原文",
  "accepted_prediction_texts": []
}
```

```json
{
  "requirement_id": "human-r1",
  "status": "partial",
  "resume_quotes": ["必须逐字来自该申请人的简历"],
  "rationale": "说明同技能的具体年限/范围缺口"
}
```

## 执行与版本隔离

离线默认不调用模型、不联网、不读取当前 `.env`。缺预测文件也会产出诚实的 pending 报告并以 exit code 2 结束：

```powershell
.venv/Scripts/python.exe -m evals.run_fit_labels
```

结果为 `docs/benchmarks/fit-labels-v1-report.{json,md}`：原72组全覆盖才可计算完整 precision/recall/status accuracy/score MAE/AUC；没有 gold 或预测则指标为 null。未匹配/遗漏要求计入 recall 和 status accuracy 的分母；重复预测不得重复匹配同一 gold。区间分不伪造点分，MAE/AUC 无完整点分时明确不可计算。分数尺度/partial 权重未修改。

每次付费 run 先冻结 manifest：dataset revision、全部正文/简历哈希、每 algorithm 的 production cache_signature（绑定实际 prompt/schema/model/configuration）、run_id 和整体摘要。每行必须绑定同一 manifest 和该算法签名。缺签名、混 run、过期正文或配置均拒绝。合法历史 run 可以在相同历史数据上离线评估，报告明确显示历史版本，不暗称当前运行时通过。

离线若要核对某个明确的版本，可提供 `--expected-manifest frozen-run.json`，不必读 `.env`。live 发现配置变更时必须新建 `--cached` 和 `--output` 路径；不静默覆盖或重用旧缓存，既有失败也不自动重新付费。

**目前不启动288行付费矩阵。** 后续独立授权的 live 命令形式如下；本次只测试了 offline provider 替身的调度/归因/失败 checkpoint，不声称实际模型评估完成：

```powershell
.venv/Scripts/python.exe -m evals.run_fit_labels --live --limit 1 --cached docs/benchmarks/fit-labels-v1-run-NEW.json --output docs/benchmarks/fit-labels-v1-run-NEW-report.json
```

原门槛保留：flat/structured 分差≤10且≥90%组满足、要求数量比0.8–1.25、AUC≥0.9、mismatch中位数≤15、fit均分降幅≤5、A1四次cold spread≤8/典型JD≤30要求/6并发32次零timeout。未做并发/重复cold及缺冻结对照时报告保留未测，不能单凭此脚本退出码宣称A1/A2/A4全通过。A5八岗≤60秒仍失败且用户要求暂缓。

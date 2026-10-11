# A1 主模型冷启动稳定性验收

入口为 `python -m evals.run_main_stability`。它独立于旧的顺序 workflow 评测，不替代 A2/A4 的人工准确率验收。**目前只完成离线机制测试，真实 A1 未通过；本轮不得启动付费矩阵。**

默认仅生成计划，完全不读 `.env`、不实例化模型、不联网；exit code 2 表示未验收：

```powershell
.venv/Scripts/python.exe -m evals.run_main_stability --output docs/benchmarks/main-stability-plan-NEW
```

计划固定 r2 的 6 个合成申请人、12 个干净公开 JD 的 structured 输入。`cold4` 为每个人岗组合 4 次等价评分，共 288 次分析；`stress32` 从同一集合等距选择 32 次分析，6 个真实执行 worker。`all` 共 320 次分析，**不是 320 次 provider 调用**：抽取/匹配批次和有界重试会产生额外调用。人工 96 项复核仍 pending，不允许将这些输入当已审 gold。

每次分析创建新的生产 `FitAnalysisService` / handler，`cache_size=0`、持久分析缓存为 None、`jev_enabled=False`、显式无凭据 `FastDecisions()` 禁用 Jev。共享 HTTP client 不等于共享结果缓存；live 还拒绝全局 LLM response cache。不能用修改输入、换 ID、缓存命中时间冒充 cold。

manifest 在任何调用前冻结 dataset revision、完整数据/正文/简历 hash、实现文件 hash、生产 cache_signature、实际 extraction 模型 ID、reasoning、timeout、SDK 重试配置及原阈值。所有行绑定同一 manifest、输入和评分签名；输入/版本/覆盖变更、缓存命中、缺失行、重复行、无账本均不能通过。

后续另行授权时的显式付费入口（本轮**未执行**）：

```powershell
$env:TYPESAFE_ENABLED='false'
$env:LLM_TIMEOUT='180'
$env:LLM_MAX_RETRIES='0'
.venv/Scripts/python.exe -m evals.run_main_stability --live --suite all --output docs/benchmarks/main-stability-LIVE-NEW
```

分析量大时配置 `LLM_TIMEOUT>=180`；项目通用默认值仍为 45 秒，脚本不静默修改 `.env` 或配置。SDK 重试为 0，生产抽取/匹配仅对失败批次的 timeout/连接类错误重试一次，保留每次 provider 调用及 attempt。成功批次不重跑、schema/身份错误不重试，第二次失败仍抛出。32 次验收中出现恢复成功的 timeout 也计入 timeout，不以最终成功掩盖。

输出新建目录，已存在则拒绝：`manifest.json`、`frozen-inputs.json`、append-only `trials.jsonl`、`usage.sqlite3` 和逐条更新的 `report.json`。保留完整结果、要求数量、provider 失败/重试、已知或未知 token 用量及 task 归因。账本写入/读取失败不能声称零成本或完整；内存 provider 观测单列保留。中断后缺行是未完成，脚本没有自动恢复或重收费入口。

离线重核已有完整/失败 run，不读当前模型配置、不调用 API，也不续跑：

```powershell
.venv/Scripts/python.exe -m evals.run_main_stability --evaluate-run docs/benchmarks/main-stability-LIVE-OLD --output docs/benchmarks/main-stability-AUDIT-NEW
```

重核使用该 run 的冻结数据/签名、所有失败行和真实 start/end 时间，独立恢复并发峰值；注明历史版本，不能宣称当前配置已测。原标准保持：每组 4 次 spread≤8、典型 JD 实际要求数≤30（不截断）、32 次实际 6 并发/0 timeout。可只执行一个 suite，但只报告该 suite，另一个仍未测。A2/A4 precision/recall/MAE/AUC 仍 null，需人工 gold 与冻结 baseline；partial=0.5 不变。A5 性能仍失败且用户要求暂缓，本入口不执行 A5。

# EventShock Lab Risk Register

## 评分

- 可能性：Low、Medium、High。
- 影响：Medium、High、Critical。
- 状态：Controlled、Open、`PENDING_HUMAN_EVIDENCE`、`CONTROL_GAP`。
- P0 Release Blocker：在受控 Demo 前必须解决或获得可核验证据。

## 风险登记

| ID | 风险 | 预警信号 | 可能性 | 影响 | 现有控制 | 回退/响应 | Owner | 残余状态 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| R-001 | 市场内核错误 | 负现金、净头寸不守恒、重复成交、Event Hash 漂移 | Medium | Critical | Integer tick、FIFO、Ledger invariant、Property/Replay tests | 停止发布、Invalidate 受影响运行、修复并重放 | Market Lead | Controlled by code；外部审查待完成 |
| R-002 | Future leakage | Agent 引用 knownAt 之后的信息 | Medium | Critical | PIT Store、Timezone-aware Schema、SpaceX 公告边界测试 | 冻结 Pack、查找受影响运行、修正时间并重放 | Data Lead | 来源时间人工复核 `PENDING_HUMAN_EVIDENCE` |
| R-003 | Prompt injection | 上传内容要求更改角色、可信度、工具或配置 | High | Critical | 抽取前确定性扫描、Delimiter、无工具、候选 Claim 人审、Schema、Red-team Case | 隔离来源、关闭 Live LLM、Rule fallback | LLM Lead | 扫描不能覆盖所有语义变体；完整攻击执行 `NOT_EVALUATED` |
| R-004 | LLM 行为漂移 | 同模型 ID 输出、拒答或成本显著变化 | High | High | Prompt/Model Hash、Cache、Eval Harness、Rule fallback | 切旧 Cache 或 Rule-only，冻结新实验 | LLM Lead | 实时模型证据 `PENDING_HUMAN_EVIDENCE` |
| R-005 | 未知证据或伪造引用 | BeliefDecision 引用 Observation 不含的 ID | Medium | Critical | allowedEvidenceIds、本地引用检查、Grader | Reject、Repair 一次、ABSTAIN | LLM Lead | 语义错引仍需人工验证 |
| R-006 | Action overreach | LLM 输出订单、数量、账本修改或工具调用 | Low | Critical | Belief-only Schema、Deterministic Policy、无真实工具 | 禁用模型路线、阻断 Intent | Market/Platform | 未来增加工具会显著提高风险 |
| R-007 | Schema drift | Unknown Version 或额外字段进入系统 | Medium | High | Literal Version、extra=forbid、Rule fallback | Reject、Repair、ABSTAIN | LLM Lead | Provider 稳定 ID 仍可能漂移 |
| R-008 | Cross-session 访问 | Session A 读取 Session B 状态或 Key | Medium | Critical | Session-bound queries、内存 Key、掩码视图 | 停服、清 Key、审计、轮换 Session | Platform Lead | 匿名 Session 不是认证，`CONTROL_GAP` for sensitive use |
| R-009 | API Key 泄漏 | Key 出现在 Response、Log、DB、ZIP 或 Crash | Medium | Critical | Memory-only、TTL、repr=False、masked view、Log filtering | 清除、吊销、扫描影响面、通知 | Platform Lead | Host/Crash 审查 `PENDING_HUMAN_EVIDENCE` |
| R-010 | Cost exhaustion | Provider Calls、Token 或账单异常增加 | High | High | Max Attempts、One Repair、Max Tokens、Cache、Rate limit | 关闭 Live LLM、Provider Budget、Rule-only | LLM/Platform | 全局美元预算 `CONTROL_GAP` |
| R-011 | Source tier promotion | Social/Synthetic 内容成为 T1 FACT | Medium | Critical | Typed SourceTier、T4/T5 FACT Reject、Human Review | Quarantine Claim、修正来源、Invalidate | Data Lead | 元数据伪造仍需人工核实 |
| R-012 | 数据许可违规 | 原文或行情进入公开仓库/ZIP | Medium | Critical | Link-only、Synthetic Market、Third-party register | 移除公开访问、调查 Fork/Artifact、法律复核 | Data Lead | 许可审查 `PENDING_HUMAN_EVIDENCE` |
| R-013 | 结果被当作预测 | 用户说“AI 建议买入”或引用目标价 | High | Critical | Synthetic Badge、非建议文案、区间和 Limitations | 停止公开结果、重做 UX 和说明 | Product Lead | 用户理解 `PENDING_HUMAN_EVIDENCE` |
| R-014 | 单路径 Cherry-pick | Demo 只展示戏剧性 Seed | High | High | Matched Ensemble、Distribution、Seed registry、Representative rule、模型内部 Study 预注册 | 展示全分布、标记探索性 | Data/Product | 无独立时间戳的历史研究预注册与外部复算 |
| R-015 | 多重比较与 p-hacking | 指标不断扩展直到出现方向 | Medium | High | 固定 METRIC_KEYS、Single Intervention、2–4 个 Study 主指标、family-level Holm | Exploratory Label、Preregister、Reduce claims | Data Lead | 真实历史研究的独立预注册仍为 `PENDING_HUMAN_EVIDENCE` |
| R-016 | Calibration 过拟合 | 对单一 SpaceX 路径拟合过好 | Medium | High | Synthetic Label、No causal claim、Excluded observed calibration | 降级为 Mechanism Demo | Data Lead | 历史 Holdout `NOT_RUN` |
| R-017 | Persona 刻板印象 | “散户=不理性”等描述或参数映射 | Medium | High | Synthetic archetype、无 Protected Attribute、Editable assumptions | Relabel/rebuild population、Human review | Product/Data | Fairness review `PENDING_HUMAN_EVIDENCE` |
| R-018 | SQLite 并发与恢复 | Locked DB、Stuck jobs、Corrupt volume | Medium | High | WAL、Busy timeout、Write lock、完整 matched-pair checkpoint、发布前 SQLite online backup | Stop writes、Restore verified backup、resume verified checkpoint | Platform Lead | 异地备份、负载与恢复演练 `PENDING_HUMAN_EVIDENCE` |
| R-019 | 单实例故障 | Server、Container、Disk 或 Provider 下线 | High | High | Restart policy、Health/SHA check、不可变发布回滚、冻结认知 tape、Rule fallback | Roll back verified image、恢复数据、重新启动 retryable run | Platform Lead | No HA；离线演示包与 Ops rehearsal pending |
| R-020 | Export traversal | User ID 或 filename 逃逸 ZIP/Filesystem | Low | Critical | Fixed entry names、DB lookup、No user file path | Disable export、Audit artifact consumers | Platform Lead | Dynamic red-team execution `NOT_EVALUATED` |
| R-021 | 指标公式错误 | 独立复算不一致或单位异常 | Medium | Critical | Tests、Matched seeds、Versioned code、Run-level CSV | Invalidate reports、修复并重跑 | Data Lead | Independent expert review pending |
| R-022 | AI 代码无人理解 | 团队无法解释核心控制 | High | High | Docs、ADR、Tests、Component inventory | Freeze feature、Walkthrough、Rewrite | All | Non-author walkthrough `PENDING_HUMAN_EVIDENCE` |
| R-023 | 低内存 OOM | Container restart、Swap、Large ZIP、Queue backlog | Medium | High | 1 GB limit、Upload/Queue caps、Single worker、Log rotation | Lower seeds/nodes、Disable Live LLM、Precomputed result | Platform Lead | Capacity test `NOT_RUN` |
| R-024 | 批量失效能力缺失 | 同一版本错误影响的其他结果仍可下载 | Medium | Critical | 单实验 invalidation API/结果 gate、Audit events、Version metadata、Manual containment | Stop service/export、Build affected set manually、逐个 invalidation | Platform/Data | 按版本/模型/时间批量发现与操作仍为 `CONTROL_GAP` |
| R-025 | 第三方供应链漏洞 | CVE、Compromised package/image | Medium | Critical | Version lock、Image digest、Non-root container | Pin safe version、Rebuild、Rotate secrets | Platform Lead | SBOM/Scan `PENDING_HUMAN_EVIDENCE` |

## 当前 P0 阻断项

- R-003 完整 Prompt Injection 红队执行。
- R-008 强认证不在当前匿名 Demo 范围；敏感多租户使用禁止。
- R-009 主机、日志、Crash 与 Secret 人工审查。
- R-010 全局模型预算控制。
- R-012 许可审查。
- R-013 用户理解研究。
- R-018 备份恢复和 SQLite 负载演练。
- R-021 独立指标与领域审查。
- R-024 批量 invalidation 控制缺口。
- R-025 供应链扫描与审查。

Release Gate 在上述人类证据和自动化 artifact 缺失时必须返回 `BLOCKED`。

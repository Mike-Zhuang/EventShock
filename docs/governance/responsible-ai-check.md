# EventShock Lab Responsible AI Check

## 检查状态

- 日期：2026-07-16
- 范围：当前课程 MVP 与 SpaceX source-backed synthetic-market Demo
- 自动化/文档自查：已完成
- 真实用户、专家、安全和许可验证：`PENDING_HUMAN_EVIDENCE`
- 发布建议：`BLOCKED`

本检查由 AI 辅助编写并依据仓库代码核对。它不能自我授予人类批准。

## 1. 谁可能因产品工作正常而受损？

用户可能因界面可信、图表精细而过度相信 synthetic 结果；团队可能把机制演示宣传为预测；第三方内容所有者可能因不当再分发受损；被 Persona 标签隐含描述的现实群体可能受到刻板印象影响。

控制：Synthetic 标签、非建议文案、Fact/Estimate/Assumption 分层、Link-only 来源、Limitations 和 Human-in-the-loop。

证据状态：用户是否正确理解仍为 `PENDING_HUMAN_EVIDENCE`。

## 2. 谁可能因产品失败而受损？

依赖错误结果做研究或现实决策的用户、API Key 泄漏的用户、跨 Session 数据被读取的用户、被错误来源或时间污染的分析对象，以及维护故障系统的团队成员。

控制：PIT、Session-bound DB、Memory-only BYOK、Schema、Replay、Release Gate 和 Incident Runbook。

证据状态：生产安全和 Incident rehearsal 为 `PENDING_HUMAN_EVIDENCE`。

## 3. 哪些数据来自不知情个人？

当前 Canonical Event Pack 使用组织和政府公开材料，不使用真实个人投资记录。合成社交网络没有真实用户。用户上传在抽取前会经过确定性 Secret/PII 初筛：已登记的高风险类别会阻断，邮箱/电话等可复核类别需要确认并在处理前脱敏；该能力不是完整 PII 检测、删除请求或数据主体流程。

控制：抽取前内容安全 gate、安全摘要不回显原文、禁止上传敏感个人数据、最小化 Provider Payload、无真实社交抓取。

证据状态：隐私影响评估为 `PENDING_HUMAN_EVIDENCE`。

## 4. 哪个输出最容易被误读？

价格路径、最大回撤、经验区间、Cascade Score、代表性 Trace 和 LLM 的 Belief Summary 最容易被误读为真实预测、发生概率或真实投资者动机。

控制：结果页与导出显示 synthetic、conditional、not a forecast、not investment advice、valid N、版本和限制。

证据状态：真实用户 Comprehension Test 为 `PENDING_HUMAN_EVIDENCE`。

## 5. 哪个模型最难验证？

实时 GLM Cognitive Agent 最难验证，因为供应商行为可能漂移，语义质量不能只靠 Schema 判断，语言与 Persona 也会影响结果。信息传播和 synthetic market calibration 同样缺少真实历史外样本验证。

控制：Model Inventory、Prompt Hash、Cache、Code Grader、Rule fallback、Single intervention 和明确的 synthetic 标签。

证据状态：Live Model 与 External Calibration Review 为 `PENDING_HUMAN_EVIDENCE`。

## 6. 人类在哪里能纠错？

- 审核、编辑或拒绝候选 Claim。
- 冻结前检查来源和 knownAt。
- 修改研究问题和唯一干预。
- 拒绝合成 Clarification 或其他假设。
- 在结果页查看版本、限制、Trace 和样本量。
- 停止实验、清除 BYOK、关闭 Live LLM。
- 阻止 Release。

缺口：当前没有面向最终用户的一键 Artifact Invalidation 和完整数据删除界面。

## 7. 人类是否被迫接受 AI 默认？

不应被迫接受。AI_PROPOSED Claim 必须处理后才能 Freeze；用户可以 Edit 或 Reject。实时 LLM 可关闭，系统可以 Rule-only。默认实验可修改一个干预变量。

风险：UI 默认值可能产生锚定效应；是否真正感到有控制权尚未由用户验证。

证据状态：`PENDING_HUMAN_EVIDENCE`。

## 8. 是否有更低自治的替代？

有：

- Rule-only Agent。
- Immutable cached decision。
- 手工 Claim 输入与审核。
- Synthetic offline Event Pack。
- Precomputed matched-seed result。
- 禁用 Provider 调用和所有模型 repair。

这些替代保留核心实验价值并降低供应商、成本和注入风险。

## 9. 结果是否可重现？

确定性内核、Seed、Matched Pair、Prompt Hash、Schema、Cache Key 和 Event-log Hash 支持重放。实时 LLM 只有在缓存命中或供应商输出冻结时才能可靠重放。

当前旗舰独立重放 artifact 尚未附入 Release Gate，状态为 `NOT_EVALUATED`。

## 10. 供应商变化会怎样？

模型行为、价格、Token、Context、拒答、保留与条款可能变化。稳定 Model ID 不保证稳定输出。

控制：Catalog、Component Inventory、Prompt/Response Hash、Provider-neutral Gateway、Cache、Rule fallback 和 Model Change Policy。

证据状态：供应商条款与 Live Evaluation 为 `PENDING_HUMAN_EVIDENCE`。

## 11. 是否有明确退出或撤回机制？

用户可清除 BYOK、停止新实验、禁用 Live LLM 和改用 Rule-only。团队可停止服务、隔离 Event Pack 与撤回公开导出。

缺口：按数据或模型版本批量标记 Experiment 为 `INVALIDATED` 尚未实现，状态为 `CONTROL_GAP`。

## 12. 限制是否在用户决策点展示？

Manifest、Event Pack、结果和导出均有 Limitations 字段，SpaceX 包含双语 synthetic 标签。是否在所有关键页面足够显眼、是否被用户读懂仍未完成观察研究。

证据状态：`PENDING_HUMAN_EVIDENCE`。

## 偏差与公平检查

- 不使用受保护属性决定 Agent 理性程度。
- Persona 应基于可测行为参数，不基于人口刻板印象。
- T4 社交内容不能直接成为 FACT。
- 中英文提示与输出需要分开验证。
- 不能把合成 Agent 的群体结果映射为现实群体评价。

人类 Bias Review 尚未完成。

## 最终判断

系统已实现较低自治、结构化证据、确定性执行、可回退和发布阻断等责任 AI 控制，但缺少人类用户、领域专家、模型验证、安全、许可和运营证据。当前不能标为生产可用或专业验证完成。

# EventShock Lab Incident Response

## 状态

本文件是当前响应 Runbook。团队尚未完成具名演练，运营证据状态为 `PENDING_HUMAN_EVIDENCE`。Runbook 存在不等于具备已经验证的响应能力。

## 目标

1. 阻止 Secret、跨 Session 数据或错误结果继续传播。
2. 确认受影响的用户、Session、实验、Event Pack、模型、提示词和数据版本。
3. 保留必要证据，同时最小化敏感数据暴露。
4. 恢复可信版本并重新验证。
5. 向受影响人员说明事实、影响、处置和仍未知的内容。

## 严重度

| 级别 | 示例 | 初始动作 |
| --- | --- | --- |
| P0 Critical | API Key 或数据库公开、跨 Session 大规模读取、远程代码执行、真实交易权限出现 | 立即停止公开服务、吊销凭据、隔离主机和导出 |
| P1 High | Future leakage 污染旗舰结果、Prompt injection 修改状态、关键撮合或指标错误 | 禁用受影响功能、冻结新实验、隔离 artifact |
| P2 Medium | 单 Session 失败、供应商持续超时、非敏感日志过量、局部 UI 误导 | 降级到缓存/规则模式、记录范围并安排修复 |
| P3 Low | 文案错误、无安全影响的可恢复展示问题 | 建立记录、常规修复和回归 |

若影响不清楚，按更高一级处理，直到证据支持降级。

## 角色

- Incident Commander：Product & Research Lead 或其指定副手，控制时间线和决策。
- Security Lead：Full-stack / Platform & Design Lead，负责 Host、Proxy、Secret 和访问控制。
- Model Lead：LLM & Evaluation Lead，负责模型、提示词、缓存和 Provider。
- Data Lead：Data & Quant Validation Lead，负责 Event Pack、knownAt、许可和受影响实验。
- Market Lead：Market Microstructure Lead，负责订单簿、账本、指标和重放。
- Communications Owner：由 Incident Commander 指定，避免多人发布不一致消息。

当前没有具名值班表和响应 SLA，状态为 `PENDING_HUMAN_EVIDENCE`。

## 响应流程

### 1. Detect

检测来源包括：健康检查、API 错误、用户报告、异常日志、测试失败、event-log hash 漂移、红队失败、供应商账单异常、Secret 扫描、来源变更和指标复算不一致。

记录：发现时间、报告人、最初证据、受影响环境、已知 Secret、可能的数据和功能范围。

### 2. Contain

- 在宝塔“计划任务”中先停用 `EventShock GitHub 自动同步部署`，防止调查期间自动引入新提交；不要只杀死当前进程而保留下一轮调度。
- 停止新的实验和模型调用。
- 清除内存 BYOK，并要求用户在智谱侧吊销可能泄漏的 Key。
- 停止或隔离 Caddy/App 容器，但先保存必要日志和只读数据库副本。
- 禁用受影响 Event Pack、模型 ID、Prompt 版本或导出入口。
- 对数据泄漏停止公开访问和进一步同步。
- 切换到已验证的 synthetic、cache 或 rule-only 路径。

不要在未确认范围时删除原始证据，也不要把 Secret 复制到 Issue、聊天或 Postmortem。

### 3. Assess

建立受影响集合：

- 时间窗口。
- Release、Commit 和 Container Digest。
- Event Pack ID、Claim、Source、knownAt 和 checksum。
- 模型 ID、Prompt Hash、Schema、Agent Config 和 Observation Hash。
- Experiment ID、Session ID、seed、event-log hash 和导出。
- 可能读取 Secret 或数据的人员、服务和第三方。

当前 API 可以把当前 Session 中一个已完成实验标记为 `INVALIDATED`，保留结果证据与哈希，同时阻断 results、runs、metrics、traces 和 export 的有效研究使用；但数据库没有一键按模型、数据版本或时间窗口批量检索和失效的功能。该批量缺口为 `CONTROL_GAP`。在修复前，需要停止公开下载，利用 manifest 和审计事件人工建立受影响清单，再逐个执行单实验 invalidation。

### 4. Invalidate artifacts

- 不删除原始 artifact；将其移动到受限位置并标记不可用于决策。
- 在用户可见位置显示 invalidation 原因、时间和影响版本。
- 生成替代结果时保留新旧 Artifact ID，禁止静默覆盖。
- 受 Future leakage 影响的所有后续 belief、order、trade、metric 和 report 都视为受污染。
- 受撮合或账本错误影响的全部运行必须重新执行。

单实验 API 会原子保存 reason code、说明和时间，保留原始结果用于取证，并写入包含结果/Event Pack/引擎/模型/提示词哈希的审计事件。它不会删除 artifact，也不会自动发现其他受同一问题影响的实验。批量 invalidation 能力未实现前，不得宣称整个受影响集合的识别与处置已经自动化。

### 5. Eradicate and fix

- 修补输入、Schema、权限、Source 时间、指标公式或依赖。
- 轮换所有受影响 Secret、TLS 证书和云凭据。
- 清除可能污染的不可变缓存；记录清除依据和 Cache Key 范围。
- 对外部来源重新核对 URL、时间、Hash 和许可。
- 对高风险修复进行非作者 Review。

### 6. Revalidate

- 运行完整 Backend、Frontend、Build 和 Deployment Test。
- 重放 Golden Seeds 和 Flagship Artifact。
- 执行相关红队 Case；P0/P1 需要完整 P0 Red-team Suite。
- 更新 Component Inventory、Validation Report、Threat Model、Risk Register 和 ADR。
- 重新运行 P0 Release Gate。

缺失人工证据时 Release Gate 仍应阻断。

### 7. Recover

- 从已验证 Commit、Image Digest、Event Pack 和数据库备份恢复。
- 核对 `/opt/eventshock/current`、`github-sync.state`、目标 GitHub SHA、容器 `/api/health.releaseCommit` 与宝塔任务日志；五者不一致时不得恢复自动同步。
- 先以 rule-only 或 frozen cache 模式开放健康检查。
- 小范围验证新实验和导出后再逐步恢复实时模型。
- 监控错误率、内存、SQLite 锁、Provider Call、Token 和异常 Session 行为。

### 8. Notify

通知内容应包含：已确认事实、仍未知内容、受影响时间和功能、用户需要执行的动作、已采取的遏制、下一次更新时间和联系渠道。

禁止把推测写成事实，也禁止在通知中暴露其他用户 Session、Secret 或受限数据。

### 9. Postmortem

Postmortem 应在事件受控后记录：

- 影响与严重度。
- 完整 UTC 时间线。
- 根因和促成条件。
- 哪些控制有效、哪些控制失效。
- 检测和响应延迟。
- Artifact invalidation 范围。
- 修复、测试和防复发变更。
- Owner 与可核验完成证据。

Postmortem 采用无责原则，但所有高风险改进必须有明确 Owner 和 Release Gate 绑定。

## 场景化处置

### API Key 泄漏

停止模型调用，清除内存配置，用户在智谱控制台吊销 Key，检查响应、Caddy/App 日志、SQLite、ZIP、Crash Dump 和 Shell History。更换相关凭据后执行 `rt-secret-disclosure-001`。

### Future leakage

冻结 Event Pack，确认错误 `knownAt` 的最早可见时刻，找出所有引用该信息的实验和导出，全部 invalidated。修正来源后从污染前的配置重新运行 matched seeds。

### Prompt injection 越权

禁用 LLM 路径并切换 rule fallback，隔离恶意来源，检查是否发生数据库、配置、账本或导出修改。修复 delimiter、Schema 或工具权限后执行 Prompt Injection 与 Action Overreach Case。

### 撮合、账本或指标错误

停止所有结果发布，确定受影响版本和公式，重跑守恒、属性和 Golden Replay。旧结果不得与修复后版本合并。

### 供应商故障或成本异常

关闭实时调用，使用 immutable cache 或 rule-only，检查请求次数、Token、错误码和账单。当前缺少全局美元预算，必须人工在供应商控制台设置余额与限额。

### 受限数据进入仓库

停止公开访问，确认 Fork、CI artifact、Container Layer、Release 和用户下载范围，咨询有权限的人类许可负责人。删除或重写历史必须遵守证据保留和法律要求，不能由 Agent 擅自执行。

## 演练要求

至少演练：Secret 泄漏、Future leakage、SQLite 恢复、供应商不可用和错误指标 invalidation。演练 artifact 必须包含时间、参与人、步骤、观察、失败、恢复时间和变更。

当前演练状态：`PENDING_HUMAN_EVIDENCE`。

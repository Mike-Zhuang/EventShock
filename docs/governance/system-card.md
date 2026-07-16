# EventShock Lab System Card

## 文档状态

- 系统版本：`0.1.0` MVP
- 文档日期：2026-07-16
- 适用部署：课程演示与受控研究试用
- 当前发布判断：`BLOCKED`
- 阻断原因：用户理解研究、独立领域专家审查、实时模型验证、部署安全审查、第三方许可审查、完整红队执行和 incident rehearsal 均未形成可核验的人类证据

本卡描述当前仓库实现，不代表生产认证、监管批准、投资适当性结论或独立模型验证。凡需要真实用户、领域专家、安全人员或运营人员参与的证据，统一标记为 `PENDING_HUMAN_EVIDENCE`。

## 系统目的

EventShock Lab 是事件驱动的市场机制情景实验室。用户冻结带来源和 `knownAt` 的 Event Pack，选择一个干预变量，在相同随机种子下运行基线和反事实实验，再比较风险分布并追踪信息、信念、订单、成交、流动性和指标之间的机制链。

系统回答的是：在明确的数据、Agent、市场机制和参数假设下，一个干预怎样改变模型内部结果。系统不回答真实资产未来价格，也不提供个性化投资建议。

## 预期用户

- 课程中的学生团队和教师。
- 在受控环境中评估事件传播机制的市场风险研究人员。
- 需要理解 Human-in-the-loop、point-in-time、matched-seed 和模型治理的学习者。

是否适合资产管理机构、银行或交易所的生产风险流程仍需独立验证，当前状态为 `PENDING_HUMAN_EVIDENCE`。

## 禁止用途

- 真实证券自动交易、订单路由、资产配置或风险限额执行。
- “买入、卖出、目标价、胜率”形式的投资建议。
- 将合成 Agent 的行为当作真实投资者证据。
- 将单次仿真路径当作概率预测。
- 使用未授权行情、指数、社交或个人数据。
- 在缺少人工审核时把 LLM 抽取结果升级为事实。
- 在多租户敏感数据场景中依赖匿名 Session ID 充当身份认证。

## 架构边界

### 确定性科学内核

- 单调仿真时钟和确定性事件队列。
- 整数 tick 的限价订单簿与价格—时间优先撮合。
- 研究级单价开盘竞价与有界波动停牌状态 gate。
- 合成账户账本、风险约束和守恒检查。
- 规则智能体、信息网络和市场机制。
- matched-seed 聚合、经验区间、路径、流量和 trace。

该层不依赖 LLM 供应商。相同代码、配置和种子应产生相同 event-log hash。

### AI 认知层

- 上传来源中的候选 Claim 抽取。
- 受限观察下的模拟信念和行动偏好。
- 智谱 Chat Completions 结构化 JSON 调用。
- 严格 Pydantic Schema、证据 ID、允许动作、重试、一次修复、不可变缓存和规则回退。

LLM 不拥有订单簿、账本、数据库、真实交易工具、发布工具或配置修改权限。BeliefDecision 只能进入确定性策略，不能直接成为订单。

### 控制面

- FastAPI 提供 API 和静态前端。
- SQLite 保存匿名会话的 Event Pack 草稿、场景、审计事件、Experiment 状态/完整配对 checkpoint、不可变 Study 记录和单实验 invalidation 元数据。
- BYOK 凭据仅保存在进程内存，具有过期时间；SQLite 和导出不保存完整密钥。
- Caddy 终止 HTTPS、设置安全响应头、限制请求体并移除 Session Header 日志字段；正式监测拓扑中的宝塔 Nginx 只在 Docker 私网反向代理到回环应用，记录真实站点流量并关闭 SSE 缓冲。

匿名 Session ID 是隔离键，不是用户身份认证。系统当前不适合保存敏感、多租户或受监管数据。

## 模型与组件清单

机器可读清单位于 `backend/app/governance/registry.py`，包括：

- 规则智能体与确定性订单策略。
- 限价订单簿、账本和事件队列。
- 信息传播网络与 point-in-time 信息库。
- 智谱 REST 网关及运行时目录中的全部 GLM 模型。
- `event_extraction_v1.0.0` 与 `belief_v1.0.0` 提示词及其 SHA-256。
- matched-seed 指标组件和 cognition code grader。
- 内存 BYOK Secret 控制。

每项记录 owner、purpose、materiality、version、Schema、输入、输出、验证、限制、回退和 approval status。GLM 模型、提示词、网关、grader 与 BYOK 生产控制仍为 `PENDING_HUMAN_EVIDENCE`。

## 价格与行为权威

- 成交价由订单簿中先到达的 resting order 价格确定。
- 账本只接受确定性撮合产生的成交。
- LLM 只能输出结构化信念与行动偏好。
- 确定性策略负责数量、方向、滑点和短卖限制。
- 风险检查可以缩小、阻断或取消意图。
- 系统没有真实交易连接。

## 数据边界

SpaceX 演示包使用 SEC、Nasdaq、SpaceX、FTSE Russell、FCC 和 NASA 的链接、元数据和短释义作为事实来源。市场路径、基准路径、订单簿深度、被动流、风险规避流、Agent 人群和所有仿真结果均明确标为 synthetic。

Nasdaq-100 公告不能在 `2026-06-27T00:00:00Z` 前进入 Agent 观察。Reuters 报道的 JPMorgan 被动流估计晚于演示观察截止时间，只能作为事后验证来源，不能进入仿真 Claim 或校准。

## 人类控制点

- 用户审核、编辑或拒绝 LLM 提出的 Claim。
- 上传正文和元数据在抽取或模型调用前经过确定性内容安全 gate；高风险内容阻断，可复核内容由用户确认后先脱敏。
- 必需 Claim 被人工批准后才能冻结 Event Pack。
- 用户选择研究问题和唯一干预变量。
- 用户决定是否启用实时 LLM，以及提供何种 BYOK 模型。
- 用户解释结果并承担现实决策责任。
- 发布、许可判断、安全批准和模型验证必须由真实人员完成。

## 输出

- 基线与干预的成组指标分布。
- matched-seed 差值、经验 95% 区间和方向一致率。
- 中位路径、Agent 流量和代表性 trace。
- 有界 Study 的预注册、全因子/LHS 单元、负对照、消融、Holm 与探索性敏感性结果；Study 始终声明 `historicalValidityEstablished=false`，认知/若干移除臂明确标为冻结 tape 或可执行代理。
- 数据、模型、提示词、场景和 event-log 版本信息。
- 可复现导出包和限制声明。

任何结果都必须同时展示“情景分析而非预测或投资建议”的说明。

## 已实现控制

- 严格 Schema 和未知字段拒绝。
- evidence ID 白名单和未来信息检查。
- 抽取前内容安全扫描、安全摘要和确认后脱敏。
- ABSTAIN 安全回退。
- bounded retry 与一次修复。
- 不可变 LLM 决策缓存键。
- matched seeds 和单干预差异验证。
- 完整 matched-pair checkpoint、重启后哈希校验恢复和 SSE 状态快照。
- 单实验 invalidation、结果/子资源/导出阻断与哈希审计；批量发现和失效仍未实现。
- Session 范围的数据库查询与内存 BYOK。
- 固定服务器端导出文件名。
- 撮合、账本、重放、来源和 Event Pack 测试。
- 机器可执行红队定义和 P0 发布门禁。

## 尚未完成的证据

| 证据 | 状态 | 影响 |
| --- | --- | --- |
| 真实目标用户完成流程并正确解释结果 | `PENDING_HUMAN_EVIDENCE` | 不能证明产品不会被系统性误读为预测 |
| 独立市场微观结构或模型风险专家审查 | `PENDING_HUMAN_EVIDENCE` | 不能宣称方法和参数得到外部认可 |
| 智谱实时模型质量、成本、延迟和多语言评估 | `PENDING_HUMAN_EVIDENCE` | 只能证明 Mock 契约和本地校验，不证明实时表现 |
| 部署主机、TLS、日志、内存和 BYOK 安全审查 | `PENDING_HUMAN_EVIDENCE` | 不能宣称生产安全 |
| 数据与供应商许可审查 | `PENDING_HUMAN_EVIDENCE` | 不能扩大外部内容存储和再分发范围 |
| 完整红队运行证据 | `NOT_EVALUATED` | 红队定义本身不是测试通过证据 |
| Incident response 演练 | `PENDING_HUMAN_EVIDENCE` | 不能宣称具备运营恢复能力 |
| 批量实验失效标记能力 | `CONTROL_GAP` | 发生模型或数据错误时需要人工识别和隔离受影响导出 |

## 变更与重新验证

以下变化触发组件版本更新和相关验证重跑：模型 ID、提示词、结构化输出 Schema、证据特征、来源层级、knownAt 规则、订单策略、撮合规则、账本规则、Agent 默认值、校准、指标公式、缓存键和导出格式。

重大行为变化不得与旧实验直接合并比较。旧 artifact 必须保留其原始版本和限制。

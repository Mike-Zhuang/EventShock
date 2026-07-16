# EventShock Lab AI Collaboration Disclosure

## 目的

本文件说明项目开发和产品运行中 AI 的角色，避免把 AI 产出描述为独立人类验证、专业批准或事实权威。

## 开发过程中使用的 AI

项目开发使用了 OpenAI Codex 进行仓库阅读、代码生成、测试生成、文档编写、部署辅助和公开来源检索。具体工作包括：

- 根据蓝图实现前后端、仿真、认知与治理组件。
- 编写和修改 Python、TypeScript、JSON、Markdown、Docker 与反向代理配置。
- 生成测试并运行仓库命令。
- 检索 SEC、Nasdaq、SpaceX、FTSE Russell、FCC、NASA 和智谱官方材料。
- 整理 SpaceX Event Pack 的来源、时间线、Claim 分层和限制。
- 编写 System Card、Data Card、Threat Model、ADR 和 Release Gate。

AI 生成内容可能包含错误、遗漏、过时信息或不合适的设计判断。自动测试通过不等于人类理解、领域正确性或生产安全。

## 本轮治理工作的 AI 贡献

- 机器可读组件清单。
- 十类红队用例和评分契约。
- 阻断式 P0 发布门禁。
- Governance 专项测试。
- 本目录中的治理文档和十个 ADR。

本轮已进行代码解析、专项 Pytest 和 Ruff 检查。真实用户研究、独立专家审查、安全审查、许可审查、实时 GLM 评估和 Incident rehearsal 均未由 AI 替代，状态为 `PENDING_HUMAN_EVIDENCE`。

## 产品中的 AI

### Event extraction

LLM 从用户提供的来源片段中提出候选 Claim。输出分为 FACT、ESTIMATE、OPINION 和 RUMOR，保留 knownAt 和 source evidence ID。所有 Claim 都要求人工审核；LLM 无权冻结 Event Pack。

### Cognitive agents

LLM 在有限 Observation 下输出 BeliefDecision，包括方向、预期变化、尾部风险、Evidence Assessment、行动偏好、目标头寸比例、紧迫度和置信度。该输出不是订单。

### 决定性边界

- System Prompt 与 Schema 固定版本和 Hash。
- 来源文本放在 untrusted delimiter 内。
- 模型不能使用互联网、工具、数据库或交易接口。
- 本地验证证据 ID、动作、版本、范围和 Schema。
- 确定性策略把 BeliefDecision 转为有界 synthetic order intent。
- 风险和账本规则可以阻断意图。
- 持续失败进入 ABSTAIN 或空抽取规则回退。

## 模型供应商

当前支持智谱 Chat Completions。用户可在前端提供自己的 API Key 并选择运行时目录中的 GLM 模型。完整 Key 只驻留应用内存并按 TTL 过期。

仓库没有完成真实计费请求的系统评估，也没有代表用户接受智谱的服务条款、数据保留或训练政策。用户在使用真实 Key 前需要自行确认条款。

## 未使用 AI 的权威范围

AI 不是以下内容的权威：

- 官方事件事实和发布时间。
- Event Pack 的最终人工批准。
- 成交价格、订单优先级和账本状态。
- 指标公式的最终领域批准。
- 数据许可和法律判断。
- 安全发布批准。
- 投资决策。

事实权威来自可追溯来源和人工审查；成交与账本权威来自确定性代码；发布权威来自有证据的 P0 Gate。

## 数据发送边界

当用户启用实时智谱模型时，结构化 System Prompt、任务说明和经过限制的用户 Evidence/Observation 会被发送给供应商。用户不应提交 Secret、个人交易记录、受监管数据或没有权利发送给第三方的文本。

本项目不需要把完整仓库、SQLite、其他 Session 数据或 BYOK Key 内容发送给模型。Authorization Header 只用于 Provider 请求身份验证。

## 人工职责

- 选择和核实来源。
- 审核、编辑或拒绝候选 Claim。
- 冻结 Event Pack 与实验配置。
- 检查 synthetic、estimate 和 official fact 标签。
- 解释统计区间和模型限制。
- 复核 AI 生成代码与高风险算法。
- 批准数据许可、安全和发布。
- 对任何现实决策承担责任。

## 当前审核状态

| 项目 | 状态 |
| --- | --- |
| 自动 Schema 与单元测试 | 已执行部分，详见 Validation Report |
| 开发者非作者代码 Review | `PENDING_HUMAN_EVIDENCE` |
| 市场微观结构专家 Review | `PENDING_HUMAN_EVIDENCE` |
| LLM 行为与 Grader 人工验证 | `PENDING_HUMAN_EVIDENCE` |
| 用户理解与可用性 | `PENDING_HUMAN_EVIDENCE` |
| 安全与许可 Review | `PENDING_HUMAN_EVIDENCE` |

因此当前版本只能作为 AI 辅助开发的课程演示原型，不应被描述为已通过独立人类验证的生产系统。

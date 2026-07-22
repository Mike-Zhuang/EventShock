# AI 供应商接入说明

EventShock Lab 支持用户自带 API Key（BYOK）的外部模型调用。默认供应商始终是智谱，默认模型是 `glm-5.2`；不填写密钥时，项目仍可完整运行确定性的 `RULE_ONLY` 流程。

> 本页价格和能力于 **2026-07-20** 根据各供应商官方文档核验。价格会调整，界面展示的是估算依据而不是账单承诺；正式调用前请同时查看界面链接到的官方价格页。

## 已接入供应商

| 供应商 | 接入模型 | 结构化输出策略 | 公开刊例价摘要（每 100 万 token） | 固定 API 端点 |
| --- | --- | --- | --- | --- |
| 智谱（默认） | `glm-5.2`、`glm-4.7-flashx` 及兼容的既有 GLM 目录 | JSON Object；后端执行完整 Schema、证据 ID、时间与动作权限校验 | GLM-5.2：输入 ¥8、输出 ¥28；GLM-4.7-FlashX：输入 ¥0.5、输出 ¥3 | `https://open.bigmodel.cn/api/paas/v4/chat/completions` |
| OpenAI | `gpt-5.6-luna`、`gpt-5.6-terra`、`gpt-5.6-sol` | 原生 JSON Schema；后端继续执行业务约束校验 | Luna：输入 $1、输出 $6；Terra：输入 $2.5、输出 $15；Sol：输入 $5、输出 $30。超过 272K 输入时按官方长上下文倍率预留 | `https://api.openai.com/v1/responses` |
| Anthropic | `claude-haiku-4-5-20251001`、`claude-sonnet-4-6`、`claude-sonnet-5`（推荐） | `output_config.format` 原生 JSON Schema；后端继续二次校验 | Haiku：输入 $1、输出 $5；Sonnet 5 在 2026-08-31 前为输入 $2、输出 $10，之后标准价为 $3/$15。预算按未来标准价及最高缓存写入倍率保守预留 | `https://api.anthropic.com/v1/messages` |
| Google Gemini | `gemini-3.5-flash` | 原生 JSON Schema 子集；后端继续按完整本地模型校验 | 输入 $1.5、输出（含 thinking）$9；缓存输入 $0.15 | `https://generativelanguage.googleapis.com/v1beta/interactions` |
| DeepSeek | `deepseek-v4-flash`、`deepseek-v4-pro` | JSON Object；后端检测空响应并执行一次有限修复和完整本地校验 | Flash：输入缓存未命中 $0.14、输出 $0.28；Pro：输入缓存未命中 $0.435、输出 $0.87 | `https://api.deepseek.com/chat/completions` |
| 阿里云百炼 / Qwen | `qwen3.6-flash` | JSON Object；提示词明确要求 JSON，后端执行完整本地校验 | 中国北京 0–256K 档输入 ¥1.2、输出 ¥7.2；256K–1M 档输入 ¥4.8、输出 ¥28.8，费用闸门按可触发的最高档预留 | `https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions` |
| Moonshot / Kimi | `kimi-k3`；`kimi-k2.6` 仅展示、因官方未明确独立输出上限而禁止调用 | 原生 JSON Schema；后端继续执行业务约束校验 | Kimi K3：输入缓存未命中 ¥20、输出 ¥100；K2.6：输入缓存未命中 ¥6.5、输出 ¥27 | `https://api.moonshot.cn/v1/chat/completions` |

“原生 JSON Schema”表示供应商在生成阶段约束 JSON 形状，但不代表业务内容可信。无论供应商能力如何，EventShock 都会再次验证字段类型、数值范围、允许引用的证据 ID、时间边界和有限动作集合。验证失败只允许一次修复；仍失败时按用户配置回退到规则或直接失败关闭。

## 接入验证状态与反馈

- 智谱是当前唯一使用本项目真实 API Key 完成端到端调用验证的供应商。
- 其他供应商已经通过自动化协议、结构化输出和错误映射测试，但维护者尚未使用真实付费账号完成项目级端到端验证；界面会明确标记为“社区预览”。供应商接口仍可能变化，请先用小额预算测试。
- 遇到兼容性问题可使用仓库的 [供应商兼容性 Issue 模板](https://github.com/Mike-Zhuang/EventShock/issues/new?template=llm-provider-feedback.yml)。Issue 只能提交供应商、模型、时间、页面、脱敏错误码和 Request ID；不得粘贴 API Key、完整提示词、结果正文、账号信息或其他个人数据。

## 结果解释助手

完成实验后，结果页提供一个可选的 AI 解释层。它不会自动产生付费调用；只有用户点击“生成结果解读”或发送追问时，后端才使用当前登录会话内已经配置的临时 API Key。

- 浏览器只提交实验 ID、当前界面语言和有界对话历史，不提交 API Key，也不把整份结果 JSON 回传给服务器。后端按当前登录用户读取持久化的权威结果快照，跨用户实验 ID 会被拒绝。
- 后端会把经过裁剪的结果切片、已审核 claim/来源元数据和本轮对话发送给用户选择的外部模型供应商；来源原始正文和 API Key 不进入提示词。界面会在付费调用前明确提醒，用户不应在追问中输入秘密或个人信息。
- 首次解释会运行固定的只读结果工具，覆盖实验概览、指标汇总、配对随机种子、市场路径、机制 Trace、Agent 结果、认知层、分析诊断、局限和来源清单；后续追问由结构化 Planner 从同一白名单中选择必要切片。工具不能访问网络、任意文件或 SQL，也不能修改实验或提交交易。
- 每段事实性解释必须引用本轮工具返回的 `result:*` 证据 ID；模型输出仍需通过严格 Schema、允许引用集合和“不是预测、不是投资建议”的边界校验。工具输出过长时会确定性抽样并在界面标记，不会假装读取了被省略的明细。
- 当前界面为英文时回答英文，为中文时回答简体中文。多轮对话不写入账号数据库、通用认知决策缓存、审计正文或导出包；为避免网络丢包导致重复计费，端点只在内存中合并进行中的相同请求，并将成功响应保留最多 60 秒用于同 ID 重试。审计只记录结果哈希、供应商、模型、语言、工具名和 token 统计。
- “分析摘要 / Reasoning summary”是解释模型生成的简短、可核验证据摘要，不是也不会声称是供应商的隐藏思维链。原始 `reasoning_content`、加密 thinking、签名、系统提示词和 API Key 不会返回前端。摘要默认折叠，用户可以选择是否请求和展开。

## 费用口径

- 界面同时显示供应商的公开输入、缓存输入和输出价格，并标明币种、地区、核验时间和官方来源。
- 运行前费用闸门使用保守上界：分档价格取最高可触发档，OpenAI 长上下文采用官方倍率，Anthropic 和 Qwen 会覆盖更高的缓存写入费率。
- 免费额度、批处理折扣、促销、资源包和账号专属折扣不会被用于放宽硬预算。
- 人民币价格按冻结的保守汇率下限折算成美元预算；该换算用于阻止超额调用，不是支付汇率或发票报价。
- 供应商、模型或价格任一项无法核验时，系统在发出请求前失败关闭，不会把未知价格当作零。

## 密钥和隐私

- API Key 只绑定当前登录会话，在同源 HTTPS 后端进程内存中短时保存；它不会写入账号、SQLite、浏览器持久存储、日志、审计详情或导出包。服务每分钟主动清除过期凭据，退出登录和服务重启也会立即清除。
- 切换供应商会原子替换当前会话的旧凭据，不会长期同时保存多家密钥。
- 退出登录、凭据过期、后端重启或主动清除后必须重新填写。
- 端点由服务器白名单固定，用户不能填写任意 Base URL，从而避免把密钥发送给未授权主机。
- 不要向外部模型发送个人身份信息、券商凭据、私人通信、受监管数据，或无权交给第三方处理的材料。

## 官方资料

- 智谱：[模型概览](https://docs.bigmodel.cn/cn/guide/start/model-overview)、[结构化输出](https://docs.bigmodel.cn/cn/guide/capabilities/struct-output)、[价格](https://bigmodel.cn/pricing)
- OpenAI：[模型](https://developers.openai.com/api/docs/models)、[结构化输出](https://developers.openai.com/api/docs/guides/structured-outputs)、[价格](https://openai.com/api/pricing/)
- Anthropic：[模型](https://platform.claude.com/docs/en/about-claude/models/overview)、[结构化输出](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)、[价格](https://platform.claude.com/docs/en/about-claude/pricing)
- Google Gemini：[API](https://ai.google.dev/api)、[结构化输出](https://ai.google.dev/gemini-api/docs/structured-output)、[价格](https://ai.google.dev/gemini-api/docs/pricing)
- DeepSeek：[模型与价格](https://api-docs.deepseek.com/quick_start/pricing/)、[JSON 输出](https://api-docs.deepseek.com/guides/json_mode/)
- 阿里云百炼：[模型](https://www.alibabacloud.com/help/en/model-studio/models)、[结构化输出](https://www.alibabacloud.com/help/en/model-studio/qwen-structured-output)、[价格](https://www.alibabacloud.com/help/en/model-studio/model-pricing)
- Moonshot / Kimi：[模型](https://platform.kimi.com/docs/models)、[K2.6 价格](https://platform.kimi.com/docs/pricing/chat-k26)、[K3 价格](https://platform.kimi.com/docs/pricing/chat-k3)

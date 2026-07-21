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

## 费用口径

- 界面同时显示供应商的公开输入、缓存输入和输出价格，并标明币种、地区、核验时间和官方来源。
- 运行前费用闸门使用保守上界：分档价格取最高可触发档，OpenAI 长上下文采用官方倍率，Anthropic 和 Qwen 会覆盖更高的缓存写入费率。
- 免费额度、批处理折扣、促销、资源包和账号专属折扣不会被用于放宽硬预算。
- 人民币价格按冻结的保守汇率下限折算成美元预算；该换算用于阻止超额调用，不是支付汇率或发票报价。
- 供应商、模型或价格任一项无法核验时，系统在发出请求前失败关闭，不会把未知价格当作零。

## 密钥和隐私

- API Key 只绑定当前登录会话，在同源 HTTPS 后端进程内存中短时保存；它不会写入账号、SQLite、浏览器持久存储、日志、审计详情或导出包。
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

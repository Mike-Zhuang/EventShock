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

## Event Pack Factory 的 Search 与 Reader

Event Pack Factory 只通过智谱官方固定端点调用联网工具；它不会采用聊天模型名称猜测工具能力，也不允许用户填写任意工具地址：

| 能力 | 固定端点 | 当前实现中的计费状态 |
| --- | --- | --- |
| Web Search | `https://open.bigmodel.cn/api/paas/v4/web_search` | 按所选引擎的官方单次公开价格在调用前展示估算 |
| Reader | `https://open.bigmodel.cn/api/paas/v4/reader` | **未知**；当前官方公开材料未给出本项目可核验的 Reader 单价，界面不得显示为免费或零成本 |

截至 **2026-07-22**，Factory 使用并展示以下智谱 Web Search 刊例价：

| 搜索引擎 | 单次公开价格 |
| --- | --- |
| `search_std` | ¥0.01 |
| `search_pro` | ¥0.03 |
| `search_pro_sogou` | ¥0.05 |
| `search_pro_quark` | ¥0.05 |

价格可能调整。每次正式调用前都应查看[智谱价格页](https://bigmodel.cn/pricing)和账号控制台；Reader 价格在无法核验时必须明确标记未知，不能把缺少价格信息解释成免费。

Search 返回的标题、URL 和摘要只用于**来源发现**，不能直接支撑候选主张或 Event Pack 冻结。用户必须先批准某条发现记录，服务器才会用 Reader 读取该条已规范化的公开 HTTPS URL；Reader 取得的完整正文经过安全扫描后形成新的待审核证据来源，还要再次由人批准。只有已批准的 `PASTE` 或 Reader 证据会进入 Event Pack 物化。完整存储与删除语义见 [Event Pack Factory 与 AI 引导说明](event-pack-factory.md)。

Search 和 Reader 复用当前登录会话已经解析的智谱凭据：普通用户使用会话内临时 Key；部署指定管理员也可使用自己明确启用的服务器持久凭据。浏览器不会把 Key 写入 Factory 构建或持久存储。Search 查询与结果元数据可以按账号保存；普通用户 Key 不进入 SQLite，管理员持久凭据在 SQLite 中也只以认证加密密文和有限元数据存在。两类 Key 的明文都不进入日志、审计详情、Factory 构建或导出。

## 高级参数白名单

用户可以调整模型参数，但不能借此扩展模型权限。服务端总白名单和取值范围如下；具体供应商只开放其明确支持的子集，填写不支持的字段会在保存配置时失败关闭：

| 参数 | 服务端范围 |
| --- | --- |
| `temperature` | 0–2 |
| `topP` | 大于 0 且不超过 1 |
| `presencePenalty` | -2–2 |
| `frequencyPenalty` | -2–2 |
| `seed` | 0–2,147,483,647 的整数 |
| `timeoutSeconds` | 1–300 秒 |

智谱当前只开放 `temperature`、`topP` 与 `timeoutSeconds`；其他供应商按后端能力矩阵开放不同子集。系统不提供自定义 Base URL、请求头、工具、系统提示词或任意 JSON 扩展字段，以免把 API Key 发送给未经授权的主机或绕过证据与动作边界。

## 开源提示词与运行时抗注入边界

本仓库采用源码可用许可证，系统提示词正文可以在源码中被审阅；`/api/v1/prompts` 与普通前端只返回提示词元数据和哈希，不把正文当作运行时数据接口，但这不构成、也不应被描述成保密措施。

实际防线建立在可验证的运行时约束上：

- 来源正文、搜索摘要、历史对话和模型上一轮输出都放在明确分隔的“不可信数据”区，不能动态拼入 system prompt。
- 外部内容先经过确定性内容扫描；高风险输入在持久化或供应商调用前阻断，需要复核的输入必须由人确认。
- 模型结果必须满足严格 Schema、证据 ID、时间边界与有限动作集合；只允许一次有界修复，仍不合格就回退到明确标记的规则结果或失败关闭。
- 输出会检查不可见控制字符、提示词控制语言、凭据模式、原始 HTML、危险 URL、系统提示词长片段/稀有 n-gram，以及当前受保护密钥的明文和常见编码变体。
- 传给浏览器和审计的错误使用稳定代码，不回显原始供应商响应、系统提示词、API Key 或未验证草稿。

这些措施能显著缩小提示词注入和提示词泄漏面，但任何基于大语言模型的防护都不能保证绝对免疫。用户仍应把所有 AI 内容视为候选草稿，通过来源审核、主张审核、冻结确认和确定性运行门禁后再使用。

## 结果解释助手

完成实验后，结果页提供一个可选的 AI 解释层。它不会自动产生付费调用；只有用户点击“生成结果解读”或发送追问时，后端才使用当前登录会话内已解析的凭据。普通用户使用临时 API Key；部署指定管理员可使用自己明确启用的服务器持久凭据。

- 浏览器只提交实验 ID、当前界面语言和有界对话历史，不提交 API Key，也不把整份结果 JSON 回传给服务器。后端按当前登录用户读取持久化的权威结果快照，跨用户实验 ID 会被拒绝。
- 后端会把经过裁剪的结果切片、已审核 claim/来源元数据和本轮对话发送给用户选择的外部模型供应商；来源原始正文和 API Key 不进入提示词。界面会在付费调用前明确提醒，用户不应在追问中输入秘密或个人信息。
- 首次解释会运行固定的只读结果工具，覆盖实验概览、指标汇总、配对随机种子、市场路径、机制 Trace、Agent 结果、认知层、分析诊断、局限和来源清单；后续追问由结构化 Planner 从同一白名单中选择必要切片。工具不能访问网络、任意文件或 SQL，也不能修改实验或提交交易。
- 每段事实性解释必须引用本轮工具返回的 `result:*` 证据 ID；模型输出仍需通过严格 Schema、允许引用集合和“不是预测、不是投资建议”的边界校验。工具输出过长时会确定性抽样并在界面标记，不会假装读取了被省略的明细。
- 当前界面为英文时回答英文，为中文时回答简体中文。浏览器通过 POST SSE 接收固定枚举的安全阶段、累计模型数据块数和状态事件数；服务端自由文本、回答草稿、隐藏推理内容及其签名不会进入进度区。只有最终回答通过严格结构与引用校验后，完整解释才会一次性显示。
- SSE 等待采用 30 秒无活动超时，每次收到网络数据、心跳或事件都会重新计时，并另设 10 分钟防失控硬上限，从而覆盖 Planner、回答生成及有限结构修复的理论最坏耗时。单个 SSE 帧和待解析总缓冲区也有独立上限；超限内容会失败关闭。若连接到尚未提供流式路由的兼容旧后端，浏览器仅在 `404`、`405`、`406` 或 `501` 时使用相同请求体和请求标识回退旧 JSON 接口，仍不会展示部分输出，且会保留服务端返回的可重试性和计费不确定性。
- 点击“停止等待”只会终止当前浏览器连接，无法保证外部供应商或服务器中的合并请求同步终止，因此本次调用仍可能继续并产生费用。对于停止等待、连接中断、无活动超时或提前结束，界面第一次恢复会完整复用原 `clientRequestId` 和请求体，以便服务器在同一进程内合并旧调用、返回短期缓存，或从 SQLite 恢复已经成功持久化的终态；若服务在供应商已接收请求后、最终终态写入前重启，结果与计费状态仍可能未知，同一标识不能被承诺为跨崩溃零重复调用。只有同一标识返回明确终态失败后，用户再次阅读费用警告并确认，界面才使用新的请求标识发起独立调用。不可重试的内容类失败允许替换失败的最后一个问题并保留此前完整会话，不要求清空全部对话。
- 只有通过结构、引用和证据边界校验的完整用户问题与最终回答，才会按“账号 + 实验 + 会话”写入服务器 SQLite，供用户跨浏览器恢复或主动删除；默认最多保留 90 天、每个账号 300 轮、全站 5,000 轮。删除会立即移除问答正文，并只保留不含正文的会话标识哈希墓碑，防止浏览器旧请求或短期缓存把已删除内容重新写回；墓碑随所属实验清理。API Key、供应商私有推理、未验证流片段、系统提示词和原始供应商响应不会进入该表、通用认知决策缓存、审计正文或导出包；请勿在问题中输入秘密或个人身份信息。为处理瞬时断线和同一请求的传输级恢复，服务器还会在内存中合并进行中的相同请求，并将成功响应或稳定失败保留最多 60 秒供**同一请求标识**恢复；进程重启后，已成功持久化的同一请求标识仍直接恢复首次终态，不再次调用供应商。这与用户明确确认后使用新标识发起的计费重试不同。审计只记录结果与请求哈希、供应商、模型、语言、工具、token、失败码、调用次数和持久化状态等元数据，不记录对话或解释正文。
- “分析摘要 / Analysis summary”是解释模型生成的简短、可核验证据检查摘要，不是也不会声称是供应商的隐藏思维链。原始 `reasoning_content`、加密 thinking、签名、系统提示词和 API Key 不会返回前端；界面也不会展示隐藏推理块计数。摘要默认关闭且最终结果中默认折叠，用户可以自主选择是否请求和展开。

## 费用口径

- 界面同时显示供应商的公开输入、缓存输入和输出价格，并标明币种、地区、核验时间和官方来源。
- 运行前费用闸门使用保守上界：分档价格取最高可触发档，OpenAI 长上下文采用官方倍率，Anthropic 和 Qwen 会覆盖更高的缓存写入费率。
- 免费额度、批处理折扣、促销、资源包和账号专属折扣不会被用于放宽硬预算。
- 人民币价格按冻结的保守汇率下限折算成美元预算；该换算用于阻止超额调用，不是支付汇率或发票报价。
- 供应商、模型或价格任一项无法核验时，系统在发出请求前失败关闭，不会把未知价格当作零。

## 密钥和隐私

- 普通用户的 API Key 只绑定当前登录会话，在同源 HTTPS 后端进程内存中短时保存；它不会写入账号、SQLite、浏览器持久存储、日志、审计详情或导出包。服务每分钟主动清除过期凭据，退出登录和服务重启也会立即清除。
- 只有 `EVENTSHOCK_ADMIN_EMAIL` 指定的管理员账号可在前端明确选择“持久保存到服务器”，并且保存、替换或删除前必须重新输入当前管理员密码完成身份复验。保存时，后端使用独立主密钥和 Fernet 认证加密，把一个供应商凭据的密文与加密版本、主密钥标识、时间戳等有限元数据写入 `auth_persistent_llm_credentials`；供应商、模型、参数和 API Key 都位于加密信封内。前端和 API 只看到掩码状态，不能取回明文。该管理员可替换或删除自己的持久凭据，普通管理员角色或普通用户不能读取、创建、使用或删除它。
- 管理员持久凭据不写入浏览器持久存储、请求/访问日志、审计详情、AI 对话、实验快照、账户导出或实验导出。数据库备份可能包含密文，但不包含用于解密的独立主密钥文件。
- 静态加密主要降低“只取得 SQLite/备份、未取得主密钥”时的泄露风险，不是端到端加密或硬件 Secret Vault。应用调用供应商时必须在进程内短暂解密，因此宿主机 root、Docker 管理员、能够读取主密钥文件的运维人员、运行中的应用进程和恶意依赖仍属于信任边界。
- 普通用户切换供应商会原子替换当前会话的旧凭据，不会长期同时保存多家密钥；退出登录、凭据过期、后端重启或主动清除后必须重新填写。管理员持久凭据只有在主动替换、删除、账户删除、主密钥丢失/轮换不兼容或密文校验失败时才不再可用。
- 端点由服务器白名单固定，用户不能填写任意 Base URL，从而避免把密钥发送给未授权主机。
- 不要向外部模型发送个人身份信息、券商凭据、私人通信、受监管数据，或无权交给第三方处理的材料。

## 官方资料

- 智谱：[模型概览](https://docs.bigmodel.cn/cn/guide/start/model-overview)、[结构化输出](https://docs.bigmodel.cn/cn/guide/capabilities/struct-output)、[Web Search API](https://docs.bigmodel.cn/api-reference/工具-api/网络搜索)、[Web Search 指南](https://docs.bigmodel.cn/cn/guide/tools/web-search)、[Reader API](https://docs.bigmodel.cn/api-reference/工具-api/网页阅读)、[价格](https://bigmodel.cn/pricing)
- OpenAI：[模型](https://developers.openai.com/api/docs/models)、[结构化输出](https://developers.openai.com/api/docs/guides/structured-outputs)、[价格](https://openai.com/api/pricing/)
- Anthropic：[模型](https://platform.claude.com/docs/en/about-claude/models/overview)、[结构化输出](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)、[价格](https://platform.claude.com/docs/en/about-claude/pricing)
- Google Gemini：[API](https://ai.google.dev/api)、[结构化输出](https://ai.google.dev/gemini-api/docs/structured-output)、[价格](https://ai.google.dev/gemini-api/docs/pricing)
- DeepSeek：[模型与价格](https://api-docs.deepseek.com/quick_start/pricing/)、[JSON 输出](https://api-docs.deepseek.com/guides/json_mode/)
- 阿里云百炼：[模型](https://www.alibabacloud.com/help/en/model-studio/models)、[结构化输出](https://www.alibabacloud.com/help/en/model-studio/qwen-structured-output)、[价格](https://www.alibabacloud.com/help/en/model-studio/model-pricing)
- Moonshot / Kimi：[模型](https://platform.kimi.com/docs/models)、[K2.6 价格](https://platform.kimi.com/docs/pricing/chat-k26)、[K3 价格](https://platform.kimi.com/docs/pricing/chat-k3)

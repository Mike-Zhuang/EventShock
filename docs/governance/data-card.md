# EventShock Lab Data Card

## 数据产品

当前仓库包含三类数据：

1. 仓库内 Canonical Event Pack，包括纯合成离线测试包和 SpaceX source-backed 演示包。
2. 用户在匿名 Session 中上传的来源元数据、抽取候选 Claim、人工审核状态和冻结草稿。
3. 仿真生成的路径、订单、成交、Agent 流、trace、指标和导出 artifact。

本项目不训练基础模型，也没有训练数据集。LLM 请求用于候选事实抽取和模拟认知输出。

## SpaceX 演示包

目录：`event-packs/spacex-nasdaq100-2026-v1/`

### 来源支持的事实

- SEC S-1、S-1 生效、IPO 定价、最终招股书和交割文件。
- Nasdaq IPO 与 Nasdaq-100 方法论、公告和生效安排。
- SpaceX 投资者关系公告。
- FTSE Russell 全球与美国指数快速纳入通知。
- FCC 第二代 Starlink 授权令。
- NASA OIG 载人登月系统合同审计。
- SEC 中披露的 250 亿美元高级票据事件。

外部来源使用标题、发布者、URL、时间、来源等级、许可说明和简短人工释义。公共仓库不保存 Reuters、Nasdaq、FTSE Russell、SpaceX 或发行人文件的完整副本。

### 合成数据

- SPCX 展示价格、价差、深度和成交量路径。
- 合成广泛科技基准。
- 做市容量、订单簿状态、风险规避流和被动执行时间表。
- Agent 人群、信念、偏好、订单、成交和结果。

`market.json` 与 `benchmark.json` 均声明 `dataMode=SYNTHETIC`、`isHistoricalMarketData=false` 和 `isObserved=false`。发行价 135 美元只是官方发行事实被复用为稳定仿真参考，不是 7 月 7 日真实价格。

## 时间语义

每项外部信息需要区分：

- `eventTime`：现实事件发生时间。
- `publishedAt`：来源发布或提交时间。
- `knownAt`：仿真中首次允许看见的时间。
- `ingestedAt`：系统抓取或录入时间。

仿真可见性的唯一入口是 `knownAt`。对于只提供日期的来源，事件包采用明确标注的 UTC 日末归一化，不伪造秒级精度。

SpaceX Nasdaq-100 公告的时间来自 Nasdaq 内容和 GlobeNewswire 官方分发元数据：美国东部时间 2026 年 6 月 26 日 20:00，即 `2026-06-27T00:00:00Z`。自动测试禁止更早注入。

## 来源等级

| 等级 | 典型来源 | 使用边界 |
| --- | --- | --- |
| T1 | SEC、Nasdaq、FCC、NASA、发行人正式公告、指数提供方正式通知 | 可支持官方事实，但仍需保留原始措辞和时间 |
| T2 | Reuters 对 JPMorgan、LSEG 等具名估计的报道 | 必须写明估计者、方法缺口和 knownAt，不能升级为官方事实 |
| T3 | 一般二手分析 | 只能作为分析背景，不能单独支持核心事实 |
| T4 | 社交内容 | 只能作为传播输入，不能直接成为 FACT |
| T5 | 项目合成场景 | 只能作为模型或场景假设，必须显示 synthetic 标签 |

## 采集和转换

- Canonical Event Pack 由项目维护者人工选择来源并记录元数据。
- 用户上传的正文与元数据在任何抽取或模型调用前经过确定性安全扫描；高风险内容阻断，可复核内容需确认并在下游处理前脱敏，持久化摘要不含命中原文。
- 通过内容安全 gate 的文本进入带 delimiter 的 untrusted data 区；需要人工确认的来源使用脱敏副本，阻断内容不会进入抽取或模型。
- LLM 只能提出候选 Claim，候选始终要求人工审核。
- 原始上传文本不进入公开 Event Pack，当前实现也不把 BYOK 密钥写入 SQLite。
- 冻结 Event Pack 后，实验引用冻结 Claim 和配置。
- 仿真输出带 seed、版本和 event-log hash。

## 数据质量控制

- JSON 解析和必需文件检查。
- Claim 到 Source 的引用完整性。
- UTC 与 `knownAt` 防泄漏检查。
- 官方事实与 synthetic/estimate 分层。
- 文件 SHA-256 校验。
- 单干预场景差异检查。
- matched-seed 相等种子检查。
- 不允许把 IPO 股数自动换算为自由流通股。
- 不允许把跟踪资产规模自动换算为买入流量。

这些控制只能验证已编码约束，不能证明来源内容本身完整、无误或适合所有研究用途。

## 隐私与个人数据

设计不需要真实个人交易记录、真实投资者身份或社交账户画像。规则和 LLM Agent 都是合成原型。当前确定性扫描只覆盖已登记的凭据、支付卡/美国 SSN、邮箱和美国/中国电话号码等类别，不能替代全面 DLP、独立隐私审查、删除请求流程或隐私影响评估，因此仍不应上传敏感或受监管个人数据。

隐私合规状态：`PENDING_HUMAN_EVIDENCE`。

## 许可和再分发

- 外部页面可访问不等于允许全文再分发。
- SEC 中发行人撰写的材料不因公开提交自动成为公共领域。
- NASA、FCC 的政府原创文字通常可公开使用，但第三方材料、照片和标志可能受限。
- Nasdaq、FTSE Russell、Reuters、SpaceX 内容及市场/指数数据受各自条款约束。
- 公开演示默认只保存链接、元数据和短释义，并使用 synthetic 行情。

独立许可审查尚未完成，状态为 `PENDING_HUMAN_EVIDENCE`。

## 代表性和偏差

- SpaceX 是单一美国科技与航天发行人，不能代表全部资产、事件或市场制度。
- Agent 不含真实人口属性，但“散户、机构、做市商”等标签仍可能强化刻板印象。
- 中文和英文界面存在，实时模型的双语等价性尚未由真实用户验证。
- 合成市场路径不代表真实 SPCX 分布、深度、波动或被动流执行。
- 官方英文来源占主导，可能忽略其他地区和语言的信息环境。

## 数据保留

- Canonical Event Pack 随仓库版本保存。
- SQLite 持久化匿名会话的草稿、场景、审计和实验。
- BYOK API Key 仅在进程内存中按 TTL 保存，进程重启即丢失。
- 当前没有面向最终用户的完整数据删除、导出权和保留期管理界面。
- SQLite 备份、恢复与过期数据清理尚未通过运营演练。

## 合适用途

- 教学演示和机制探索。
- 验证 Event Pack、PIT、matched seeds 与可复现导出工作流。
- 对合成参数进行敏感性分析。
- 测试证据约束型 LLM 组件。

## 不合适用途

- 历史收益归因、真实异常收益或自由流通冲击估计。
- 实盘交易、资产配置、投资建议或监管资本计算。
- 对真实群体、机构或个人行为作判断。
- 在没有许可的情况下存储或公开行情、指数、新闻全文和社交数据。
- 使用事后来源验证先前时点的 Agent 决策。

## 待补证据

- 历史行情与订单簿许可：`PENDING_HUMAN_EVIDENCE`
- 数据源许可审查：`PENDING_HUMAN_EVIDENCE`
- 隐私影响评估：`PENDING_HUMAN_EVIDENCE`
- 双语数据质量评估：`PENDING_HUMAN_EVIDENCE`
- 真实目标用户对数据标签的理解：`PENDING_HUMAN_EVIDENCE`
- 备份、恢复和删除演练：`PENDING_HUMAN_EVIDENCE`

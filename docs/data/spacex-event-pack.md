# SpaceX Nasdaq-100 事件包

`spacex-nasdaq100-2026-v1` 是 EventShock Lab 的第一个具有可追溯来源的正式演示事件包。它把真实事件事实与合成市场机制严格分开：SEC、Nasdaq、SpaceX、FTSE Russell、FCC 和 NASA 的公开记录只负责回答“发生了什么以及何时公开”，价格路径、订单簿、资金流、Agent 行为和实验效果则全部标为合成。

## 演示目标

事件包围绕一个单变量问题展开：在 SpaceX 纳入 Nasdaq-100 的事实记录保持不变时，将合成 `marketMakerCapacity` 从 `1.0` 降至 `0.65`，会怎样改变仿真的价差、可见深度、下行风险和止损级联？

`marketMakerCapacity` 是无量纲的合成流动性深度代理，不是从 SPCX 真实订单簿估计出的历史指标。配对实验只能说明模型在所选假设下的内部差异，不能识别指数纳入的现实因果效应。

## 点时边界

Nasdaq 公告由官方 Nasdaq 页面支持，精确公开时间由 GlobeNewswire 的官方分发元数据交叉确认：

- 原始时间：2026 年 6 月 26 日 20:00，`America/New_York`
- UTC 时间：`2026-06-27T00:00:00Z`
- 仿真观察截止：`2026-07-07T13:30:00Z`

任何 cognition 或 LLM Agent 都不得在 `2026-06-27T00:00:00Z` 之前看到纳入公告。`2026-07-07T13:30:00Z` 表示正常美股开盘边界，并不是 Nasdaq 发布的精确到秒纳入时间。

合成澄清事件安排在 `2026-07-07T14:00:00Z`。未来接入 LLM cognition 时，也必须按仿真时钟过滤，不能在该时刻之前提前暴露。

## 数据分层

### T1 官方事实

- SEC S-1、S-1 生效通知、定价 FWP、最终 424B4 和 IPO 完成交割 8-K。
- Nasdaq IPO 交易公告、Nasdaq-100 方法论和正式纳入公告。
- FTSE Russell 的全球与美国指数快速纳入通知。
- SEC 中披露的 250 亿美元高级票据定价与交割。
- FCC 第二代 Starlink 授权令和 NASA OIG 载人登月系统合同审计。

### T2 具名估计

Reuters 报道的 JPMorgan 约 43 亿美元被动资金流估计仅保存在来源登记中。由于保守的 `knownAt` 晚于仿真截止时间，且事件包没有该估计的方法、区间和完整假设，它不会进入 `claims.json`、Agent 观察或校准参数。

### 合成输入

- `market.json` 中的价格、价差、深度和成交量单位。
- `benchmark.json` 中的广泛科技基准路径。
- 被动资金执行时间表、风险规避卖出流和澄清时序。
- Agent 人群、信念、偏好、订单以及仿真输出。
- `marketMakerCapacity` 的 `1.0` 与 `0.65` 参数值。

## 文件结构

| 文件 | 用途 |
| --- | --- |
| `manifest.json` | EventPackService 与前端直接加载的标题、双语摘要、来源、默认实验、机制规则和限制 |
| `event.json` | 主事件、点时边界、研究问题与事实/合成边界 |
| `timeline.json` | 具有 `knownAt`、事件时间、来源和事实类别的完整时间线 |
| `entities.json` | 发行人、证券、指数、监管机构和指数提供方实体 |
| `sources.json` | 来源层级、标题、URL、时间精度、支持的事实和许可说明 |
| `claims.json` | 前端审核和冻结工作流使用的事实、规则、背景与合成假设 |
| `market.json` | 明确标注的合成 SPCX 压力路径 |
| `benchmark.json` | 明确标注的合成广泛科技基准 |
| `instrument.json` | SPCX 官方证券事实、未知字段与仿真参考价格边界 |
| `calibration.json` | 仿真参数、干预解释、固定参数和排除的估计 |
| `defaults.json` | 默认配对实验、人工审核要求和展示策略 |
| `validation.json` | 数据完整性、点时一致性、许可边界和混杂因素检查 |
| `limitations.json` | 面向结果页和导出的结构化限制说明 |
| `checksums.json` | 除自身之外所有本地 JSON 文件的 SHA-256 校验值 |

## 前端操作流程

1. 在案例选择页选择 `SpaceX Nasdaq-100 Fast Entry: Liquidity Capacity Stress Test`。
2. 检查每条 Claim 的来源层级、`knownAt` 和合成标志。
3. 对以下四条初始 `AI_PROPOSED` 合成假设执行批准、编辑或拒绝：
   - `claim-limited-depth`
   - `claim-passive-execution`
   - `claim-risk-off`
   - `claim-clarification`
4. 只有全部待审核 Claim 均被处理、所有必需 Claim 被批准或编辑后，才能冻结事件包。
5. 使用默认配对实验运行 10 个种子；基线为 `marketMakerCapacity=1.0`，干预为 `0.65`。
6. 结果解释必须保留样本量、经验区间、模型版本、数据版本、合成标签和限制说明。

若拒绝可选的 `claim-clarification`，引擎不会注入合成澄清事件。不得把此操作解释为对真实公司信息披露行为的估计。

## 不能进行的换算

- IPO 共售出 638,888,888 股不等于自由流通股或可立即交易供给。
- Nasdaq 所称超过 8000 亿美元跟踪产品资产不等于对 SPCX 的买入需求。
- 发行价 135 美元不是 7 月 7 日真实价格。
- 官方写明的“开盘前生效”不证明被动交易全部在开盘时完成。
- 事件窗口内的价格变化不能只归因于 Nasdaq-100 纳入；FTSE Russell 纳入和债券发行均为明显混杂因素。

## 版权与数据许可

公共仓库只保存外部来源的标题、URL、时间、来源层级和简短人工释义，不保存 Reuters、Nasdaq、FTSE Russell、SpaceX 或发行人文件的完整副本。SEC 文件可公开访问并不意味着其中发行人撰写的全部内容自动进入公有领域。

NASA、FCC 等美国政府原创文字通常可以公开使用，但其中第三方材料、照片、标志和机构识别元素仍可能受到限制。任何真实 SPCX、NDX、QQQ、逐笔、订单簿或指数数据都必须先确认许可证，再决定能否进入仓库或公开导出。

## 替换为授权历史数据

只有同时满足以下条件，才能将 `marketDataMode` 从 `SYNTHETIC` 改为授权历史数据模式：

1. 具有允许当前用途、存储方式和再分发范围的数据许可证。
2. 保存数据供应商、产品名、版本、提取时间、交易所时区和企业行动处理规则。
3. 为每条数据建立 UTC 时间、原始时区与点时可用时间。
4. 单独记录 SPCX 与基准序列，禁止将估算值伪装成观测值。
5. 重新校准参数并重新生成 `validation.json` 与 `checksums.json`。
6. 继续保留原始合成包，避免历史验证和离线测试失去可复现基线。

## 验证

在满足项目 CPython 3.12.13 环境要求的 `eventshock` Conda 环境中运行：

```bash
conda run -n eventshock python -m pytest tests/backend/test_spacex_event_pack.py
```

测试会检查文件完整性、JSON 解析、来源引用、官方事实与合成输入分层、公告时间防泄漏、默认单变量干预、服务加载以及本地文件校验值。

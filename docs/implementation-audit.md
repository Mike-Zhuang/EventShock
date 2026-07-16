# EventShock Lab 蓝图实现审计

> 审计基线：`EventShock_Lab_End_to_End_Blueprint_ENGIN170E_CN.md` 与当前工作区，2026-07-15。
> 本文是代码可追溯性清单，不是发布批准、历史有效性证明或测试执行报告。测试是否在某次发布中通过，应以带日期的 CI / 本地测试产物和 `docs/governance/validation-report.md` 为准。

## 1. 状态定义

| 标记 | 含义 |
| --- | --- |
| `已实现` | 当前仓库中存在可调用的端到端代码路径，并有对应自动化测试或结构化验收点。 |
| `已实现，已有运行证据` | 除代码和自动化外，目标服务器或公网链路已有带边界的运行验收；这仍不等于安全批准、长期 SLO 或科学有效性。 |
| `已实现，待外部证据` | 代码能力存在，但真实模型、真实数据、目标用户、生产主机或人工审核证据尚未完成；不得据此提升现实世界主张。 |
| `部分实现` | 存在核心类型、函数或页面，但蓝图要求的动态编排、数据覆盖或交互仍不完整。 |
| `未实现` | 当前仓库没有该能力的可执行实现。 |
| `明确不做 / 后续` | 蓝图将其列为非目标、可选学习模块或课程后生产化方向。 |

## 2. 结论摘要

当前仓库已打通课程演示所需的核心闭环：有来源的 SpaceX Event Pack、人工 claim 审核和冻结、单变量场景、matched-seed 批量仿真、确定性订单簿和账本、有限 LLM 认知节点、分布比较、Trace Explorer、治理页面与可复现 ZIP。价格只由确定性订单簿产生，LLM 不能直接设置价格、账户或最终订单。

当前能够诚实支持的最高主张仍是“合成模型内的机制演示”。CrowdStrike 2024 与 GameStop 2021 的来源可追溯案例包已经可审核、冻结和运行，但它们只达到 `L5_CASE_AVAILABLE / PENDING_HUMAN_STUDY`，尚未形成真实市场拟合、预注册阈值或独立历史研究证据。真实 GLM 双语与 persona 质量评估、目标用户可用性与信任测试、人工红队、安全/许可证审查和生产灾难恢复演练也仍待完成。

| 能力域 | 当前判断 | 主要边界 |
| --- | --- | --- |
| 核心产品闭环 | `已实现` | 只支持一个主要标的和一次一个干预。 |
| SpaceX 旗舰 Demo | `已实现` | 事实有来源；行情、订单流、自由流通与机制参数均明确为合成。 |
| CrowdStrike / GameStop 历史案例 | `已实现，待外部证据` | 官方事实与合成机制已分层并可运行；案例可用不等于历史校准或 L5 通过。 |
| 科学内核 | `已实现` | 单标的简化现货；研究级开盘竞价与波动停牌已执行，但不是交易所完整 auction/LULD 规则，多场所机制仍未实现。 |
| 规则智能体 | `已实现` | 策略是课程级简化规则，尚未以真实订单数据校准。 |
| 智谱 LLM 接入 | `已实现，待外部证据` | 严格 JSON、BYOK、回退已实现；尚无真实供应商质量/成本/多语言评估证据。 |
| LLM 与仿真动态耦合 | `部分实现` | 按 `decisionIntervalSteps` 与 `callBudget` 预生成多轮 PIT 决策，包含届时证据、有限社交馈送和上轮记忆；同一冻结序列跨双臂和 matched seeds 复用，不做 seed-specific 内生价格实时重观察或仿真内事件触发调用。 |
| 信息网络 | `已实现` | 六类合成网络可运行；真实社交图、影响者和完整谣言—澄清研究未校准。 |
| 统计与稳健性 | `部分实现` | 单实验诊断和有界 Study coordinator 均可执行；Study 支持全因子/LHS、common seeds、8 类负对照、10 类消融、精确符号检验、family-level Holm 与探索性 rank correlation，但认知/若干移除臂是显式代理，尚无 Sobol/Morris/Bayesian design 或外部历史验证。 |
| 前端与 Human-in-the-loop | `已实现` | 主流程与 Study Workbench 可操作；Experiment 状态通过 SSE 推送变更并保留周期性 HTTP 对账，不提供高频逐订单 WebSocket。 |
| 数据与可复现 | `已实现` | ZIP/CSV/JSON/六张固定 Schema Parquet 完成；没有对象存储和长期 artifact registry。 |
| 安全与治理 | `部分实现` | 抽取前确定性内容扫描、风险分级、确认后脱敏与安全摘要已接线；认证/RBAC、完整附件解析、反病毒沙箱、全面 PII/数据主体工作流与人工安全证据未完成。 |
| 自有服务器部署 | `已实现，已有运行证据` | GitHub 两类触发的六项 CI 检查、宝塔原生 10 分钟任务/GetLogs、GitHub 拉取部署、scoped UFW、Caddy→Nginx→app、SSE access log、`site_total` 增长和目标 SHA 一致性均已在目标服务器验收；宝塔网页视觉确认、失败恢复演练、长期 SLO 与独立安全审查仍待完成。 |

## 3. 核心产品、案例与总体架构映射（蓝图第 1–7 章）

| 蓝图要求 | 状态 | 实现位置 | 自动化证据 | 边界 / 未完成项 |
| --- | --- | --- | --- | --- |
| 有来源事件包 → 人工确认 → 冻结 | `已实现` | `backend/app/service.py` 的 `EventPackService`；`frontend/src/pages/event-pack-page.tsx` | `tests/backend/test_api.py`、`test_control_plane.py`、`test_spacex_event_pack.py` | 动态上传只保存来源元数据、哈希与候选 claim，不保存完整原文。 |
| 基准 + 一个反事实变量 | `已实现` | `backend/app/schemas.py`、`backend/app/scenario_service.py`、`frontend/src/pages/scenario-builder-page.tsx` | `test_control_plane.py`、`test_api.py`、`test_simulation.py` | 多变量政策包和因子实验未提供自动编排。 |
| matched seeds 成组比较 | `已实现` | `backend/app/service.py`、`backend/app/simulation/analytics.py` | `test_api.py`、`test_simulation.py`、`test_validation_statistics.py` | UI 限定 10/25/50 对；不等于已达到外部统计功效。 |
| 比较分布而非单条路径 | `已实现` | `aggregatePairedResults`；`frontend/src/pages/results-page.tsx` | `test_simulation.py`、`frontend/src/api/normalize.test.ts` | 目前没有 seed-level scatter 的完整交互式研究工作台。 |
| 事件 → 信念 → 信息传播 → 风控 → 订单 → 成交 → 指标 Trace | `已实现` | `backend/app/simulation/engine.py`、`backend/app/export/parquet.py`、`frontend/src/pages/trace-explorer-page.tsx` | `test_simulation.py`、`test_parquet_export.py` | 代表性 trace 是模型内追踪，不是现实因果归因；LLM 可读取有限社交馈送，但其 `public_message` 尚未动态回写传播网络。 |
| 导出可复现实验包与限制 | `已实现` | `backend/app/service.py::_buildExport`、`scripts/replay-bundle.py` | `test_api.py`、`test_parquet_export.py` | Replay 证明代码内确定性，不证明历史有效性。 |
| 价格由订单簿而非 LLM 产生 | `已实现` | `backend/app/simulation/order_book.py`、`agent_protocol.py`、`agents.py` | `test_order_book.py`、`test_agent_protocol.py`、`test_simulation.py` | 无真实交易接口；这是有意的安全边界。 |
| 规则主体 + 少量 LLM 代表节点 | `已实现` | `buildPopulation`、`ExperimentService._prepareCognitiveSignals` | `test_simulation.py`、`test_cognition_service.py` | LLM 节点最多按受控数量生成；不支持数千 LLM 节点。 |
| Point-in-time 冻结数据 | `已实现` | `backend/app/information/models.py`、`engine.py`、SpaceX claims/timeline | `test_information_network.py`、`test_simulation.py`、`test_spacex_event_pack.py` | 动态来源时间依赖用户输入与人工审核，无法自动证明其现实发布时间真实。 |
| SpaceX 2026 旗舰案例 | `已实现` | `event-packs/spacex-nasdaq100-2026-v1/`、`docs/data/spacex-event-pack.md` | `test_spacex_event_pack.py` | SEC/Nasdaq 事实与合成市场严格分层；Reuters 事后估计只作元数据，未泄漏进仿真。 |
| CrowdStrike 2024 验证案例 | `已实现，待外部证据` | `event-packs/crowdstrike-outage-2024-v1/{manifest,claims}.json` | `test_historical_event_packs.py` 验证事实/合成边界、人工审核、冻结与默认 preflight | 仅为可运行的澄清时机候选案例；无 CRWD 历史行情、校准、阈值比较或真人独立研究。 |
| GameStop 2021 验证案例 | `已实现，待外部证据` | `event-packs/gamestop-meme-2021-v1/{manifest,claims}.json` | `test_historical_event_packs.py` 验证事实/合成边界、人工审核、冻结与默认 preflight | 仅为可运行的社交放大候选案例；无历史订单/社交数据校准，期权/gamma 机制也未实现。 |
| L0/L1/L2/L3 四层案例梯度 | `部分实现` | L0 合成机制测试、CrowdStrike/GameStop 历史候选案例、L3 SpaceX；`/api/v1/validation/ladder` | `test_simulation.py`、`test_historical_event_packs.py`、`test_governance.py` | L1/L2 的案例输入已存在，但历史研究结果和人工证据仍缺失，因此不能宣称相应等级通过。 |
| 科学、认知、产品控制三层隔离 | `已实现` | `backend/app/simulation/`、`cognition/`、`main.py`/`service.py` | 各模块单元测试与 API 测试 | MVP 使用单体进程和 SQLite，不是蓝图中的 PostgreSQL/Redis/Object Store 拓扑。 |
| 信任边界与系统不变量 | `已实现` | 严格 Pydantic、风险/账本、PIT store、CSP、hash chain | `test_ledger.py`、`test_agent_protocol.py`、`test_database.py`、`test_cognition.py` | 认证、组织权限与外部安全验证未完成。 |

## 4. 仿真内核与市场微观结构映射（蓝图第 8 章）

| 蓝图要求 | 状态 | 实现位置 | 自动化证据 | 边界 / 未完成项 |
| --- | --- | --- | --- | --- |
| 单调离散事件时钟与确定性优先级队列 | `已实现` | `backend/app/simulation/event_queue.py` | `test_event_queue.py` | 没有跨进程分布式事件调度。 |
| 限价订单、IOC、部分成交、撤单 | `已实现` | `order_book.py` | `test_order_book.py`、`test_ledger.py` | 订单类型集合小于真实交易所；不含隐藏单、冰山单等。 |
| 价格—时间优先 | `已实现` | `LimitOrderBook` | `test_order_book.py` | 单一撮合场所。 |
| 价格保护与未成交量 | `已实现` | `order_book.py`、`engine.py::_protectedPrice` | `test_order_book.py`、`test_simulation.py` | 实现为带 collar 的可成交限价/IOC，不是交易所完整 market-order 制度。 |
| 自成交防护和订单 ID 唯一 | `已实现` | `order_book.py`、ledger/engine 校验 | `test_order_book.py`、`test_simulation.py` | 无多账户实益拥有人识别。 |
| 做市库存偏斜和多层深度 | `已实现` | `engine.py::_refreshMarketMakerQuotes` | `test_simulation.py` | 简化函数，未按真实做市商数据校准。 |
| 交易费、现金、持仓、已实现/未实现 P&L | `已实现` | `backend/app/simulation/ledger.py` | `test_ledger.py` | 税费、清算周期、公司行动未建模。 |
| 借券、保证金、风险修改/拒绝与强平 | `已实现` | `ledger.py`、`engine.py` | `test_ledger.py`、`test_simulation.py` | 是受限代理模型，不是券商/交易所规则复刻。 |
| 现金和仓位守恒 | `已实现` | `PortfolioLedger.checkInvariants`、`engine.py::_validateLedgerInvariants` | `test_ledger.py`、`test_simulation.py` | 外生账户仍是明确的合成流动性/事件流账户。 |
| 订单/网络/市场延迟 | `部分实现` | `ScenarioRuntimeConfig`、信息传播延迟、`informationLatency` 干预 | `test_information_network.py`、`test_simulation.py` | `market.latencyMs` 进入配置但未形成完整消息往返/交易所延迟模型。 |
| 开盘集合竞价和波动停牌 | `已实现` | `engine.py::_runOpeningAuction`、`_updateMarketState` 与 `openingAuction` / `volatilityHalt` 配置 | `test_simulation.py` 覆盖开关差异、竞价成交、halt 触发与连续交易恢复语义 | 是课程研究用单价竞价和有界 HALTED gate；复牌采用连续重新报价，不复刻交易所完整 LULD bands、暂停规则或 reopening auction。 |
| 外生基本面与 risk-off 因子 | `已实现` | `engine.py::_advanceFundamental` 与合成事件流 | `test_simulation.py` | 基准路径是合成过程，不是许可的 NDX/QQQ 历史数据。 |
| 多资产、基准与跨资产撮合 | `明确不做 / 后续` | 当前只保存 benchmark 元数据并运行单资产 SPCX 订单簿 | 无 | 蓝图第一版允许单标的；异常收益与跨资产套利仅是简化代理或未实现。 |
| 独立随机流、相同 seed 重放 | `已实现` | `engine.py::_derivedSeed`、artifact hash | `test_simulation.py`、`test_api.py` | LLM 外部调用本身只有通过冻结缓存/决策产物才可重放。 |
| 事件日志、hash 与精选 trace | `已实现` | `engine.py`、export Parquet/JSONL | `test_simulation.py`、`test_parquet_export.py` | 没有全量对象存储、分区 event log 或长期 trace 索引服务。 |
| Checkpoint 与中断后续跑 | `已实现` | `database.py` 压缩持久化 checkpoint；`ExperimentService` 在每个完整 matched pair 后校验并保存，重启后从 `FAILED_RETRYABLE` 恢复 | `test_database.py`、`test_api.py::test_retryable_experiment_resumes_verified_matched_pair_checkpoint` | 只恢复与 request/Event Pack/seed 哈希匹配的完整配对和冻结认知 tape；半完成 pair 不复用，用户仍需重新触发 start，单实例没有跨节点迁移。 |
| 性能基准（5,000 agents 等） | `未实现` | 无 benchmark artifact | 无 | 当前 API 限制人口 250、步数 300，适配低内存课程服务器。 |

## 5. 规则与混合智能体映射（蓝图第 9–10 章）

### 5.1 规则智能体

| 蓝图要求 | 状态 | 实现位置 | 自动化证据 | 边界 / 未完成项 |
| --- | --- | --- | --- | --- |
| 统一 Observation / Decision / Risk 接口 | `已实现` | `backend/app/simulation/agent_protocol.py` | `test_agent_protocol.py` | 内核规则策略仍主要由函数与 `AgentType` 分支实现，并非每类都是独立 Protocol 类。 |
| 噪声、价值、动量、均值回归 | `已实现` | `backend/app/simulation/agents.py` | `test_simulation.py` | 参数是合成默认，不是经验分布校准。 |
| 做市、被动基金、机构执行 | `已实现` | `agents.py`、`engine.py` | `test_simulation.py` | 被动/机构执行是简化时序规则，未提供可选 VWAP/TWAP/POV/IS 执行器。 |
| 止损、去杠杆、强制平仓 | `已实现` | `agents.py`、`ledger.py`、`engine.py` | `test_ledger.py`、`test_simulation.py` | 风险触发是代理规则。 |
| 套利/相对价值 | `已实现` | `AgentType.ARBITRAGE` 与 `_strategyScore` | `test_simulation.py` | 单标的内使用交叉信号代理，不是真实跨资产残差交易。 |
| 人口合成与层级分布 | `部分实现` | `agents.py::buildPopulation` | `test_simulation.py` | 当前按确定性类型序列和固定参数构造，未实现 YAML 层级分布、财富分布来源与经验校准。 |
| 事件/状态驱动激活 | `已实现` | `agents.py::makeOrderIntent`、`engine.py::_activateAgents` | `test_simulation.py` | 采用有界随机激活和阈值，不是已校准的非齐次 Poisson hazard。 |
| 无事件基线、方向性和种子分布 | `已实现` | engine/analytics | `test_simulation.py` | 只证明内部行为方向，不证明真实市场拟合。 |

### 5.2 LLM / 智谱认知层

| 蓝图要求 | 状态 | 实现位置 | 自动化证据 | 边界 / 未完成项 |
| --- | --- | --- | --- | --- |
| 智谱 Chat Completions 接入 | `已实现` | `backend/app/cognition/zhipu.py` | `test_cognition.py` | 测试使用 mock transport；真实供应商可用性需运行连接测试。 |
| GLM 型号目录与前端选择 | `已实现` | `cognition/catalog.py`、`frontend/src/pages/ai-configuration-page.tsx` | `test_cognition.py`、前端测试 | 目录按 2026-07-15 官方资料静态登记；供应商变更需重新核验。 |
| `response_format: json_object` + 本地严格 Schema | `已实现` | `zhipu.py`、`cognition/models.py` | `test_cognition.py`、`test_cognition_service.py` | 智谱接口提供 JSON object，不提供服务端 JSON Schema 保证，因此本地 Pydantic 是最终边界。 |
| 完整系统提示词和不可信数据 delimiter | `已实现` | `cognition/prompts.py` | `test_cognition.py` | 提示词版本已登记；真实模型的 injection 抵抗仍需执行红队。 |
| 事件 claim 抽取、证据绑定与人工审批 | `已实现` | `CognitionService.extractEventClaims`、Event Pack API/UI | `test_cognition_service.py`、`test_control_plane.py` | 模型只提候选 claim；不会自动冻结或升级来源等级。 |
| BeliefDecision 结构、evidence ID 与 allowed action | `已实现` | `cognition/models.py`、`gateway.py` | `test_cognition.py`、`test_agent_protocol.py` | Persona/语义合理性尚无人工或模型 grader 证据。 |
| 信念到订单的确定性转换和风险限额 | `已实现` | `cognition/policy.py`、`agents.py::makeCognitiveOrderIntent`、ledger | `test_cognition.py`、`test_agent_protocol.py`、`test_simulation.py` | LLM 永远不能提交原始订单。 |
| 一次 JSON repair、重试与规则回退 | `已实现` | `cognition/zhipu.py`、`gateway.py` | `test_cognition.py`、`test_cognition_service.py` | 供应商长时间不可用时只能回退，未实现多 provider route。 |
| 不可变决策缓存 | `已实现` | `cognition/cache.py` | `test_cognition.py` | 当前是进程内缓存；重启后不保留，也没有跨 worker artifact cache。 |
| BYOK 会话密钥、TTL、遮罩和不落 SQLite | `已实现` | `cognition/config_store.py`、LLM config API/UI | `test_cognition.py`、`test_control_plane.py` | 内存不是硬件密钥库；主机、崩溃转储和运维访问仍需人工安全审查。 |
| 预算、调用数、token、fallback、latency 遥测 | `已实现` | `CognitionService`、preflight、governance UI | `test_cognition_service.py`、`test_cognition_pricing.py` | `maxCostUsd` 是调用前硬门控：按公开刊例价的最高分档和冻结保守汇率，为初次请求、JSON 修复及全部传输重试预留美元成本上界，再按供应商 token usage 结算；缺失 usage 或未知价格时失败关闭。该上界不是供应商实时账单，且不包含税费、支付手续费、折扣、套餐或账户余额。 |
| 在线关键时点动态调用 LLM | `部分实现` | `ExperimentService._prepareCognitiveSignals` 按 `decisionIntervalSteps` / `callBudget` 生成多轮 PIT 信号，engine 按 `activeFromStep` 消费 | `test_simulation.py::test_scheduled_cognitive_decisions_are_consumed_at_their_point_in_time_steps` | 调用仍在实验仿真前完成并冻结，同一序列复用于 baseline/intervention 与所有 seeds；模型不会在每个 seed 中实时重观察内生价格，也没有仿真内阈值/事件触发调用。 |
| LLM 社交发言、记忆与 follower 扩散 | `部分实现` | `_prepareCognitiveSignals`、`_socialFeed`、`Observation.social_feed` / `memory_summary` | `test_cognition.py`、`test_simulation.py` | 每轮可读取截至观察时点的最多八条证据绑定社交摘要和自身上一轮决策记忆；LLM `public_message` 尚未动态进入传播网络，馈送也不来自 seed-specific 内生主体发言。 |
| 工具白名单与有限 agent loop | `部分实现` | 提示词和 Schema 明确禁止工具，gateway 无工具调用；多轮观察由受控调度器驱动 | cognition 安全测试、scheduled-signal simulation test 与治理清单 | MVP 采用零工具、多轮有界 workflow；蓝图中的有限检索工具和仿真内自主 agent loop 未实现。零工具比越权工具更安全，但功能范围更窄。 |
| Provider-neutral gateway | `部分实现` | `cognition/gateway.py` 定义协议，当前 adapter 为 Zhipu | `test_cognition.py` | 没有第二家 provider adapter，无法在运行时进行跨 provider 比较。 |
| LLM 黄金集与混合 grader | `已实现，待外部证据` | `cognition/golden_suite.py`、`cognition/evaluation.py`、`POST /api/v1/evals/run`、AI Configuration 页面 | `test_cognition.py`、`test_cognition_service.py`、`test_control_plane.py::test_cognition_eval_distinguishes_grader_self_test_from_live_model` | 三个固定案例覆盖官方负面证据、无证据 prompt injection 和冲突证据；`CODE_GRADER_SELF_TEST` 只验证 grader 接线，`LIVE_CONFIGURED_MODEL` 才调用当前智谱配置。仓库没有真实 GLM 运行、model grader 或人工盲评证据。 |

## 6. 信息、数据与 Event Pack 映射（蓝图第 11–13 章）

| 蓝图要求 | 状态 | 实现位置 | 自动化证据 | 边界 / 未完成项 |
| --- | --- | --- | --- | --- |
| event/published/known/ingested 四时间与未来泄漏阻止 | `已实现` | `backend/app/information/models.py` | `test_information_network.py`、`test_simulation.py` | 用户输入时间的现实真实性仍依赖来源审核。 |
| Fact/estimate/opinion/rumor/correction 等类型与来源层级 | `已实现` | `information/models.py`、SpaceX pack | `test_information_network.py`、`test_spacex_event_pack.py` | 动态 Event Pack 的来源等级主要依赖用户提供的 sourceType。 |
| ER、WS、BA、SBM、Echo Chamber、Core-Periphery | `已实现` | `information/network.py` | `test_information_network.py` | 图是合成网络，不代表真实投资者联系。 |
| 可信度、同质性、失真、传播延迟、覆盖率 | `已实现` | `InformationNetwork.propagate` | `test_information_network.py` | 传播参数未用真实社交数据校准。 |
| 谣言—澄清与更正覆盖 | `部分实现` | 网络层支持 rumor/correction；engine 有 fact/clarification 事件 | `test_information_network.py`、`test_simulation.py` | 主实验只完整传播风险信息；澄清主要改变情绪/时序，尚未形成对称的多节点 belief correction 研究。 |
| 公司沟通代理 | `未实现` | 无独立 communication agent | 无 | 可用 clarification claim 代理时序，但不具备独立策略、审批和消息版本。 |
| canonical Event Pack 完整文件、校验和与血缘 | `已实现` | `event-packs/spacex-nasdaq100-2026-v1/`、`crowdstrike-outage-2024-v1/`、`gamestop-meme-2021-v1/` | `test_spacex_event_pack.py`、`test_historical_event_packs.py` | 使用 JSON 而非示例中的 YAML 不影响语义；历史案例为精简 canonical 包，schema registry 仍是代码内契约。 |
| 来源哈希、许可/合成标签、PIT 截止 | `已实现` | 三个来源包的 manifests/claims；preflight/export | `test_spacex_event_pack.py`、`test_historical_event_packs.py`、`test_api.py` | 部分历史来源是 link-only 且未捕获内容哈希；公开再分发的许可证结论必须人工确认，系统不自动给法律意见。 |
| Claim graph | `部分实现` | claims 有 source IDs、机制映射和 correction 引用 | `test_spacex_event_pack.py` | 没有通用图实体/边 API 和可视化 claim graph 编辑器。 |
| 上传来源最小化与原文不落盘 | `已实现` | Event Pack create/extract、SQLite manifest | `test_control_plane.py` | 候选 claim 片段会保存供人工审核；用户不应上传敏感信息。 |
| 上传内容安全、恶意内容与 PII 初筛 | `部分实现` | `backend/app/security/content.py`、Event Pack create/re-extract 的抽取前 gate、Event Pack Studio 安全摘要 | `test_content_security.py`、`test_control_plane.py` | 可确定性识别无效 UTF-8/二进制特征、控制字符、活动脚本/命令、prompt injection、凭据和若干 PII；高风险阻断，中低风险需确认并脱敏。仍无 Office/PDF/压缩包解析、反病毒沙箱、OCR、全面 DLP/PII 或数据主体流程。 |
| 不训练基础 LLM | `已实现` | 仓库没有训练 pipeline，采用 prompt/gateway/rules | 架构和依赖可检查 | 符合蓝图决策。 |
| 可选分类器、surrogate、RL 做市等学习模块 | `明确不做 / 后续` | 无 | 无 | 只有在评估证明需要后再建设。 |

## 7. 校准、验证、实验与指标映射（蓝图第 14–16 章）

| 蓝图要求 | 状态 | 实现位置 | 自动化证据 | 边界 / 未完成项 |
| --- | --- | --- | --- | --- |
| L0–L8 验证阶梯与下层门禁 | `已实现` | `backend/app/validation/ladder.py`、validation API/governance UI | `test_validation_statistics.py`、`test_control_plane.py` | CrowdStrike/GameStop 的 `L5_CASE_AVAILABLE / PENDING_HUMAN_STUDY` 是案例元数据，不是 L5 `PASS` 证据；L5/L7/L8 仍需人工或外部 artifact。 |
| Model Development / System / Data / Limitations 文档 | `已实现` | `docs/governance/`、`docs/adr/` | `test_governance.py` 检查清单结构 | 文档不能代替独立挑战或批准签名。 |
| Method of Simulated Moments 校准 | `未实现` | SpaceX `calibration.json` 仅记录合成参数和状态 | `test_spacex_event_pack.py` 验证其不冒充历史校准 | 无真实 moments、优化器、参数不确定性或 holdout 结果。 |
| 微观结构历史拟合 | `未实现` | 无许可 tick/order-book 数据 | 无 | spread/depth/arrival/cancel/impact 目前没有真实误差阈值。 |
| 历史事件研究 AR/CAR | `未实现` | 无历史 market series pipeline | 无 | 结果不得称为 CrowdStrike/GameStop/SpaceX 历史拟合。 |
| 相同 baseline 自对照 | `已实现` | paired engine/analytics | `test_simulation.py` | 这是代码负对照，不是完整研究负对照套件。 |
| 配对差异、经验区间、bootstrap 95%、效应量、方向一致率、尾概率 | `已实现` | `simulation/analytics.py`、`validation/statistics.py` | `test_simulation.py`、`test_validation_statistics.py` | 小样本 Demo 区间不能被误读为现实概率。 |
| 顺序停止规则 | `已实现` | `StoppingRule`、`service.py::_stoppingDecision` | `test_api.py` | 以 CI 半宽为停止信号；尚未实现正式 minimum effect/power 设计。 |
| Holm 多重比较 | `已实现` | 单实验 `service.py::_buildAnalysisDiagnostics` 与 Study `coordinator.py::_holmFamilies` 均调用 `holmBonferroni` | `test_api.py`、`test_validation_statistics.py`、`test_study_coordinator.py` | 校正各次运行中预注册的 family；不会自动把多个独立 Study 合并为一个全局假设族。 |
| Rank-correlation 敏感性 | `已实现` | 单实验两水平局部筛查；Study coordinator 对全因子/LHS 单元运行 `rankCorrelationSensitivity` 并标记证据依据 | `test_api.py`、`test_validation_statistics.py`、`test_study_coordinator.py` | 仍是探索性 rank/方差重要性代理；没有 Morris/Sobol indices、response surface 或真实参数后验。 |
| 负对照与 knockout | `已实现` | 单实验 identical-seed self-control/参数恢复 knockout；Study 自动纳入蓝图列出的 8 类负对照 | `test_api.py`、`test_validation_statistics.py`、`test_study_coordinator.py`、`test_study_api.py` | 部分控制通过合成事件或最近可执行机制表达；均为模型内部诊断，不是现实因果证据。 |
| 规则/LLM/混合消融与模型比较 | `部分实现` | Study 自动编排 10 类消融臂并输出逐臂分析与机制语义 | `test_study_coordinator.py`、`test_study_api.py` | RULE_ONLY/HYBRID/LLM-heavy/fixed-decision 臂使用冻结认知 tape，不调用实时 Provider；若干 subsystem removal 是 `BOUNDED_EXECUTABLE_PROXY`，不能称为字面完整移除或真实模型质量对比。 |
| 因子实验、LHS、Sobol、Bayesian design | `部分实现` | `backend/app/study/design.py`、`coordinator.py`、Study API/UI 支持全因子和 Latin hypercube | `test_study_coordinator.py`、`test_study_api.py`、Study 前端测试 | 设计最多 16 cells、2–4 matched seeds，并受总 runs/work units 上限约束；Sobol、Morris、Bayesian design、并行/可恢复 Study worker 尚未实现。 |
| 17 个核心风险/流动性/网络/账本/LLM 运行指标 | `已实现` | `simulation/analytics.py::METRIC_KEYS`、结果页 | `test_simulation.py` | 覆盖面小于蓝图完整指标字典。 |
| VaR/ES、Amihud、Kyle、取消率、fill rate、queue time、wealth Gini 等完整指标 | `部分实现` | Parquet schema 预留部分列，核心 run metrics 未全部计算 | Parquet 测试只证明类型/可查询 | 未计算的预留列可能为 null；不能把稳定 schema 当成已计算指标。 |
| Agent 类型流量与 P&L | `已实现` | engine/analytics/results/Parquet | `test_simulation.py`、`test_parquet_export.py` | 未实现完整 risk-adjusted P&L、tracking error、spread revenue 分解。 |
| 自动自然语言报告 | `已实现` | `service.py::_buildNarrativeReport` | `test_api.py` | 使用确定性双语模板而不是 LLM；这是更可控的 MVP，内容仅覆盖已计算指标。 |
| 独立 challenge、专家审批 | `已实现，待外部证据` | 治理模板与 release gate | `test_governance.py` 保证无证据时不误报通过 | 需要不同成员/导师实际签署 artifact。 |

## 8. 前端与 Human-in-the-loop 映射（蓝图第 17 章）

| 蓝图要求 | 状态 | 实现位置 | 自动化证据 | 边界 / 未完成项 |
| --- | --- | --- | --- | --- |
| 默认英文、完整中英文切换 | `已实现` | `frontend/src/i18n.tsx`、`app.tsx` | `frontend/src/i18n.test.tsx`、`app.test.tsx` | GLM 实际中英文行为仍需真人评估。 |
| Case Library 与用途/限制 | `已实现` | `case-library-page.tsx`、`EventPackService.listCases` | `app.test.tsx`、`test_historical_event_packs.py` | SpaceX 为旗舰样本外 Demo；CrowdStrike/GameStop 仅标为历史验证候选案例，不能解读为已通过历史研究。 |
| Event Pack Studio：来源、内容安全摘要、claim 状态、审核、冻结 | `已实现` | `event-pack-page.tsx`、upload modal、`security/content.py` | 前端测试、`test_content_security.py` 与 API tests | 安全摘要只显示分类码/数量/确认状态，不回显命中原文；Claim graph 仍以列表/时间线为主。 |
| AI Configuration：API Key、型号、thinking、token、连接测试、清除 | `已实现` | `ai-configuration-page.tsx` | API normalize/tests、backend cognition tests | Key 只保存在服务端内存；刷新会话配置可见但不能取回原 key。 |
| 七步场景信息：Event/Facts/Market/Population/Network/Intervention/Review | `已实现` | `scenario-builder-page.tsx` 的七步锚点导航 + preflight | `app.test.tsx`、API tests | 七步已集中在一个页面，但仍是锚点式长表单而非逐步向导；高级参数来源/敏感性没有逐字段动态证据卡。 |
| 会话 Scenario 库：保存、更新、克隆、diff、冻结、删除 | `已实现` | `scenario-builder-page.tsx`、`frontend/src/api/client.ts`、`scenario_service.py` | `test_control_plane.py::test_scenario_crud_diff_freeze_and_audit_chain` | 当前前端代码已调用全部接口并禁止覆盖/删除冻结记录；尚无覆盖这些按钮操作的前端交互测试。 |
| 七类单变量干预和即时 diff | `已实现` | Scenario Builder、schemas、preflight | `test_api.py`、`test_simulation.py` | 不支持多个干预同时归因。 |
| Preflight：PIT、许可、版本、成本、重复、限制、确认 | `已实现` | `preflight-page.tsx`、`EventPackService.validateScenario` | `test_api.py`、`test_control_plane.py` | 许可结论仍需人工复核；LLM 成本使用可审计的公开刊例价上界，不冒充供应商实时美元账单。 |
| Run Center：排队、SSE 进度、取消、断点恢复、历史 | `已实现` | `run-center-page.tsx`、workflow context、`GET /experiments/{id}/events` | `test_api.py`、前端 API 测试 | SSE 只在公共实验状态变化时发送快照，10 秒 heartbeat/300 秒窗口并保留周期性 HTTP 对账；不是逐订单流，也无暂停播放或速率控制。 |
| Experiment Compare：卡片、分布、paired delta、路径、agent 流 | `已实现` | `results-page.tsx` | normalize tests、backend simulation tests | 机制 waterfall、完整 paired scatter 与 Study 级对比仍有限。 |
| 逐实验敏感性/负对照/knockout/Holm 结果 | `已实现` | `results-page.tsx` 的 analysis diagnostics 区域 | `test_api.py`、frontend normalize tests | 展示的是本次 Experiment 的模型内部诊断；扩展消融或无诊断 artifact 时仍应显示 `NOT_EVALUATED` / `NOT_RUN`，且不代表外部验证。 |
| Study Workbench：预注册、全因子/LHS、资源预览、执行、结果与历史 | `已实现` | `study-workbench-page.tsx`、Study API/service/coordinator | `study-workbench-page.test.tsx`、`test_study_api.py`、`test_study_coordinator.py` | 同步执行且规模受限；认知 tape 与若干消融是显式代理，UI 固定显示 historical validity 未建立。 |
| Trace Explorer 可展开来源/agent/risk/order/trade/metric | `已实现` | `trace-explorer-page.tsx` | simulation/API/normalize tests | 精选 trace，不是全量交互式 DAG；贡献没有唯一因果分解。 |
| Validation & Governance | `已实现` | `governance-page.tsx` | governance/control-plane tests | 人工证据、红队运行、真实 eval 未完成时页面保持 blocked/pending。 |
| Export / Reproduce | `已实现` | `export-history-page.tsx` | `test_api.py`、`test_parquet_export.py` | 没有云端 artifact 历史或签名下载 URL。 |
| Human-AI 决策地图和限制 | `已实现` | governance page、全局 footer、结果/导出文案 | `app.test.tsx` | 报告发布审批尚无账户/签名流程。 |
| 键盘、skip link、ARIA、移动 focus trap、暗色/高对比 | `已实现` | `app.tsx`、`styles.css`、common components | `app.test.tsx` | 未附 WCAG 自动扫描和屏幕阅读器真人证据；动画关闭偏好未完整实现。 |
| 目标用户信任测试七问 | `已实现，待外部证据` | UI 已暴露回答所需信息；用户研究模板见蓝图/治理文档 | 无真人测试 artifact | 不能声称陌生用户已正确区分预测/情景、事实/估计和区间。 |

## 9. API、存储、工程与部署映射（蓝图第 18–20 章）

| 蓝图要求 | 状态 | 实现位置 | 自动化证据 | 边界 / 未完成项 |
| --- | --- | --- | --- | --- |
| Event Pack REST endpoints | `已实现` | `backend/app/main.py` | `test_api.py`、`test_control_plane.py` | 使用 `/api/v1/...` 前缀。 |
| Scenario CRUD/clone/freeze/diff/validate | `已实现` | `main.py`、`scenario_service.py`、`scenario-builder-page.tsx` | `test_control_plane.py::test_scenario_crud_diff_freeze_and_audit_chain` | 后端与前端会话 Scenario 库均已接线；前端按钮级交互测试仍待补充。 |
| Experiment create/start/cancel/status/results/runs/metrics/traces/export | `已实现` | `main.py`、`service.py` | `test_api.py` | 独立子资源都只允许读取 `COMPLETED` 且未 invalidated 的当前 Session 实验。 |
| Study presets/design-preview/run/list/detail | `已实现` | `main.py`、`backend/app/study/` | `test_study_api.py`、`test_study_coordinator.py` | Study run 当前是单进程同步有界执行，不提供取消、SSE、checkpoint 或跨 worker 调度。 |
| Model/prompt/config/telemetry/eval endpoints | `已实现，待外部证据` | `main.py`、`cognition/`、AI Configuration 页面 | cognition/control-plane tests | `GET /api/v1/evals` 汇总状态；`POST /api/v1/evals/run` 明确区分不计费的 `CODE_GRADER_SELF_TEST` 与需会话密钥的 `LIVE_CONFIGURED_MODEL`。测试未调用真实智谱服务，真人/model grader 仍缺失。 |
| Governance inventory/red-team/release-gate/validation ladder | `已实现` | `main.py`、`governance/` | `test_governance.py`、`test_control_plane.py` | 红队 definition 不等于运行证据。 |
| 写 API idempotency | `部分实现` | experiment create/start 使用 key 与 DB 唯一约束 | `test_api.py` | Event Pack、claim review、Scenario 等其他写入并非全部要求 Idempotency-Key。 |
| 任务状态机、checkpoint 与后台 worker | `已实现` | SQLite experiment state/压缩 checkpoint + 单 `ThreadPoolExecutor` | `test_database.py`、`test_api.py` | Experiment 可恢复完整 matched pairs；Study 仍同步执行，且没有 Redis/Celery worker pool。 |
| SSE/WebSocket 实时事件 | `已实现` | `GET /api/v1/experiments/{id}/events`、前端 stream parser/workflow | `test_api.py` 与前端 API 测试 | SSE 发送变更后的公共 experiment 快照与 heartbeat，并在 terminal 状态关闭；不是全事件日志/逐订单 WebSocket，反向代理必须关闭该路径缓冲。 |
| SQLite 会话/场景/审计/实验状态 | `已实现` | `backend/app/database.py` | `test_database.py` | 无用户/组织/项目实体，也不是 PostgreSQL 多租户生产拓扑。 |
| 哈希链审计和篡改检测 | `已实现` | `Database.appendAuditEvent` / `verifyAuditChain` | `test_database.py`、`test_control_plane.py` | 同一应用数据库管理员仍有底层写权限；没有外部 WORM 日志。 |
| 固定 Schema Parquet | `已实现` | `backend/app/export/parquet.py` | `test_parquet_export.py` | 在导出时内存生成；无 S3 分区数据湖。 |
| ZIP：manifest/scenarios/Event Pack/source hashes/seeds/model versions/traces/报告 | `已实现` | `service.py::_buildExport` | `test_api.py` | 不含原始上传全文或 API Key，符合最小化原则。 |
| CPython 3.12.13 和依赖锁 | `已实现` | `.python-version`、`environment.yml`、`pyproject.toml`、locks、Dockerfile、CI | CI 配置本身 | 某次发布仍需实际 CI artifact。 |
| Ruff/Pytest/前端 test/build/container gates | `已实现` | `.github/workflows/ci.yml` | 工作流定义 | 没有覆盖率阈值、E2E 浏览器 CI、镜像漏洞/许可证扫描。 |
| 单实验 artifact invalidation | `已实现` | `POST /api/v1/experiments/{id}/invalidate`、SQLite invalidation 字段、Results 页面操作与结果读取/导出 gate、审计事件 | `test_api.py`、`test_database.py`、`frontend/src/api/normalize.test.ts` | 只允许当前 Session 对单个已完成实验操作；保留底层 result 供取证但不再返回为有效结果。Results 弹窗尚无独立按钮级前端交互测试；按模型/数据/版本批量查找和失效仍是控制缺口。 |
| ADR | `已实现` | `docs/adr/0001-0011` | 治理测试检查部分引用 | 重大未来变更仍应新增 ADR。 |
| Docker 非 root、只读 FS、资源限制、健康检查 | `已实现` | `Dockerfile`、`compose.yml` | CI container build gate | 运行安全性需在生产主机实测。 |
| GitHub→宝塔→自有服务器拉取式部署 | `已实现，已有运行证据` | `sync-from-github.sh`、`deploy-server.sh`、宝塔任务/站点注册器、Caddy/Compose 与部署指南 | 214 项后端测试、部署 shell 测试、两类 GitHub CI 共 6 个成功检查、宝塔原生任务/GetLogs、目标主机健康与流量观测 | implementation commit 已先经 GitHub CI，再由宝塔任务匿名拉取；本地/GitHub/sync state/current release/健康 SHA 一致。真实 SSE 写入 Nginx access log，`site_total` 随公网请求增长，外部 18080 不可达。尚无正式失败恢复演练、长期运行数据或宝塔网页截图。 |
| 请求限制、安全响应头、rate limit、稳定错误码 | `已实现` | Caddyfile、FastAPI middleware、`rate_limit.py` | `test_rate_limit.py`、`test_api.py` | rate limit 是单进程内存状态；多副本需要共享限流器。 |
| OpenTelemetry traces/metrics/structured logging | `部分实现` | `backend/app/observability.py`、`GET /api/v1/system/metrics`、HTTP trace ID、LLM telemetry、Docker JSON log | `test_api.py`、cognition tests | 有不携带 URL/正文/session/credential 标签的有界聚合指标，但无 OTEL collector、Prometheus、集中式 dashboard、告警或端到端 spans。 |
| SLO 与真实性能/成本基准 | `部分实现` | `/api/v1/system/metrics` 返回 API 延迟/错误、队列、存储、认知汇总和显式标记的 SLO targets | `test_api.py` 检查 `TARGETS_NOT_PRODUCTION_EVIDENCE` | 目标值与当前进程快照不是生产可用性、容量或真实 LLM 成本证据；仍需在标明硬件/配置的环境做持续测量。 |
| 备份、PITR、对象版本、IaC、恢复演练 | `部分实现` | 每次发布前使用 SQLite online backup 原子生成一致性备份并保留 3 份；不可变代码/镜像保留与回滚路径有脚本 | deployment scripts tests；无真人演练证据 | 仍无自动异地备份、连续 PITR、完整 IaC 或具名恢复演练 artifact；代码回滚不会自动覆盖可能已有新写入的数据库。 |
| 现场 run + 预计算 ensemble + 离线视频/截图 + reset | `部分实现` | 现场 run 和可导出结果可用 | API lifecycle test | 固定预计算 ensemble、离线视频、静态报告包和一键 reset 尚未作为版本化 Demo artifact 提交。 |

## 10. 安全、责任 AI 与治理映射（蓝图第 21 章）

| 蓝图要求 | 状态 | 实现位置 | 自动化证据 | 边界 / 未完成项 |
| --- | --- | --- | --- | --- |
| Prompt injection 数据/指令隔离 | `已实现` | 抽取前 `security/content.py` gate、`cognition/prompts.py` delimiter、gateway/schema | `test_content_security.py`、`test_cognition.py`、`test_control_plane.py` | 确定性模式不能覆盖所有语义变体；真实 GLM 与复杂附件仍需红队执行证据。 |
| Excessive agency 控制 | `已实现` | LLM 无交易/账本/文件/网络工具；Event Pack 人工冻结 | cognition/agent protocol/API tests | 报告发布没有账户级审批流。 |
| 金融安全免责声明和主张边界 | `已实现` | README、前端 footer/results/governance/export | frontend/API tests | 仍需目标用户理解测试，不能只靠文案。 |
| 模型与关键组件清单 | `已实现` | `backend/app/governance/registry.py` | `test_governance.py` | owner/approval 是治理字段，真实人员签字仍待完成。 |
| 第三方登记、系统卡、数据卡、威胁模型、限制 | `已实现` | `docs/governance/` | `test_governance.py` | 法律、安全与供应商条款需要人工定期审核。 |
| Model/prompt/schema/version change policy | `部分实现` | component/prompt/engine/schema 版本和 ADR | tests verify current contracts | 无自动 comparability migration、变更审批 UI 或旧 artifact 批量重验证。 |
| 偏差与公平控制 | `部分实现` | 参数化合成 persona，不使用真实受保护属性；治理文档 | cognition schemas/tests | 无跨语言/persona 公平评估集与真人 blind review。 |
| 隐私：最少收集、无真实交易、原文不落盘、PII/Secret 初筛 | `部分实现` | Event Pack service、`security/content.py`、BYOK store、data card | `test_content_security.py`、`test_control_plane.py`、`test_cognition.py` | 扫描只覆盖已登记类别；无全面 DLP、删除请求、数据主体流程、隐私影响评估和硬件 secret vault。 |
| 红队攻击注册表 | `已实现` | `governance/redteam.py` | `test_governance.py` | 当前 API 明确把全部用例标为 `NOT_RUN`，直到附可核验证据。 |
| 发布门与人工证据类型隔离 | `已实现` | `governance/release_gate.py` | `test_governance.py`、`test_control_plane.py` | 当前 release gate 正确保持 blocked；不妨碍受限课程 Demo。 |
| Incident response 与单实验 invalidation | `部分实现` | `docs/governance/incident-response.md`、单实验 invalidation API/DB/audit gate | `test_api.py`、`test_database.py` | 单实验结果可保留证据并阻断后续使用；按版本/时间/模型批量查找与 invalidation、通知系统和具名演练仍未完成。 |
| OAuth/OIDC、organization RBAC、object authorization | `未实现` | 匿名浏览器 session ID 仅用于隔离 | 会话隔离 API tests | Session ID 不是身份认证；不应承载私有生产数据。 |
| CSRF/CORS、签名导出 URL、presigned upload | `部分实现` | 同源部署、CSP、无跨域公开 API | API tests | 无账号/CSRF token、对象存储 presigned URL 或短时签名下载。 |

## 11. 团队、课程、用户研究与 Demo 映射（蓝图第 22–30 章）

| 蓝图要求 | 状态 | 实现位置 | 自动化/人工证据 | 边界 / 未完成项 |
| --- | --- | --- | --- | --- |
| 五人角色、RACI、PM 轮换、决策权 | `已实现，待外部证据` | 蓝图与团队课程材料 | 需团队记录 | 仓库不能证明实际轮换、贡献与决策已按计划执行。 |
| Issue/PR/DoR/DoD/AI 协作模板 | `部分实现` | `AGENTS.md`、蓝图附录、Git 文档 | Git 历史/PR 才是证据 | 当前未见完整 issue/PR 模板和连续 AI 协作期刊 artifact。 |
| Gate 0–7：章程到混合认知 | `部分实现` | 产品、数据、内核、网络、LLM 代码已覆盖主要交付 | 自动测试映射见上文 | 用户问题证据与人工批准不可由代码替代。 |
| Gate 8：校准与历史验证 | `部分实现，待外部证据` | CrowdStrike/GameStop canonical 候选案例包与人工审核/preflight 路径 | `test_historical_event_packs.py` | 仅达到 `L5_CASE_AVAILABLE / PENDING_HUMAN_STUDY`；真实行情、预注册阈值、校准 pipeline 与独立研究结果仍是最大科学缺口。 |
| Gate 9：实验编排与统计 | `部分实现` | 单实验配对编排与有界 Study coordinator；全因子/LHS、8 类控制、10 类消融、sign test、Holm 和探索性敏感性均有 artifact | simulation/API/statistics/Study tests | Study 中认知与若干 subsystem removal 是显式代理；Sobol/Morris/Bayesian design、真实历史输入与独立验证仍缺失。 |
| Gate 10：前端与 HAI | `已实现，待外部证据` | 十一个可操作页面、SSE Run Center、Study Workbench 与双语 UI | 前端测试 | 仍需目标用户任务测试。 |
| Gate 11：安全与责任 AI | `部分实现` | 控制、文档、inventory、red-team definitions、release gate | governance tests | 人工红队、安全/许可审查仍 pending。 |
| Gate 12：生产部署与可观测 | `部分实现` | GitHub 拉取式发布、宝塔原生任务/日志、scoped UFW、Caddy→Nginx→app 站点统计、部署前 SQLite backup 与 `/api/v1/system/metrics` | deployment/API tests + 目标服务器的 TLS、SHA、原生日志、真实 SSE/access log 与 `site_total` 运行证据 | 单机链路已现场验收；仍无集中式 OTEL/告警、宝塔网页视觉证据、备份恢复演练或长期 SLO。 |
| Gate 13：真实用户验证 | `未实现` | 无访谈/可用性/信任测试结果 | 无 | 不得声称“陌生用户无需指导即可完成”已经验证。 |
| Gate 14：旗舰研究与 Demo Day | `部分实现` | SpaceX case、live experiment、results/trace/export | 可执行系统 + 待生成 Demo artifact | 预计算 ensemble、五分钟彩排、视频后备和人工审核结果未存档。 |
| Gate 15：课程后生产化 | `明确不做 / 后续` | 没有多租户 SaaS 基础设施 | 无 | 需要认证、Postgres/对象存储、worker pool、OTEL、合规和运维团队。 |
| Project Proposal / Checkpoint 1 一页计划 | `已实现，待外部证据` | 课程外部文档与已部署产品目标 | 需团队提交记录 | 仓库只提供技术成果，不能证明课程平台已收件。 |
| Checkpoint 2 Human-AI Interaction Map | `已实现` | Governance 页面和蓝图 17.9 | UI 可检查 | 需课程要求格式的最终提交。 |
| Checkpoint 3 Responsible AI Check | `已实现，待外部证据` | `docs/governance/responsible-ai-check.md` | 需团队审阅/签字 | 文档明确披露 pending 项。 |
| 用户发现访谈、概念测试、任务可用性、信任校准 | `未实现` | 只有蓝图模板 | 无 | 必须由真实受访者完成，AI 不得伪造。 |
| Demo 五分钟点击链路 | `已实现` | Cases → Event Pack → AI → Scenario → Preflight → Run → Results → Trace → Governance → Export | 可通过浏览器手动验收 | 演示可靠性后备材料尚不完整。 |

## 12. 当前最重要的未完成闭环

这些项目按“会改变系统可声称能力的程度”排序，而不是按代码量排序：

1. **历史与校准证据**：以已经可运行的 CrowdStrike 和 GameStop canonical Event Pack 为输入，取得许可明确的市场数据，预注册 moments/阈值并执行独立历史研究。两包当前只有 `L5_CASE_AVAILABLE / PENDING_HUMAN_STUDY`；完成前最高主张不得超过机制演示。
2. **真实 LLM 评估**：使用已提交的三例 golden/攻击集和 `LIVE_CONFIGURED_MODEL` 路径，扩展中英文/persona 扰动并实际运行目标 GLM 型号；保留请求版本、模型、输出、grader 和人工盲评证据。`CODE_GRADER_SELF_TEST` 或 Schema 通过率不能替代语义质量。
3. **动态认知耦合**：现有多轮 PIT 序列已接入时点证据、有限社交馈送和上一轮记忆；若研究问题需要更强耦合，下一步是 seed-specific 内生市场重观察、阈值/事件触发更新，以及让经审核的 `public_message` 进入传播。每次决策仍必须缓存、版本化并经过确定性风险层。
4. **从有界代理 Study 到验证型研究**：预注册 Study、全因子/LHS、8 类负对照、10 类消融、common seeds、Holm 与探索性敏感性已有 artifact，但认知臂使用冻结 tape，若干移除臂是最近可执行代理，且 `historicalValidityEstablished` 永远为 false。下一步是实现字面 subsystem removal/真实 provider 对比、Sobol/Morris 等全局敏感性，并用许可明确的历史数据与独立研究证据提升主张。
5. **真实用户证据**：由目标分析师/学生完成任务测试与七个信任问题；记录成功率、时间、误读和修复。没有这一证据不能宣称“陌生用户可独立完成”。
6. **生产安全与运维证据**：完成人工红队、许可证审查、TLS/日志/内存密钥检查、SQLite 异地备份与恢复演练，并补齐按版本/模型/时间窗口批量 invalidation；如承载私有数据，再增加身份认证、组织 RBAC、对象授权和完整 PII/数据主体工作流。
7. **市场制度和性能边界**：只有在产品主张需要时，再实现真正的 auction/halt/latency 状态机、多资产或大规模 worker；当前单资产课程服务器约束必须继续公开。

## 13. 可接受的当前发布标签

当前实现适合标为：

> **Controlled educational demo / synthetic mechanism laboratory**
> 受控教学演示 / 合成机制实验室

当前不应标为：

- 真实世界价格预测；
- 投资建议或自动交易系统；
- 已通过历史校准的风险模型；
- 已完成独立模型验证或生产安全认证；
- 可存储私有金融数据的多租户生产 SaaS。

只要上述边界继续同时出现在首页、Preflight、结果、导出和治理页面，当前仓库可以诚实地展示一个功能完整的课程级核心闭环，而不会把“代码已实现”混同为“科学或生产证据已完成”。

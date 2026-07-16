# 历史验证 Event Pack：CrowdStrike 2024 与 GameStop 2021

## 定位

这两个 Event Pack 用来执行蓝图 L5“历史事件响应”层的验证实验，但“案例可运行”不等于“验证已经通过”。仓库尚未附上经人类批准的历史容差、独立行情授权、校准结果或验收签字，因此 manifest 中只声明 `L5_CASE_AVAILABLE`，并将经验校准状态保持为 `PENDING_HUMAN_STUDY`。

两个案例均采用同一数据边界：

- 官方事实层只保存来源元数据与短篇幅转述，不复制原始全文；
- 历史价格、逐笔、报价、订单簿、消息、身份和账户级数据不进入仓库；
- 市场路径、Agent 信念、网络传播、订单、成交和干预效果全部是合成变量；
- 所有候选事实和合成假设初始状态均为 `AI_PROPOSED`，必须由用户逐条批准、编辑或拒绝后才能冻结；
- 配对实验只能解释为模型内部机制对比，不能解释成历史因果效应、预测或投资建议。

## CrowdStrike Channel File 291（2024）

目录：`event-packs/crowdstrike-outage-2024-v1/`

默认实验只改变 `clarificationDelay`：基线为 `1.0`，干预为 `2.5`。该参数是仿真器中“经核验信息到达”的无量纲延迟倍数，不是对 CrowdStrike 实际披露速度的统计估计。

核验过的主要官方来源：

- [CrowdStrike Form 8-K（SEC）](https://www.sec.gov/Archives/edgar/data/1535527/000110465924081571/tm2419936d1_8k.htm)：披露 04:09 UTC 发布更新、05:27 UTC 回滚，且事件并非网络攻击；
- [CrowdStrike 致客户与合作伙伴说明](https://www.crowdstrike.com/en-us/blog/to-our-customers-and-partners/)：说明 Windows 内容更新缺陷、Mac/Linux 不受影响，以及官方恢复沟通边界；
- [CrowdStrike 初步事后审查](https://www.crowdstrike.com/en-us/blog/falcon-content-update-preliminary-post-incident-report/)：限定受影响的传感器版本与在线时间窗口；
- [Microsoft 官方故障说明](https://blogs.microsoft.com/blog/2024/07/20/helping-our-customers-through-the-crowdstrike-outage/)：给出 850 万台 Windows 设备的归因估计；该数值只作背景，不映射为收入、估值或订单流；
- [CrowdStrike 根因分析公告](https://www.crowdstrike.com/en-us/blog/channel-file-291-rca-available/)与[官方执行摘要](https://www.crowdstrike.com/wp-content/uploads/2024/08/Executive-Summary_Root-Cause-Analysis_Channel-File-291.pdf)：补充输入字段不匹配、越界读取与恢复进展等事后信息。

该案例的 `asOf` 为 2024-08-06，是事后证据截止时间，不代表这些信息在 2024-07-19 04:09 UTC 已全部公开。仿真不会重放 CRWD 当日行情。

## GameStop（2021）

目录：`event-packs/gamestop-meme-2021-v1/`

默认实验只改变 `socialAmplification`：基线为 `1.0`，干预为 `1.8`。该参数是合成信息网络中的无量纲传播敏感性系数，不来自 Reddit 帖子、唯一账户数或任何账户级数据拟合。

核验过的主要官方来源：

- [GameStop 2021-01-11 Form 8-K（SEC）](https://www.sec.gov/Archives/edgar/data/1326380/000132638021000006/0001326380-21-000006-index.html)：公告与 RC Ventures 的协议及三名董事即时加入；
- [GameStop 2020 财年 Form 10-K（SEC）](https://www.sec.gov/Archives/edgar/data/1326380/000132638021000032/gme-20210130.htm)：发行人披露 2021-01-28 的盘中高低值与极端波动风险；这些数值只用于事实核对，不组成仿真价格路径；
- [SEC 工作人员 2021 年初市场结构报告](https://www.sec.gov/files/staff-report-equity-options-market-struction-conditions-early-2021.pdf)：报告账户参与、高空头仓位、社交关注、券商限制、流动性恶化与 LULD 暂停，并对空头回补和更广泛积极情绪作出有条件区分；
- [SEC 报告发布页](https://www.sec.gov/newsroom/press-releases/2021-212)：确认报告范围与 SEC 工作人员列出的市场结构议题。

该案例的 `asOf` 为 2021-10-18，因此它是基于 SEC 事后调查的验证案例，不是 2021 年 1 月的实时策略回放。当前有界情绪机制也不能还原看涨关注、空头回补、交易限制、清算压力与后续卖出的全部混合方向；这一限制已写入 manifest。

## 人工冻结与实验前检查

操作顺序如下：

1. 打开 Event Pack，逐条检查事实转述、来源、`knownAt` 和合成标记；
2. 对每条 `AI_PROPOSED` 候选执行批准、编辑或拒绝；必需声明不可被拒绝后直接冻结；
3. CrowdStrike 案例必须保留并批准 `claim-clarification`，否则 `clarificationDelay` 干预会被实验前检查阻止；
4. 冻结后运行 Scenario Preflight，检查单一干预、PIT 边界、网络配置、结果指标和 rule-only/LLM 运行配置；
5. 只有在人类另行批准经验容差并执行独立校准研究后，才能判断 L5 是否真正通过。

自动化测试会证明两组 JSON 可加载、来源引用闭合、真实事实与合成假设严格分层，并验证“逐条人工批准 → 冻结 → 默认干预通过 Preflight”的完整控制路径。测试不会把自动化通过等同为历史有效性通过。

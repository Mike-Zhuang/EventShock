# EventShock Lab Validation Report

## 报告范围

本报告记录截至 2026-07-15（America/Los_Angeles；部分服务器日志为 2026-07-16 UTC/Asia-Shanghai）当前工作区实际执行的自动检查、浏览器验收、服务器配置验证、代码中可见的控制以及未完成证据。它不把文档存在、测试定义存在、AI 自检或一次课程服务器部署视为真实用户研究、领域专家验证、安全批准或生产级运行证明。

当前结论：`NOT_RELEASE_APPROVED`。

## 实际执行的检查

| 检查 | 命令 | 当前结果 | 证据边界 |
| --- | --- | --- | --- |
| Python 解释器 | `python -c "import sys; ..."` | CPython 3.12.13，解释器位于项目 `eventshock` Conda 环境 | 只证明本次本地命令使用了规定解释器 |
| 完整后端静态检查 | `python -m ruff check backend tests` | passed | 证明当前 Python 文件满足已配置的 Ruff 规则 |
| 完整后端格式检查 | `python -m ruff format --check backend tests scripts` | 80 files already formatted | 只证明格式一致 |
| 完整后端回归 | `python -m pytest` | 214 passed, 1 upstream deprecation warning | 覆盖当前自动化契约；不等于外部科学有效性 |
| 前端类型检查 | `npm run typecheck` | passed | 证明 TypeScript 当前可编译 |
| 前端组件/API 测试 | `npm test` | 5 files、17 tests passed | 覆盖归一化、SSE 分帧、双语资源、Study 页面与应用壳，不是目标用户研究 |
| 前端生产构建 | `npm run build` | passed，5,986 modules transformed | 证明 Vite 发布工件可生成 |
| 前端依赖审计 | `npm audit --audit-level=high` | 0 vulnerabilities reported | 仅限 npm 当前数据库和锁文件 |
| 部署脚本语法 | `bash -n scripts/*.sh`、管理脚本 `py_compile` | passed | 不代替真实定时任务与回滚演练 |
| Caddy 与宝塔 Nginx 真实链路 | 固定 digest 的 Caddy 2.11.4；Caddy 容器请求 `host.docker.internal:18080/api/health`；公网 `/api/health` | 两条健康响应均为 `status=ok`、`service=eventshock-api`，且 `releaseCommit` 与已部署 GitHub SHA 一致 | 单次链路验收，不是长期可用性、容量或故障转移证明 |
| 本地浏览器主流程 | 英文默认、中文切换、SpaceX 18 条 claim 审核与冻结、Rule-only Scenario、Preflight、10 组 matched seeds、SSE 请求、Results、Trace、单实验作废、390px 响应式与控制台检查 | 通过手工浏览器验收；作废后 Results 显示 tombstone，控制台无 warning/error | 不是正式可用性研究或无障碍审计；没有真实智谱密钥 |
| 公网浏览器主流程 | 正式域名完成英文默认/中文切换、GLM 配置入口、SpaceX 18 条 claim 人工批准与冻结、单变量场景保存/冻结、Preflight、10 组 matched seeds、SSE、Results、Trace 与 Export 页面 | `exp-a553126d27e64245` 完成 10/10 配对种子；结果显示区间、方向一致率、有效 N 与限制；浏览器控制台无 warning/error | 这是开发者控制的课程验收，不是真实目标用户研究；没有调用真实智谱 API，也未把展示数值当成历史预测 |
| 公网入口与内部端口 | DNS/TLS、安全响应头、监听器、外部 `18080` 探测、UFW | Caddy 独占公网 80/443；app 为 `127.0.0.1:18000`；Nginx 为 `172.17.0.1:18080` 和 `127.0.0.1:888`；公网 `18080` 不可达 | 未执行独立渗透测试，云账户与宿主机整体基线仍需人工安全审查 |
| 宝塔 PHP 项目与流量统计 | 宝塔站点 API、Nginx access log、`free_site_total` 服务/socket/config/请求数 | `eventshock.mikezhuang.cn` 以 `project_type=PHP` 注册为真实反向代理；5 次公网请求使 access log 13→19、`site_total` 13→19，完整浏览器流程后计数为 125 | 已证明真实请求经过 Nginx；未以用户登录宝塔网页截图作为视觉证据，也不是长期监控证明 |
| scoped UFW | 动态 Docker network/bridge 与 `ufw status` | 只有 `br-607487476fbf` 上 `172.19.0.0/16 -> 172.17.0.1:18080/tcp` 的 `EventShock-Caddy-Nginx` 规则；没有 broad/public 18080 | 规则绑定当前 Compose network；人工重建网络后必须重新注册并复核 |
| 智谱真实 API | 未使用真实密钥或真实计费请求 | `NOT_RUN` | Mock 契约不能证明实时供应商质量、成本、延迟或保留政策 |
| GitHub / 宝塔自动部署 | implementation commit 先 push GitHub；push 与 draft PR 两个 CI run 的 Backend、Frontend、Production container 共 6 个检查通过；宝塔原生任务随后拉取部署 | 10 分钟任务 ID 1、原生脚本/日志和 root crontab 均存在；`GetLogs` 可读，日志含 `DEPLOY_SUCCESS` 与 `Successful`；本地、GitHub、sync state、current release 与健康 SHA 一致 | 证明一次成功拉取式部署和面板 API 可读日志；仍缺失败发布/恢复的正式演练和宝塔网页人工视觉确认 |

上表只记录实际发生的动作。自动化、受控公网流程和单机部署链路已通过，但真实用户、领域专家、真实 GLM、人工红队、许可与灾难恢复证据仍缺失，因此发布门禁继续保持阻断。

## 已关闭的历史回归问题

此前发现的 `runScenario(cognitiveSignals=...)` 签名不一致和上传原文通过候选 claim 回显的问题已经修复，并进入当前完整回归。最新的 214 项后端测试全部通过；本报告不再把这两项列为开放失败。新增的部署测试还覆盖 Caddy Docker bridge/subnet 识别、禁止公开 `18080`、精确 UFW 规则、添加后失败回滚和容器内版本一致性健康检查。

唯一警告来自 Starlette `TestClient` 对当前 `httpx` 适配层的上游弃用提示，不是测试失败；后续依赖升级仍需单独评估。自动化通过只能支持“已编码契约在当前环境中通过”，不能解释为产品、科学、模型或生产发布已经获批。

## 已有自动化验证面

### 市场内核

- price-time priority 与 resting-order 成交价。
- FIFO、IOC、价格保护和未成交数量。
- 自成交防护。
- 账本现金与净头寸守恒。
- 相同 seed 重放稳定性。
- 事件队列排序和单调时钟。

### 实验统计

- 基线与干预数量相等。
- 每对运行使用相同 seed。
- 自比较的 paired delta 为零。
- 中位数、经验区间、方向一致率和有效样本量。
- 单一干预变量差异。

### Event Pack 与 PIT

- JSON 文件、来源引用和 SHA-256。
- 真实事实、T2 估计与 synthetic 输入分层。
- SpaceX Nasdaq 公告不能在 `2026-06-27T00:00:00Z` 前注入。
- 事后 Reuters/JPMorgan 估计不进入仿真。
- 日期精度和 UTC 标签。

### LLM 认知层

- 未知字段和错误 Schema 拒绝。
- Evidence ID 白名单。
- 允许动作验证。
- prompt injection delimiter。
- bounded retries、一次 repair 和 deterministic ABSTAIN fallback。
- 缓存键包括 provider、model、prompt hash、Schema、Agent 配置、Observation 和 sampling。
- BYOK Session 隔离、过期、清除与掩码视图。

### Governance

- 组件清单与实际智谱模型目录、提示词 Hash 一致。
- 至少覆盖十类 P0 红队攻击。
- 红队评分由显式信号、操作符、权重和 critical criterion 决定。
- 未执行红队用例返回 `NOT_RUN`，不会因为定义存在而通过。
- 缺失人工证据的发布门返回 `PENDING_HUMAN_EVIDENCE`。
- 自动化测试 artifact 不能满足人工用户或专家 Gate。

## 未完成验证

| 验证项 | 状态 | 所需证据 |
| --- | --- | --- |
| 真实目标用户工作流与理解 | `PENDING_HUMAN_EVIDENCE` | 受观察任务、原始记录、编码规则、样本说明和结论 |
| 独立市场微观结构审查 | `PENDING_HUMAN_EVIDENCE` | 具名审查者、假设清单、问题、处置和签署 artifact |
| 独立模型风险审查 | `PENDING_HUMAN_EVIDENCE` | 用途、概念健全性、结果分析、限制与变更政策审查 |
| 实时 GLM 质量评估 | `PENDING_HUMAN_EVIDENCE` | 固定模型 ID、时间、提示词 Hash、golden/attack set、成本和延迟 |
| Grader 与人类判断一致性 | `PENDING_HUMAN_EVIDENCE` | 双人标注、分歧仲裁和 agreement 指标 |
| 双语等价性与可读性 | `PENDING_HUMAN_EVIDENCE` | 中英文任务、原始输出和用户理解证据 |
| 部署安全审查 | `PENDING_HUMAN_EVIDENCE` | 主机、TLS、代理、日志、内存、Secret、备份和依赖审查 |
| 第三方许可审查 | `PENDING_HUMAN_EVIDENCE` | 条款版本、用途、保留、训练、再分发、地域和退出方案 |
| 完整红队执行 | `NOT_EVALUATED` | 每个 Case 的运行时间、构建、输入、结果、捕获 artifact 和评分 |
| Incident response 演练 | `PENDING_HUMAN_EVIDENCE` | 真实演练时间线、参与者、检测、遏制、恢复和改进项 |
| 批量 invalidation | `CONTROL_GAP` | 数据库状态、API、导出标记和回归测试 |
| 长时并发与容量测试 | `NOT_RUN` | 明确负载、内存、CPU、SQLite 锁、队列和恢复结果 |

## 统计口径

系统报告的“95% 区间”是有限 seed 下的经验分位区间，不等于具有完整抽样理论保证的总体置信区间。默认 10 个 seed 适合课堂 Demo，但对尾部风险较不稳定。方向一致率描述 paired delta 与中位方向的一致程度，不是现实事件发生概率。

代表性 trace 是接近最大价差中位 delta 的一条路径，用于解释机制。它不是“最可能路径”，也不能代替完整分布。

## 模型验证口径

严格 JSON、证据 ID 和允许动作检查只能证明输出符合已编码规则。它们不能证明：

- Claim 在语义上真实。
- 结论完整且没有遗漏关键反证。
- 输出不会被金融用户误读。
- 中英文含义等价。
- Persona 不含刻板印象。
- 供应商没有保留、训练或版本漂移风险。

因此 code grader 只能作为混合验证的一部分，不能代替专家和用户评估。

## 发布判断

在以下条件全部满足前，`evaluateP0Release` 应保持 `BLOCKED`：

- 完整自动化测试 artifact。
- Flagship 可复现重放 artifact。
- 十类红队用例全部执行并通过。
- 用户理解研究。
- 独立领域专家审查。
- LLM 与 grader 人工验证。
- 部署安全审查。
- 许可审查。
- Incident rehearsal。

当前没有足够证据将系统描述为生产级风险工具。

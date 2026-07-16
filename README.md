# EventShock Lab

EventShock Lab 是一个可复现的事件驱动市场反事实实验室。它让事件风险分析人员审核一个有来源记录的事件包，只改变一个实验变量，在完全相同的随机种子下运行基准与干预情景，并追踪信念、订单、成交和流动性如何共同改变风险分布。

正式地址：[https://eventshock.mikezhuang.cn](https://eventshock.mikezhuang.cn)

> 本项目是研究与压力测试工具，不是价格预测系统，也不提供投资建议。SpaceX 旗舰案例中的公司、监管与指数事件事实来自可追溯来源；价格路径、订单簿、资金流、智能体行为和反事实效果均为明确标记的合成研究数据。

## 核心流程

```text
选择来源可追溯或完全合成的 Event Pack
  -> 人工批准、编辑或拒绝候选声明
  -> 冻结本次会话的证据集
  -> 配置规则或有限 LLM 认知节点
  -> 选择且只选择一个反事实干预
  -> 运行 10、25 或 50 组 matched seeds
  -> 比较分布、配对差异和市场路径
  -> 查看事件到成交的 Trace
  -> 导出含 JSON、CSV、Markdown 与 Parquet 的可复现实验 ZIP
```

价格由整数 tick、价格-时间优先的限价订单簿撮合产生，不由 LLM 直接生成。相同配置和随机种子可以确定性重放；基准与干预只允许一个已声明参数不同。

## 已实现功能

- 英文和简体中文完整界面，默认英文；语言和明暗主题在浏览器中持久化。
- SpaceX 2026 IPO 与 Nasdaq-100 快速纳入旗舰包：真实事件事实、官方来源链接和 PIT 时间边界，与合成行情及机制假设严格分层。
- CrowdStrike 2024 故障与 GameStop 2021 社交级联历史案例包：均可审核、冻结和运行，但状态明确为“案例可用、真实历史研究待执行”，不能冒充已校准验证。
- Event Pack 文本/文件导入、确定性或智谱结构化候选主张抽取、人工审核、双语编辑、拒绝和冻结；所有上传正文与来源元数据在抽取或调用智谱前先经过确定性内容安全扫描，高风险内容直接阻断，可复核内容必须人工确认并脱敏，安全摘要不包含命中原文且上传正文不持久化。
- 七类单变量干预：做市商容量、社交放大、止损敏感度、澄清延迟、流动性深度、被动资金流和信息延迟。
- Scenario 创建、保存、克隆、冻结与 diff；市场、人口、网络、LLM、结果指标和停止规则均有类型化配置与启动前检查。
- 后台实验队列、SSE 状态更新、真实进度、取消、历史记录，以及按完整 matched pair 持久化的校验断点；服务重启后可从 `FAILED_RETRYABLE` 重新启动并复用已验证的完整配对与冻结认知序列，不复用半完成配对。
- 十一类规则智能体：噪声、价值、动量、均值回归、做市、被动资金、机构执行、止损、去杠杆、强制平仓与套利。
- Provider-neutral 认知网关与智谱 BYOK：当前官方 GLM 型号目录、完整系统提示词、`json_object` 输出、严格本地 Schema/Evidence/Action 校验、一次修复和确定性回退。
- 限价单、部分成交、IOC、价格保护、自成交防护、做市库存偏移、离散事件队列、借券/保证金/强平账本和确定性事件追踪。
- 六类信息网络、`publishedAt`/`knownAt`/`scheduledAt`/仿真时间隔离、谣言与澄清传播，以及未来信息防泄漏。
- 17 项风险、流动性、网络、Agent 经济结果、强平和 LLM 指标；同时报告经验区间、配对 bootstrap、效应量、方向一致率与尾部概率。
- 可执行的顺序停止规则，以及预注册主指标的负对照、参数恢复 knockout、两水平局部敏感性、精确 sign test 和 Holm 多重比较诊断；这些仍是模型内部诊断，不是外部因果证明。
- Study Workbench 提供 7 个预注册模板、全因子与有界 Latin hypercube 设计、common seeds、2–4 个主指标、8 类负对照、10 类消融、family-level Holm 校正、探索性 rank-correlation 敏感性和不可变运行历史。Study 只执行受限规模的合成模型内部研究；认知臂使用冻结证据绑定 tape，若干消融是明确标注的最近可执行代理，所有结果都固定返回 `historicalValidityEstablished=false`。
- Executive Risk Cards、Market Dynamics、Trace Explorer、验证梯度、模型清单、红队定义、发布门与哈希链审计。
- 已完成实验可在当前匿名会话内按原因码和说明标记为 `INVALIDATED`；底层结果与审计哈希保留，但结果、runs、metrics、traces 与导出接口会拒绝把它继续作为有效研究使用。按模型、版本或时间窗口批量失效仍未实现。
- 可复现 ZIP 含 Manifest、事件包、场景、结果、认知决策、Trace、双语报告、CSV，以及六张固定 Schema Parquet 表。
- 参数上限、单仿真 worker、有限队列、请求体限制、稳定错误码和生产环境 API 文档关闭。

默认运行仍是无需密钥、可确定性重放的 `RULE_ONLY`。用户可在当前匿名会话中临时填写智谱 API Key 并选择 `HYBRID_LLM`；Key 只保存在服务器内存中、按 TTL 过期且不写入 SQLite、日志或导出。LLM 只能提出候选事实或有限的信念与行动偏好，不能设置价格、绕过风险控制或直接提交订单，最终订单必须经过固定策略、账本风控与确定性撮合层。

混合模式按 `decisionIntervalSteps` 和 `callBudget` 生成时点安全的认知决策序列，并将同一冻结序列复用于基准/干预及 matched seeds。模型能看到届时已知的证据、受限社交摘要和自身上轮记忆；确定性策略会响应当前模拟订单簿，但模型不会在每个随机种子中重新观察内生价格。AI 页面同时提供不计费的 code-grader 自检和显式触发的真实 GLM golden/攻击集，两者在结果中严格区分。

## 架构

```text
Browser
  -> Caddy (HTTPS, security headers, compression)
  -> BaoTa Nginx (private :18080 reverse proxy and real traffic accounting)
  -> EventShock app (FastAPI API + built React/TypeScript/Carbon assets)
       -> SQLite session, scenario, audit, experiment and Study state
       -> Zhipu structured cognition gateway (optional, BYOK)
       -> deterministic event queue, information network, ledger and order-book core
```

生产环境由两个轻量容器和宿主机宝塔 Nginx 组成：Caddy 独占公网 80/443 并处理 TLS，宝塔 Nginx 只在 Docker 私网地址的 18080 端口做真实反向代理与流量记账，单体应用只映射到宿主机回环地址 `127.0.0.1:18000`。首次引导或故障诊断可以让 Caddy 暂时直连容器内应用；这不会产生宝塔站点流量数据。SQLite、证书和配置保存在独立持久卷中。

## 开发环境

项目的开发、测试、容器和部署运行时统一使用 **CPython 3.12.13**。除非你能够自行保证版本、隔离和依赖一致性，否则使用项目默认的 Conda 环境，不要把依赖安装到系统 Python 或 Conda `base`。

首次创建环境：

```bash
conda env create --file environment.yml
conda activate eventshock
python -c "import sys; print(sys.executable); assert sys.version_info[:3] == (3, 12, 13)"
```

如果 `eventshock` 已存在，不要重复创建；先按[开发环境安装说明](usage_documents/install.md)核对版本，再在明确了解影响后更新依赖。

### 本地运行

终端一启动 API：

```bash
conda activate eventshock
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload
```

终端二启动前端；Vite 会把 `/api` 代理到 `127.0.0.1:8000`：

```bash
cd frontend
npm ci
npm run dev
```

打开 `http://127.0.0.1:5173`。

### 生产式本地构建

```bash
cd frontend
npm ci
npm run build
cd ..
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

构建完成后，FastAPI 会直接提供 `frontend/dist` 中的单页应用。

### 重放导出的实验

实验 ZIP 包含完整场景、Event Pack、matched seeds、认知决策和逐次事件日志哈希。在相同代码版本与 CPython 3.12.13 环境中执行：

```bash
conda activate eventshock
python scripts/replay-bundle.py /path/to/eventshock-experiment.zip
```

命令会实际重跑每一对基准/干预情景，并逐项核对配置哈希、Event Pack 哈希、事件日志哈希和 run-level 指标；这证明模型内部的确定性重放，不等同于外部历史有效性。

## 测试与检查

```bash
conda activate eventshock
python -m ruff check backend tests
python -m ruff format --check backend tests
python -m pytest

cd frontend
npm run typecheck
npm test
npm run build
```

后端测试覆盖价格—时间优先、部分成交、价格保护、开盘竞价、研究级波动停牌、PIT 信息隔离、六类网络、借券/保证金、内容安全策略、认知 Schema 与安全回退、确定性重放、baseline-vs-baseline 零差异、配对统计、Study 编排、会话隔离、哈希链审计、断点恢复、单实验 invalidation、SSE 状态流、完整实验生命周期和 ZIP/Parquet 导出。

## Docker 与服务器部署

本地生产式容器可在完成前端构建后启动：

```bash
cd frontend
npm ci
npm run build
cd ..
cp .env.example .env
docker compose up --detach --build
```

服务器内存较小，因此生产镜像直接复制已经通过本地与 CI 验证的 `frontend/dist`，服务器只构建 Python 运行层，不会在主机上运行 Node。`frontend/dist` 是受 Git 跟踪的发布工件：修改前端后必须执行 `npm run build`，并把源码和对应的 `dist` 一起提交。

正式更新采用 GitHub 拉取式链路。开发者在 `codex/self-hosted-mvp` 功能分支完成测试、commit 和 push；服务器只有在 `Backend / Python 3.12.13`、`Frontend / Node 22` 与 `Production container` 三项 GitHub CI 全绿后才接受该 SHA。宝塔原生计划任务每 10 分钟调用 `/opt/eventshock/bin/baota-eventshock-task.sh`，服务器匿名 fetch 公有仓库、拒绝非快进更新，并从目标 commit 的 `git archive` 构建带唯一镜像标签的发布版本。容器与公网健康检查必须返回目标 commit SHA，失败时自动恢复上一发布版本。

默认公网链路由 Caddy 独占 80/443 并处理 TLS，应用只额外映射到 `127.0.0.1:18000`。宝塔任务的原生输出可在面板“计划任务”的日志中查看，稳定审计日志写入 `/opt/eventshock/shared/logs/github-sync.log`。如果需要宝塔 Nginx 的真实站点流量统计，必须显式采用 `Caddy -> Nginx:18080 -> app:18000` 的真实转发链路；不能通过伪造宝塔“PHP 项目”数据库记录制造监控数据。

正式服务器的 DNS、首次安装、宝塔任务注册、Caddy、HTTPS、发布门禁、日志和排障步骤见[自有服务器部署指南](usage_documents/server-deploy.md)。正式域名使用以下解析：

```text
A  eventshock  47.251.41.145  TTL 600
```

当前没有稳定公网 IPv6，因此不创建 `AAAA` 记录。

## 目录结构

```text
backend/                       FastAPI、SQLite、实验服务和仿真内核
event-packs/                   来源可追溯事件包与完全合成测试包
frontend/                      React、TypeScript、Carbon UI 与双语界面
tests/backend/                 订单簿、仿真和 API 测试
usage_documents/               安装、Git、Agent 与服务器部署说明
.github/workflows/ci.yml       Python 3.12.13、前端与容器 CI
Dockerfile                     React 构建与 Python 3.12.13 运行镜像
compose.yml                    Caddy、应用和持久卷
Caddyfile                      自动 HTTPS 与反向代理
requirements*.lock             已验证的生产与开发 Python 依赖锁
```

完整产品、科学、验证、安全和课程交付蓝图见 [EventShock_Lab_End_to_End_Blueprint_ENGIN170E_CN.md](EventShock_Lab_End_to_End_Blueprint_ENGIN170E_CN.md)。

## 协作规范

1. 禁止任何人直接向 `main` 分支提交，包括直接 `push`、`merge` 或 `rebase` 后推送。
2. 所有改动必须在个人功能分支完成。
3. 所有改动必须通过 Pull Request 合并，并包含清晰的变更、测试和风险说明。
4. 未经 Review Approve，不允许合并。

具体流程见 [Git 使用说明](usage_documents/git_use.md)。

## 数据、责任 AI 与限制

- SpaceX 案例的事件事实来自所列 SEC、Nasdaq 等来源，但市场路径、深度、订单流、Agent 行为与反事实效果均为合成模型输出，不代表 SpaceX、Nasdaq 或任何真实证券的历史或未来表现。
- 当前模型是单标的简化现货订单簿，包含受限借券、保证金和强平代理，但不包含完整期权市场、跨场所路由、清算会员制度或完整交易所规则。
- 配对差异只描述所选模型假设下的内部机制，不构成现实世界因果效应。
- 10 个 seeds 仅适合课程 Demo；界面会显示区间、有效样本数和限制，不能把单条路径当作统计结论。
- 浏览器会话 ID 只用于隔离匿名草稿与实验历史；项目不接券商账户、不自动交易，也不采集支付信息。上传来源的完整原文不持久化，但用于人工审核的候选主张片段会保存到当前会话。确定性扫描器不是反病毒沙箱、完整附件解析器或隐私合规系统，用户仍不得上传不可信二进制、受监管个人数据或无权发送给第三方模型的材料。

## 许可证

本仓库采用 [PolyForm Strict License 1.0.0](LICENSE)。源码公开可见不等同于开放源代码软件；本项目属于源码可用（source-available）项目。

该许可证不授权分发软件，也不授权修改软件或基于软件创作新作品。其余使用仅在许可证规定的非商业用途等范围内获得授权；超出范围时，必须另行取得许可。以上仅为便于阅读的摘要，不替代或修改 `LICENSE` 中的英文许可证原文。

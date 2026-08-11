<p align="right">
  <a href="README.md">English</a> · <strong>简体中文</strong>
</p>

![EventShock Lab：基于证据的反事实市场压力测试](docs/assets/readme/eventshock-banner.svg)

# EventShock Lab

<p align="center">
  <strong>只改变一个条件，观察同一场模拟冲击是否变得更严重。</strong>
</p>

<p align="center">
  <a href="https://github.com/Mike-Zhuang/EventShock/actions/workflows/ci.yml"><img alt="CI 状态" src="https://github.com/Mike-Zhuang/EventShock/actions/workflows/ci.yml/badge.svg?branch=main"></a>
  <img alt="Python 3.12.13" src="https://img.shields.io/badge/Python-3.12.13-3776AB?logo=python&logoColor=white">
  <img alt="React 与 TypeScript" src="https://img.shields.io/badge/React%20%2B%20TypeScript-Production%20UI-0F62FE?logo=react&logoColor=white">
  <a href="LICENSE"><img alt="PolyForm Strict 1.0.0 源码可用许可证" src="https://img.shields.io/badge/License-PolyForm%20Strict%201.0.0-FFB000"></a>
</p>

<p align="center">
  <a href="https://eventshock.mikezhuang.cn"><strong>打开在线产品</strong></a>
  · <a href="#两分钟体验流程">体验流程</a>
  · <a href="#在本地运行">本地运行</a>
  · <a href="https://github.com/Mike-Zhuang/EventShock/issues/new/choose">提交问题</a>
</p>

EventShock Lab 是一个已经部署的研究原型，面向**市场事件风险分析人员、机构研究团队和行为金融教学人员**。它比较一组基准模拟和一组只改变单一已声明条件的配对模拟，帮助人研究风险传播机制，而不是用预测代替人的判断。

> [!IMPORTANT]
> 所有价格路径、订单簿、资金流、智能体行为和反事实效果都是合成的。结果只在选定证据、模型与假设下成立，不是预测，也不构成投资建议。

## 为什么做这个项目

传统压力测试常从主观叙事和固定冲击参数出发，不容易系统检查证据如何改变信念、信念如何通过网络传播、订单如何与有限流动性相互作用，以及级联从哪里开始。EventShock 把这类定性故事变成可检查、可重放的实验，同时把重要判断留给人。

项目刻意只回答一个窄问题：

> **冻结事件证据并保持其他设置不变时，改变一个条件会让模拟冲击变得更好、更糟，还是产生实质差异？**

## Human in the loop：人在闭环中

AI 可以降低信息整理和解释成本，但不能替人拥有研究结论。产品把 AI 与人的交接点直接做进流程。

| 阶段 | AI 可以协助 | 人必须完成 | 确定性系统负责 |
| --- | --- | --- | --- |
| 定义研究 | 提议事件标题、摘要、目标标的和研究问题 | 编辑并明确应用候选内容 | 保存人接受的版本和审计轨迹 |
| 收集证据 | 提议搜索式、发现候选网页、抽取候选主张 | 打开原始来源；逐条批准、修改或拒绝；确认时间和再分发边界 | 保存来源哈希，审核未完成时禁止冻结 |
| 设计实验 | 解释参数，并提议一个干预 | 选择基准、唯一干预、指标、随机种子数和费用上限 | 拒绝未声明的差异与未来信息泄漏 |
| 模拟行为 | 可选地为代表性 Agent 生成受证据约束的信念与行动偏好 | 决定是否启用 LLM 认知，并查看修复或回退状态 | 将定价、风控、账本、订单和撮合置于 LLM 权限之外 |
| 解释结果 | 解释服务器计算的指标，并依据证据回答追问 | 阅读区间和局限、查看机制链路并判断结果意味着什么 | 保持原始指标、版本、来源和导出包不可变 |

这套分工就是产品的核心：**AI 提议；人批准并解释；确定性机制执行并记录。**

## 两分钟体验流程

1. 打开[在线产品](https://eventshock.mikezhuang.cn)，登录后选择 **AI 引导**或专家流程。
2. 描述事件和研究问题。助手会生成可编辑的元数据候选，但不会自动应用。
3. 粘贴来源正文或使用受限联网发现。人工审核每个来源和候选主张；只有全部项目都有明确的人类决定后，才能冻结 Event Pack。
4. 选择一个干预，例如降低做市商容量，然后运行使用相同随机种子的基准组和干预组。可选 LLM Agent 只能影响受限认知，不能直接定价或提交订单。
5. 比较配对差异和结果分布、查看机制链路、向结果解释助手追问，并导出可复现实验包。

默认的 `RULE_ONLY` 路径不需要模型 Key。`HYBRID_LLM` 和结果解释助手使用用户提供的 Key；智谱是已测试的默认供应商，其他供应商会标记为社区预览。

## 已实现内容

- 已部署的双语、账号制 Web 应用。
- AI 引导和专家两套流程，覆盖事件定义、来源审核、Event Pack 冻结、情景设计、运行前复核、实验运行和结果解释。
- 手动文本/文件导入和受限联网发现；搜索摘要只能用于发现来源，不能直接作为证据。
- 使用价格—时间优先订单簿、风险控制、信息网络、十一类 Agent 和七种单变量干预的配对基准/干预模拟。
- 以分布为先的结果、配对差异、不确定性区间、机制链路、研究诊断、结果作废、持久历史和可复现 ZIP 导出。
- 可选的多供应商结构化 LLM 认知，以及带证据引用和多轮追问的双语结果解释。

完整产品与研究规范见[端到端蓝图](EventShock_Lab_End_to_End_Blueprint_ENGIN170E_CN.md)。

## 我们如何使用 AI 构建项目——诚实版本

我们使用 Codex、Claude 和模型供应商来阅读仓库、起草实现与测试、分析日志、提议事件元数据、抽取候选主张和解释模拟结果。团队仍然负责决定产品范围、研究边界、证据取舍、验收标准，以及一次发布是否可以上线。AI 生成的代码只有经过人工检查、自动测试、CI、部署健康检查和生产版本核对后，才会进入 `main`。

下面是几次真正改变我们使用 AI 方式的经历：

| 发生了什么 | AI 做错了什么 | 人如何处理 |
| --- | --- | --- |
| 把 FAA 紧急适航指令转成 Event Pack | 模型把完整句子切成碎片，并给主张分配了过于宽泛的影响通道 | 我们对照原文逐条检查，要求每条主张都有明确的人类决定，改进结构化抽取，并禁止批量批准低质量规则回退候选 |
| 测试者使用 AI 引导流程 | 助手重复询问用户已经提供的字段，有时在应该推进工作流时只给了一段回答 | 我们复现会话、拆清阶段、在生成期间保留用户消息和候选，并要求每次转换都由用户审核和应用 |
| 测试者询问结果助手正常的未来走势或买卖问题 | 过严的语义守卫把本可基于证据回答的问题直接拒绝 | 我们移除关键词式拒绝，保留“不构成投资建议”的边界，并要求先直接给出情景条件下的回答，再说明证据与不确定性 |

我们明确不让 AI：

- 批准证据、冻结 Event Pack、选择最终干预或决定生产发布；
- 编造缺失来源、价格、置信区间或现实确定性；
- 设置市场价格、绕过风控、访问未声明的实时数据或直接下单；
- 把不可核验的私有思维链当成结论依据。

人机分工中，我们自己编写并维护人工决策门、研究边界、测试要求和发布标准，因为这些是关于责任的判断，不是文字补全任务。

## 在本地运行

### 环境要求

- Git
- Conda 与 **CPython 3.12.13**
- Node.js 22–26 和 npm

Docker 对本地开发不是必需项。不要把依赖安装进系统 Python、Conda `base` 或其他项目的环境。

### 1. 克隆并准备 Python 环境

```bash
git clone https://github.com/Mike-Zhuang/EventShock.git
cd EventShock
conda env list
```

如果列表里没有 `eventshock`，只创建一次：

```bash
conda env create --file environment.yml
```

不依赖 shell 激活，直接确认实际解释器：

```bash
conda run -n eventshock python -c "import sys; print(sys.executable); assert sys.version_info[:3] == (3, 12, 13), sys.version"
```

### 2. 安装前端依赖

```bash
cd frontend
npm ci
cd ..
```

### 3. 分别启动两个开发进程

终端一——API：

```bash
conda run -n eventshock python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

终端二——前端：

```bash
cd frontend
npm run dev -- --host 127.0.0.1
```

打开 [http://127.0.0.1:5173](http://127.0.0.1:5173)。本地开发默认关闭邮箱认证，因此不需要 SMTP 凭据。

确认 API 和 Vite 代理都正常：

```bash
curl http://127.0.0.1:8000/api/health
curl http://127.0.0.1:5173/api/health
```

两个命令都应返回包含 `"status":"ok"` 的 JSON。Conda 安装和排障见[安装说明](usage_documents/install.md)。

## 测试

后端：

```bash
conda run -n eventshock python -m ruff check backend tests
conda run -n eventshock python -m ruff format --check backend tests
conda run -n eventshock python -m pytest
```

前端：

```bash
cd frontend
npm run typecheck
npm test
npm run build
```

每个 Pull Request 和 `main` 更新都会在 CI 中重复后端、前端、生产镜像构建和容器冒烟测试。

## 架构

```text
Browser
  -> FastAPI API + React/TypeScript 界面
       ├─ 人工审核的 Event Pack 与账号所属的研究历史
       ├─ 可选的结构化输出 LLM 网关
       ├─ 确定性事件队列、信息网络、账本与订单簿
       └─ SQLite 持久化、审计记录、导出和实验检查点
```

生产环境额外使用 Caddy HTTPS 和宝塔 Nginx 反向代理。运维细节放在[自有服务器部署指南](usage_documents/server-deploy.md)，不在 README 展开。

## 目录结构

```text
backend/             FastAPI 服务、持久化、认知网关和模拟器
event-packs/         来源可追溯与完全合成的 Event Pack
frontend/            React、TypeScript、Carbon UI 与双语产品界面
tests/backend/       后端、模拟、安全与生命周期测试
usage_documents/     安装、AI 供应商、工作流、Git 与部署说明
.github/             CI 与结构化 Issue 模板
```

## 文档

- [English README](README.md)
- [端到端蓝图](EventShock_Lab_End_to_End_Blueprint_ENGIN170E_CN.md)
- [安装说明](usage_documents/install.md)
- [Event Pack Factory 与 AI 引导说明](usage_documents/event-pack-factory.md)
- [AI 供应商接入说明](usage_documents/ai-providers.md)
- [Git 协作说明](usage_documents/git_use.md)
- [自有服务器部署说明](usage_documents/server-deploy.md)

## 项目状态与局限

EventShock Lab 是仍在接受测试的**课程研究原型**，不是经过外部校准的预测产品。历史案例用于展示流程和内部机制，不代表已经证明现实预测能力。10 对随机种子适合课堂演示，不足以支持生产风险结论。用户仍需核对来源权利、保护私人数据，并在已声明模型假设内解释结果。

## 贡献与支持

请使用范围清晰的功能分支和 Pull Request；发布前必须通过所需 CI 与生产健康门禁。可以通过结构化模板[报告 Bug、提出功能建议或反馈已脱敏的供应商兼容性问题](https://github.com/Mike-Zhuang/EventShock/issues/new/choose)。

请勿在公开 Issue 中提交 API Key、授权请求头、账号标识、邮箱地址、来源全文或其他个人与机密信息。

## 许可证

本仓库依据 [PolyForm Strict License 1.0.0](LICENSE) **源码可用，但不是开源软件**。除许可证明确写出的范围外，它不授予分发、修改软件或创作衍生作品的权利。最终应以许可证原文为准。

本项目由 UC Berkeley ENGIN 170E 第 9 组维护。

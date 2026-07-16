# EventShock Lab Third-Party Register

## 状态与边界

本登记表用于追踪外部模型、软件、基础镜像、反向代理和数据来源。它不是法律意见，也不是完整 SBOM。独立许可、隐私、安全和供应商条款审查均为 `PENDING_HUMAN_EVIDENCE`。

## 模型与外部服务

| 第三方 | 用途 | 发送数据 | 当前控制 | 退出与回退 | 审查状态 |
| --- | --- | --- | --- | --- | --- |
| 智谱开放平台 Chat Completions | Event extraction 与 simulated belief JSON | System Prompt、有限 Evidence/Observation、Request ID、User ID；Authorization Header 含用户 BYOK | 固定 HTTPS Endpoint、无重定向、结构化 JSON、本地 Schema、限次重试、TTL Key | Immutable cache、Rule-only ABSTAIN、关闭 Live LLM | 服务条款、保留、训练、地域、SLA 和成本均 `PENDING_HUMAN_EVIDENCE` |
| Let's Encrypt 或 Caddy 所选 ACME CA | 公网 HTTPS 证书 | 域名与 ACME 所需元数据 | Caddy 自动申请和续期 | 暂停公网服务或改用经审查证书 | 实际 CA、证书链和续期演练 `PENDING_HUMAN_EVIDENCE` |

运行时 GLM 目录来自 `backend/app/cognition/catalog.py`。模型 ID 包括 GLM-5.2、GLM-5.1、GLM-5-Turbo、GLM-5、GLM-4.7 系列、GLM-4.6、GLM-4.5 系列和已标记 legacy 的旧模型。稳定 ID 不保证稳定行为；每个模型都需要独立的实时验证 artifact。

## Python 运行时依赖

| 组件 | 锁定版本 | 主要用途 | 常见上游许可证 | 当前状态 |
| --- | --- | --- | --- | --- |
| CPython | 3.12.13 | 应用运行时 | PSF License | 镜像标签和 digest 已固定；供应链审查待人工 |
| FastAPI | 0.139.0 | API Framework | MIT | 版本锁定，许可复核待人工 |
| Pydantic | 2.13.4 | 严格 Schema | MIT | 版本锁定，许可复核待人工 |
| Starlette | 1.3.1 | ASGI 基础 | BSD-3-Clause | 版本锁定，许可复核待人工 |
| Uvicorn | 0.51.0 | ASGI Server | BSD-3-Clause | 版本锁定，许可复核待人工 |
| HTTPX / HTTPCore | 0.28.1 / 1.0.9 | 智谱异步 HTTP | BSD-3-Clause | 版本锁定，许可复核待人工 |
| AnyIO | 4.14.2 | 异步抽象 | MIT | 版本锁定，许可复核待人工 |
| PyYAML | 6.0.3 | 配置解析能力 | MIT | 版本锁定，许可复核待人工 |
| python-dotenv | 1.2.2 | 环境变量加载 | BSD-3-Clause | 版本锁定，许可复核待人工 |
| SQLite | Python 标准库绑定 | 控制面数据库 | SQLite Public Domain 声明 | 未使用外部 DB 服务；备份与安全审查待人工 |

许可证列是根据通常上游声明形成的初步登记，尚未由独立人员逐项核对当前发行包和 Transitive Dependency。

## 前端依赖

| 组件 | 版本范围 | 用途 | 常见上游许可证 | 当前状态 |
| --- | --- | --- | --- | --- |
| React / React DOM | `^19.1.1` | UI Runtime | MIT | Lockfile 和最终解析版本需在 Release Artifact 中保存 |
| Carbon React / Styles | `^1.94.0` | 设计系统 | Apache-2.0 | Attribution 与 Bundle 许可复核待人工 |
| Phosphor Icons React | `^2.1.10` | 图标 | MIT | 图标使用与 Attribution 复核待人工 |
| Recharts | `^3.1.2` | 图表 | MIT | 图表语义由项目负责，不由库保证 |
| Vite | `^7.0.6` | Build Tool | MIT | 生产构建供应链复核待人工 |
| TypeScript | `^5.8.3` | Type Check | Apache-2.0 | 仅开发构建 |
| Vitest 与 Testing Library | 锁定于 package lock | 前端测试 | 以各上游声明为准 | 完整许可证导出待人工 |

## 基础设施

| 组件 | 固定方式 | 用途 | 许可/条款关注点 | 状态 |
| --- | --- | --- | --- | --- |
| `python:3.12.13-slim-bookworm` | Docker Digest | App Base Image | Python 与 Debian 组件具有多个许可证 | Digest 已固定，SBOM 和漏洞扫描 `PENDING_HUMAN_EVIDENCE` |
| `caddy:2.11.4-alpine` | Docker Digest | HTTPS 与 Reverse Proxy | Caddy Apache-2.0；Alpine 组件各自许可 | Digest 已固定，SBOM 和漏洞扫描 `PENDING_HUMAN_EVIDENCE` |
| Docker / Compose | Host 提供 | 容器运行 | 产品许可与 Host 安全策略 | 未由仓库锁定，运营审查待人工 |
| 云服务器与 DNS 提供方 | 用户账户 | 公网部署 | 账户权限、地域、日志和 SLA | 未在仓库登记具体合同，`PENDING_HUMAN_EVIDENCE` |

## 外部事实和数据来源

| 来源 | 内容类型 | 仓库保存 | 禁止默认行为 | 状态 |
| --- | --- | --- | --- | --- |
| SEC EDGAR | 注册文件、招股书、8-K | 标题、URL、时间、短释义 | 不因公开访问而假设发行人内容可全文再分发 | Link-only 策略；人工许可复核待完成 |
| Nasdaq / Nasdaq Indexes | IPO 公告、指数方法论、纳入公告 | 元数据、链接、短释义 | 不保存或再分发未授权行情与指数数据 | `PENDING_HUMAN_EVIDENCE` |
| SpaceX Investor Relations | 发行人公告 | 元数据、链接、短释义 | 不保存完整受版权保护内容 | `PENDING_HUMAN_EVIDENCE` |
| FTSE Russell | 指数纳入通知 | 元数据、链接、短释义 | 不再分发指数数据或完整通知副本 | `PENDING_HUMAN_EVIDENCE` |
| Reuters | 具名估计与事件后报道 | 元数据、链接、短释义 | 不保存全文；不把报道估计升级为事实 | `PENDING_HUMAN_EVIDENCE` |
| FCC / NASA OIG | 政府命令与审计 | 元数据、链接、短释义 | 不假设第三方附件、照片和标志为公共领域 | 政府原创文本边界待人工复核 |
| GlobeNewswire | 官方公告分发时间元数据 | 标题、URL、时间 | 不保存完整分发页面 | Link-only；人工复核待完成 |

## 项目许可证

根目录采用 PolyForm Strict License 1.0.0。其允许范围、非商业条件、分发限制和衍生作品限制必须由使用者自行阅读。项目许可证不会自动授予任何第三方模型、数据、新闻、指数、图标或依赖的权利。

## 供应商变更触发器

以下变化必须更新本登记并重新验证：

- 模型 ID、Endpoint、Price、Token、Context 或 Retention Policy。
- Provider Terms、Training Policy、Region 或 Incident。
- Python/Node Dependency 或 Container Digest。
- Event Pack Source、Market-data Provider 或 License。
- Cloud、DNS、Certificate 或 Logging Provider。
- 新的 Authentication、Monitoring、Analytics 或 Error-reporting Service。

## 当前结论

仓库通过锁定版本、最小发送数据、Link-only 来源、Synthetic 行情和回退适配器降低第三方风险，但没有足够证据宣称完整许可和供应链审查已经完成。

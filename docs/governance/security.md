# EventShock Lab Security Policy

## 支持范围

当前安全支持范围是单服务器、低流量、匿名课程演示。系统没有生产级身份认证、组织租户、敏感数据承诺或真实交易权限。

生产安全批准状态：`PENDING_HUMAN_EVIDENCE`。

## 漏洞报告

仓库目前没有配置专用安全邮箱或公开漏洞赏金计划。发现漏洞时，不应在公开 Issue、截图或聊天中发布 API Key、Session ID、服务器地址之外的敏感配置、数据库内容或可复现利用细节。报告者应通过项目维护者已经建立的私有团队沟通渠道提交：

- 受影响版本和组件。
- 复现前提与最小步骤。
- 实际和最坏影响。
- 是否涉及 Secret、跨 Session、数据完整性或远程代码执行。
- 已采取的临时遏制。

建立专用安全联系人和响应 SLA 的状态为 `PENDING_HUMAN_EVIDENCE`。

## 身份与 Session

- `X-Session-ID` 用于匿名状态隔离，不是身份认证。
- Session ID 必须不可预测并只通过 HTTPS 传输。
- Caddy 访问日志删除 Session Header。
- 数据库读取和写入必须同时匹配资源 ID 与 Session ID。
- 不应把敏感、私人或受监管数据放入匿名 Session。
- 若未来增加账号或组织功能，必须引入真正的认证、授权、Session 轮换、CSRF 策略和安全退出。

## BYOK Secret

- 完整 API Key 只保存在应用进程内存。
- Key 具有 TTL，过期后在读取或清理时删除。
- API 配置视图只显示末四位掩码。
- Dataclass `repr` 排除 Key。
- Key 不得写入 SQLite、审计事件、实验结果、ZIP、异常消息或访问日志。
- 进程重启后 Key 必须消失。
- 用户应使用可撤销、最小权限、可查看用量的专用供应商 Key。
- Demo 结束或怀疑泄漏时，用户应立即在界面清除配置并在供应商控制台吊销 Key。

内存存储不是专用 Secret Vault。Host 管理员、内存转储、调试器和恶意依赖仍可能访问 Key。主机与 Crash Dump 审查为 `PENDING_HUMAN_EVIDENCE`。

## 模型调用

- 只调用固定的智谱 HTTPS Chat Completions URL。
- 不跟随重定向。
- Authorization Header 不写入请求日志。
- Provider 输出始终视为不可信。
- 本地 Schema、Evidence ID 和 Allowed Action 验证在 Provider 返回后执行。
- 重试和 repair 有固定上限。
- Persistent failure 进入 deterministic fallback。
- 模型没有网络浏览、文件系统、数据库、账本、订单或发布工具。

供应商条款、数据保留和训练政策需要用户在使用真实 Key 前自行确认；独立审查状态为 `PENDING_HUMAN_EVIDENCE`。

## 输入与上传

- Caddy 请求体最大 2 MiB；应用层继续限制来源数量、字符数和字段尺寸。
- API 限制来源数量和单份文本大小。
- Event Pack create 与 re-extract 在确定性抽取或智谱调用前扫描正文和来源/事件包元数据；扫描结果不会因来源域名在 allowlist 中而降级。
- 扫描器处理 Unicode 混淆与不可见字符，并识别无效 UTF-8/二进制特征、活动脚本、shell payload、prompt injection、权限提升、凭据、支付卡/美国 SSN、邮箱、美国/中国电话号码和有界代码样式。
- `HIGH` / `CRITICAL` 命中直接返回 `EVENT_PACK_CONTENT_BLOCKED`；`LOW` / `MEDIUM` 命中要求显式人工确认，并在进入抽取、模型和持久化前对当前支持类别做确定性脱敏。
- 持久化的安全摘要只保留 code、severity、字段、偏移、数量和来源审查标签，不包含命中原文或推荐动作；上传原文不保留。
- 上传内容只作为 untrusted data，不能进入 system instruction。
- 文件名、HTML、来源文本和模型输出都不能改变配置或调用工具。
- 输入经过 Pydantic 严格 Schema 和长度、范围、枚举检查。
- 不接受用户提供的服务器文件路径。

该扫描器是纯文本 fail-closed 初筛，不是安全认证。当前没有 Office/PDF/压缩包解析、OCR、恶意文件沙箱、病毒特征更新、全面 DLP/PII 分类、删除请求或数据主体工作流，因此仍不应上传敏感文件、不可信二进制附件或受监管个人数据。

## 导出

- 导出从 Session 绑定的实验记录生成。
- ZIP entry 名由服务器固定，不使用用户路径。
- 导出必须包含版本、限制和审计信息，不包含 BYOK。
- 消费 ZIP 的下游工具仍应防范 Zip Slip，不应盲目信任任何压缩包。
- 对导出 traversal 的完整动态测试状态为 `NOT_EVALUATED`。

## 数据库

- SQLite 位于独立持久卷。
- 每个操作使用独立连接并启用 foreign keys 和 busy timeout。
- 写入路径受进程内锁保护。
- Session ID 是查询条件的一部分。
- 当前没有数据库加密、行级安全、独立备份账户或在线复制。
- SQLite 文件与备份权限必须由 Host 层控制。

数据库备份与恢复演练为 `PENDING_HUMAN_EVIDENCE`。

## 容器与反向代理

已有配置：

- Python 3.12.13 镜像使用 digest。
- 应用以非 root UID/GID 运行。
- Root filesystem 只读，只有 `/data` 持久卷可写。
- 移除 Linux capabilities，并启用 `no-new-privileges`。
- 设置 CPU、内存、PID、日志轮换和健康检查。
- Caddy 镜像使用 digest，自动 HTTPS，并设置 HSTS、nosniff、DENY frame、Referrer 和 Permissions Policy。
- Caddy 与应用通过私有 Docker Network 通信。

未验证项：

- Host 防火墙、SSH、补丁和云账户权限。
- Docker daemon 权限与日志读取权限。
- Caddy Admin API 暴露情况。
- 容器和依赖漏洞扫描。
- 备份加密与恢复。
- 实际域名证书和 TLS 扫描。

这些项目均为 `PENDING_HUMAN_EVIDENCE`。

## 日志

- 默认 Uvicorn Access Log 被关闭，Caddy 保留经过过滤的访问日志。
- 不记录 Session Header。
- 不得记录完整请求体、Authorization Header 或模型 Key。
- Trace ID 可用于关联错误，但不应包含 Secret。
- 日志轮换限制单文件大小和数量。
- 生产 Debug Mode 必须关闭。

尚未完成对异常堆栈、第三方库日志和 Crash Dump 的 Secret 扫描。

## 依赖与供应链

- Python Runtime 和 Dev 依赖锁定到具体版本。
- 基础镜像和 Caddy 镜像使用 digest。
- 升级依赖前需要运行完整测试和安全检查。
- 不应通过未审查脚本修改全局 Python 或 Conda 环境。

当前没有 SBOM、签名、漏洞扫描或自动 Dependabot 证据，状态为 `PENDING_HUMAN_EVIDENCE`。

## GitHub 拉取式发布与宝塔

- 正常发布必须先进入公有 GitHub 功能分支，并通过三个固定名称的 GitHub Actions Check；服务器不接受未提交工作区。
- 服务器只匿名读取公有仓库和 Checks API，不保存 GitHub Token。`github-sync.env` 必须由 root 拥有，且不可被组或其他用户写入。
- 同步使用裸镜像、固定 refspec、快进关系检查和 `git archive`，不在运行目录执行 merge。
- 每个发布使用唯一镜像标签与独立 `.release.env`；Compose 调用会清除宿主进程的同名插值变量，避免新 SHA 污染旧版本回滚。
- 宝塔任务必须通过其 `AddCrontab` 注册。任务正文和日志不能包含 Key、Token、环境文件内容或带凭据的 Git URL。
- 宝塔 Nginx 只允许监听 Docker 内部 host-gateway 的 18080，上游应用只绑定 `127.0.0.1:18000`；Caddy 继续独占公网 80/443。
- 宝塔反向代理明确关闭 `proxy_cache`、`proxy_no_cache` 与 `proxy_cache_bypass`，避免匿名 `X-Session-ID` 绑定的 API 响应被跨会话缓存。

这些控制的代码存在不等于部署已被独立审查；分支保护、宿主权限、真实回滚、重启顺序和宝塔流量统计仍需实际证据。

## 安全发布条件

以下任一情况存在时禁止发布为受控 Demo：

- 已知 Critical/High 漏洞未处置。
- Cross-session 数据可见。
- Secret 出现在日志、响应、数据库或导出。
- Prompt injection 获得状态修改能力。
- Future leakage 未阻断。
- 受限数据进入公开仓库或导出。
- 自动测试、红队、主机安全或 incident evidence 缺失。

`backend/app/governance/release_gate.py` 将缺失人工安全证据保留为 `PENDING_HUMAN_EVIDENCE`，不会自动通过。

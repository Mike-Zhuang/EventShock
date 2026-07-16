# ADR 0011：采用 GitHub 门禁与宝塔轮询的拉取式部署

- 状态：当前 MVP 已接受
- 日期：2026-07-15
- 负责人：EventShock Lab 工程团队

## 背景

EventShock 部署在一台资源有限的自有服务器上，并要求更新任务能在宝塔“计划任务”及其原生日志中可见。此前从开发机直接打包工作区并上传虽然适合一次性引导，但不能保证服务器运行的内容已经提交到 GitHub，也无法强制绑定 CI、提交 SHA 和可审计回滚点。服务器不应保存公有仓库并不需要的 GitHub Token，宝塔站点列表也不能靠直接写数据库伪造。

## 决策

正常发布采用 GitHub 拉取式链路：开发者在个人功能分支完成测试和构建，将源码与受 Git 跟踪的 `frontend/dist` 一起 commit、push；服务器当前只轮询 `codex/self-hosted-mvp`。目标提交的 `Backend / Python 3.12.13`、`Frontend / Node 22` 与 `Production container` 三项 GitHub Check Run 全部成功后，服务器才允许部署。功能通过 Pull Request 合入稳定分支后，可以在人工核对快进关系和稳定分支 CI 后修改服务器配置，不直接向 `main` 推送。

宝塔通过自身 `crontab().AddCrontab` 注册名为 `EventShock GitHub 自动同步部署` 的原生 Shell 任务，每 10 分钟调用 `/opt/eventshock/bin/baota-eventshock-task.sh`。包装器把相同输出同时交给宝塔原生任务日志和 `/opt/eventshock/shared/logs/github-sync.log`，并保留同步脚本的真实退出码。任务不直接写 `/etc/crontab`，避免面板不可见的重复调度。

同步脚本对公有 GitHub 仓库执行匿名 HTTPS fetch，使用 `/opt/eventshock/shared/github-mirror.git` 裸镜像与固定内部引用，不在生产发布目录执行合并。它记录上次成功 SHA，拒绝非快进更新；通过 `git archive` 提取目标 commit，并要求其中包含已构建的 `frontend/dist/index.html`。服务器为每个发布构建唯一的 `eventshock-app:<release-id>` 镜像标签，避免后一版本覆盖前一版本的回滚镜像。目标 commit 的运维脚本也安装到不可变目录，只有部署和健康验证成功后才原子切换 `/opt/eventshock/bin`；失败 SHA 采用 30/60 分钟有界退避，避免每 10 分钟重复构建。

部署完成前必须同时满足应用容器健康和公网 `/api/health` 返回目标 40 位 commit SHA。任一步骤失败时，不写入目标同步状态，并由部署退出陷阱恢复上一发布目录及其唯一镜像。SQLite 和 Caddy 证书使用独立持久卷，不随代码回滚删除。

Caddy 继续独占公网 80/443 并终止 TLS；首次引导可直接代理 Docker 内部的 `app:8000`，最终生产请求必须经过 `Caddy -> Nginx:18080 -> app:18000`，使宝塔获得真实站点流量统计。Nginx 只能在 Docker host-gateway 私网地址监听。UFW active 时，站点注册器动态识别 Caddy 所属 Docker network 的 subnet 与 Linux bridge，只允许该 bridge/subnet 到 host-gateway `18080/tcp`，并禁止 broad/public 18080 规则。注册器必须从 Caddy 容器内验证 `host.docker.internal:18080/api/health`；失败时恢复 Nginx 配置，并只撤销本次新建的精确 UFW 规则。不得直接修改宝塔站点数据库来伪造监控记录；必须通过宝塔自身站点 API 创建 `version=00` 的 PHP 列表项、反向代理和 `free_site_total` 配置，并用真实请求计数验证。

## 被否决的方案

- **从开发机直接上传未提交工作区作为日常发布**：无法证明服务器内容与 GitHub commit、评审和 CI 一致，也容易夹带本地文件。
- **服务器直接 `git pull` 到当前运行目录**：会把 fetch、merge 和工作区写入混在一起，失败时难以获得不可变回滚点。
- **每次构建覆盖同一个 `eventshock-app:local` 标签**：上一发布目录可能指向已被替换的镜像，回滚不再可靠。
- **仅写系统 crontab**：任务不会作为宝塔原生对象出现在前端，用户也无法通过宝塔查看其原生日志。
- **保存 GitHub Token 或部署密钥**：目标仓库公有，匿名只读 fetch 和公共 Check Runs API 已足够，额外凭据只会扩大泄漏面。
- **使用 webhook 直接触发生产部署**：当前单机 MVP 不需要额外公开接收端、签名密钥和防重放面；10 分钟轮询更简单且延迟可接受。
- **通过 `ufw allow 18080` 或云安全组解决容器到宿主机连通性**：这会把仅供 Caddy 使用的内部代理端口扩大到 `Anywhere` 或公网来源；必须使用动态 bridge、source subnet、host-gateway 与目标端口四项都受限的精确规则。
- **只向宝塔数据库插入伪造 PHP 站点**：面板列表记录不等于真实请求路径和 access log。允许通过宝塔自身 API 把项目注册为 `version=00` 的 PHP 列表反向代理站点，但请求必须真实经过其 Nginx，且不能生成与 Caddy 冲突的 80/443 listener。

## 后果

优点是每个生产版本都可以追溯到 GitHub SHA、三项 CI 与不可变发布目录；服务器不持有 GitHub 凭据，宝塔前端能管理调度并查看任务输出，失败发布具备确定的上一版本恢复路径。

代价是正常发布最多有约 10 分钟发现延迟，首次部署仍需要受控引导；GitHub 公共 API 和 GitHub Actions 暂时不可用时，服务器会保留旧版本而不会发布新代码。分支发生 force-push 或 rebase 后同步会按设计停止，需要人工审查，不能靠删除状态文件自动继续。把 Nginx 加入真实流量路径会增加一层代理和额外运维面，但这是满足宝塔真实流量监测要求的明确取舍。

## 验证与复审

自动验证应覆盖脚本语法、配置权限、同一任务防重入、无变更、CI 等待、CI 失败、非快进拒绝、缺少前端工件、唯一镜像标签、目标 SHA 健康检查和失败回滚。运维验证还应在目标服务器实际检查：

- 宝塔计划任务中存在且只存在一条正确的 10 分钟任务；
- 宝塔原生日志与稳定审计日志都能看到一次实际执行结果；
- 成功发布后本地、GitHub、同步状态与 `/api/health` 的 SHA 一致；
- 人为制造的失败发布不会改变可用版本，上一版本仍能响应健康检查；
- 若启用 Nginx 统计，Caddy 容器能经 `host.docker.internal:18080` 通过健康检查，真实公网请求确实写入对应 access log 与 `site_total`；UFW 只有匹配当前 Caddy bridge/subnet 的精确规则，没有 `Anywhere` 或其他 broad/public 18080 放行。

这些服务器端检查必须以实际命令输出、宝塔页面和日志为证据；脚本或本文档存在本身不代表注册、执行、回滚与流量统计已经验证完成。

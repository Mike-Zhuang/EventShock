# EventShock 自有服务器部署指南

本文档描述 EventShock 的 GitHub 拉取式发布链路。目标服务器是 Ubuntu 22.04 x86_64，公网 IPv4 为 `47.251.41.145`，正式访问地址为 `https://eventshock.mikezhuang.cn`。

正常发布必须经过以下路径，不再把开发机的未提交工作区直接复制到生产服务器：

```text
本地功能分支完成测试与前端构建
  -> commit 并 push 到 GitHub
  -> GitHub 三项必需 CI 全部通过
  -> 宝塔原生计划任务每 10 分钟运行一次
  -> 服务器匿名 fetch 公有仓库
  -> 校验快进关系并按 commit 执行 git archive
  -> 构建带唯一标签的应用镜像
  -> 容器与公网健康检查均返回目标 commit SHA
  -> 切换 /opt/eventshock/current；失败则恢复上一版本
```

当前部署分支固定为 `codex/self-hosted-mvp`。功能稳定并通过 Pull Request 合并后，可以按第 8 节把服务器改为跟踪稳定分支；不要通过修改服务器文件绕过 GitHub 与 CI。

## 1. 运行架构

首次引导时由 Caddy 直连应用；完成本指南第 9 节后，正式生产拓扑如下：

```text
Internet :80/:443
  -> Caddy（公网 TLS、安全响应头、压缩）
  -> host.docker.internal:18080（宝塔 Nginx，仅 Docker 私网监听）
  -> 127.0.0.1:18000（EventShock app）
```

- `caddy` 是默认且唯一的公网入口，负责证书申请与续期。
- `app` 同时提供 FastAPI 与已构建的 React 单页应用。它只映射到宿主机回环地址 `127.0.0.1:18000`，不能从公网直接访问。
- 宝塔 Nginx 是真实的中间反向代理而不是面板占位记录；生产请求确实经过其 access log，供宝塔站点流量统计使用。
- 实验状态接口使用 SSE；宝塔 Nginx 的 EventShock 代理配置必须关闭响应缓冲，保留长连接相关请求头，并且不能缓存 `/api/v1/experiments/*/events`。
- SQLite 保存在 Docker 命名卷 `eventshock-data`；重新构建应用镜像不会删除该卷。
- 每个发布目录都生成独立的 `.release.env`，应用镜像标签形如 `eventshock-app:<release-id>`。上一版本不会因下一次构建而被同名镜像覆盖。

第 9 节说明如何在不中断现有 HTTPS 的前提下完成宝塔 Nginx 接入。Caddy 直连仅作为首次引导和故障诊断模式，不是本项目要求的最终监测拓扑。

## 2. DNS 与公网端口

在域名服务商的 DNS 控制台为 `mikezhuang.cn` 新增或确认：

| 字段 | 填写内容 |
| --- | --- |
| 记录类型 | `A` |
| 主机记录 / Name | `eventshock` |
| 记录值 / Value | `47.251.41.145` |
| TTL | `600` 或 `Auto` |
| 路由线路 | 默认 |

不要在记录值中填写 `https://`、路径或端口。当前没有确认可用且稳定的公网 IPv6，因此不要添加 `AAAA` 记录。可复核：

```bash
dig +short eventshock.mikezhuang.cn A @1.1.1.1
dig +short eventshock.mikezhuang.cn A @8.8.8.8
```

两条命令都应输出：

```text
47.251.41.145
```

阿里云安全组入方向还必须允许：

| 协议 | 端口 | 来源 |
| --- | --- | --- |
| TCP | `80` | `0.0.0.0/0` |
| TCP | `443` | `0.0.0.0/0` |

UDP `443` 只用于可选 HTTP/3；不开放不会影响 TCP HTTPS。不要把应用端口 `18000` 或可选 Nginx 内部端口 `18080` 开放到公网。SSH 与宝塔面板端口继续遵循服务器现有访问限制。

## 3. 本地发布前准备

在项目根目录确认当前位于部署功能分支，并先同步远程引用：

```bash
cd /Users/mike/Documents/University/Grade_1B/UCB_Summer_Session/Classes/ENGIN_170E/Project/repo
git switch codex/self-hosted-mvp
git fetch origin
git status --short
```

执行后端检查：

```bash
conda activate eventshock
python -c "import sys; print(sys.executable); assert sys.version_info[:3] == (3, 12, 13)"
python -m ruff check backend tests
python -m ruff format --check backend tests
python -m pytest
```

执行前端检查并生成发布工件：

```bash
cd frontend
npm ci
npm run typecheck
npm test
npm run build
cd ..
```

`frontend/dist` 是发布输入，必须与源码一起受 Git 跟踪。GitHub 的前端任务会重新构建并执行 `git diff --exit-code -- dist`；源码与已提交工件不一致时，CI 会失败，服务器不会部署。提交时必须包含本次源码和对应的 `frontend/dist`，但不要把密钥、`.env`、数据库、缓存或无关文件加入提交：

```bash
git status --short
git add \
  .dockerignore .env.example .github .gitignore .python-version \
  Caddyfile Dockerfile README.md backend compose.yml docs \
  environment.yml event-packs frontend pyproject.toml \
  requirements-dev.lock requirements.lock scripts tests usage_documents
git diff --cached --check
git diff --cached --stat
git commit -m "feat: describe the completed change"
git push --set-upstream origin codex/self-hosted-mvp
```

确认本地 `HEAD` 与 GitHub 上的部署分支一致：

```bash
git fetch origin
git rev-parse HEAD
git rev-parse origin/codex/self-hosted-mvp
```

两个 SHA 应完全相同。禁止直接向 `main` 推送；评审与合并流程见 [Git 使用指南](git_use.md)。

## 4. GitHub CI 门禁

服务器只接受下列三个 GitHub Check Run 全部以 `success` 完成的目标提交：

- `Backend / Python 3.12.13`
- `Frontend / Node 22`
- `Production container`

同步脚本通过 GitHub 公共 API 查询公有仓库，不保存 GitHub Token。同名检查若存在多条，必须全部成功，不能用一条成功结果掩盖另一条失败或未完成结果。检查尚未完成或数量不足时记录 `WAIT_CI` 并等待下一轮；任一检查失败时记录 `CI_BLOCKED` 并停止，不改动当前服务。

GitHub 页面上的检查结果才是该提交的远程门禁证据。本地测试通过不能代替这三项检查，服务器也不会通过跳过检查来“抢先”部署。

## 5. 首次安装 GitHub 同步入口

本节用于当前服务器已有可用 EventShock 发布目录的情况。安装脚本把同步入口、宝塔任务包装器和宝塔注册工具安装到不可变运维版本目录，并让 `/opt/eventshock/bin` 原子指向该目录；同时创建 root 专用配置。它不会直接写系统 crontab。

```bash
ssh sv
sudo bash /opt/eventshock/current/scripts/install-github-sync.sh /opt/eventshock/current
sudo sed -n '1,120p' /opt/eventshock/shared/github-sync.env
```

默认配置为：

```dotenv
EVENTSHOCK_GITHUB_URL=https://github.com/Mike-Zhuang/EventShock.git
EVENTSHOCK_GITHUB_BRANCH=codex/self-hosted-mvp
EVENTSHOCK_GITHUB_REPOSITORY=Mike-Zhuang/EventShock
```

配置文件位于 `/opt/eventshock/shared/github-sync.env`，由 root 拥有且权限为 `0600`。仓库为公有仓库，配置中不应出现 GitHub Token、密码或部署密钥。

安装完成后，可先做只读检查：

```bash
sudo /opt/eventshock/bin/register-baota-task.py --show
sudo readlink -f /opt/eventshock/bin
sudo ls -l /opt/eventshock/bin/baota-eventshock-task.sh
sudo ls -l /opt/eventshock/bin/sync-from-github.sh
```

对于一台完全空白的新服务器，仍需要先从一个已评审的 Git commit 引导运行一次 `scripts/deploy-server.sh`，建立 Docker、共享配置和初始发布目录；此后所有常规更新必须走 GitHub 拉取链路。不要用本地未提交工作区作为引导源码。

## 6. 在宝塔注册每 10 分钟计划任务

为了让任务在宝塔“计划任务”前端及其“任务日志”中原生可见，必须调用宝塔自身的 `crontab().AddCrontab`，不能只在 `/etc/crontab` 中手写一行。本仓库提供的注册工具通过宝塔 10.x 自身的 Python 环境和 `AddCrontab` 完成这一操作。

先查看是否已有同名任务：

```bash
sudo /opt/eventshock/bin/register-baota-task.py --show
```

没有任务时注册；若同名任务存在但字段不同，人工核对后才使用 `--replace`：

```bash
sudo /opt/eventshock/bin/register-baota-task.py
# 仅在已核对同名旧任务可以被替换时执行：
sudo /opt/eventshock/bin/register-baota-task.py --replace
```

注册结果应满足：

- 名称：`EventShock GitHub 自动同步部署`
- 类型：Shell 脚本
- 周期：每 `10` 分钟
- 任务入口：`/opt/eventshock/bin/baota-eventshock-task.sh`
- 状态：启用

随后在宝塔网页的“计划任务”中核对名称、周期和启用状态。需要立即验证一次时，通过宝塔执行已注册任务：

```bash
sudo /opt/eventshock/bin/register-baota-task.py --run
```

`--run` 不是绕过宝塔直接执行 shell：注册工具调用宝塔自身的任务执行入口，随后用 `GetLogs` 读取同一条任务的原生日志。命令结果中的 `logsReadableInPanel=true` 只能证明宝塔接口能读到日志；仍应在面板“计划任务 → 日志”中人工核对一次名称、执行时间、目标 SHA 和最终状态。

不要另建第二条系统 cron 或重复的宝塔任务。同步脚本通过 `flock` 防止前一轮尚未结束时重入，但重复调度会制造不必要的日志和 GitHub API 请求。

### 日志位置

包装器使用 `tee` 同时保留两份输出，并通过 `PIPESTATUS` 传播真实退出码：

1. 宝塔原生任务日志：在宝塔“计划任务”中点击该任务的“日志”查看。
2. 稳定审计日志：`/opt/eventshock/shared/logs/github-sync.log`。

SSH 查看稳定日志：

```bash
sudo tail -n 200 /opt/eventshock/shared/logs/github-sync.log
sudo grep -E 'NO_CHANGE|WAIT_CI|CI_BLOCKED|DEPLOY_(START|SUCCESS)|ERROR' \
  /opt/eventshock/shared/logs/github-sync.log | tail -n 100
```

安装脚本同时写入 `/etc/logrotate.d/eventshock-github-sync`，按天轮转并保留 14 份压缩日志。是否已在特定服务器成功注册、执行和显示，应以 `--show`、宝塔网页与上述实际日志为准；仅存在脚本不等于注册已经完成。

## 7. 每轮同步与回滚如何工作

`/opt/eventshock/bin/sync-from-github.sh` 每次运行会：

1. 使用非阻塞文件锁，避免两轮部署并发执行。
2. 以匿名 HTTPS 初始化或更新裸仓库镜像 `/opt/eventshock/shared/github-mirror.git`。
3. 把配置分支抓取到固定内部引用，不在生产目录执行 `git pull` 或合并。
4. 对照 `/opt/eventshock/shared/github-sync.state`，并同时核对 current 发布、容器环境与公网健康 SHA；只有四者一致才输出 `NO_CHANGE`，否则按运行时漂移处理。
5. 要求上次已部署提交是目标提交的祖先；发现 force-push、rebase 或其他非快进历史时拒绝部署。
6. 查询目标 SHA 的三项 GitHub CI；只有全部成功才继续。
7. 使用 `git archive` 把该提交解包到临时目录，拒绝缺少 `frontend/dist/index.html`、后端入口或部署脚本的提交。
8. 运行该提交自己的 `deploy-server.sh`，创建 `/opt/eventshock/releases/<release-id>`，并构建唯一镜像标签 `eventshock-app:<release-id>`。
9. 等待应用容器健康，并要求公网 `/api/health` 同时返回 `status=ok` 与目标 40 位 `releaseCommit`。
10. 成功后才写同步状态，并把 `/opt/eventshock/bin` 原子切换到目标 commit 的不可变运维脚本目录；失败时不写目标 SHA。

同一目标 SHA 部署失败后会进入有界退避：第一次至少等待 30 分钟，后续失败至少等待 60 分钟；分支出现新的 SHA 后自动解除。这样 10 分钟计划任务仍会持续记录状态，但不会反复构建一个已知失败版本。应用发布和运维脚本各保留最近 5 个不可变版本，当前版本不会被清理。

部署脚本会记录切换前的发布目录。新版本构建、启动、容器健康或公网 SHA 校验失败时，退出陷阱会把 `/opt/eventshock/current` 恢复为上一发布目录，并重新启动该目录对应的唯一镜像。SQLite 与 Caddy 证书卷不会随代码发布删除。

查看当前版本和服务状态：

```bash
ssh sv
sudo readlink -f /opt/eventshock/current
sudo cat /opt/eventshock/shared/github-sync.state
sudo /opt/eventshock/current/scripts/compose-current.sh ps
curl --fail --show-error https://eventshock.mikezhuang.cn/api/health
```

查看容器日志：

```bash
sudo /opt/eventshock/current/scripts/compose-current.sh logs --tail=100 app
sudo /opt/eventshock/current/scripts/compose-current.sh logs --tail=100 caddy
```

不要执行 `compose-current.sh down --volumes`，否则会删除 SQLite 与 Caddy 持久数据。不要手工改写 `github-sync.state` 来跳过非快进保护；发生历史重写时应先停止任务、查明 GitHub 分支和当前部署关系，再制定人工恢复方案。

## 8. 从功能部署分支切换到稳定分支

当前固定轮询 `codex/self-hosted-mvp` 是 MVP 阶段的临时发布策略。代码通过 Pull Request 合入稳定分支、稳定分支自身三项 CI 全绿且当前部署 SHA 是其祖先后，才可修改 root 配置：

```bash
ssh sv
sudoedit /opt/eventshock/shared/github-sync.env
```

例如切换到 `main`：

```dotenv
EVENTSHOCK_GITHUB_URL=https://github.com/Mike-Zhuang/EventShock.git
EVENTSHOCK_GITHUB_BRANCH=main
EVENTSHOCK_GITHUB_REPOSITORY=Mike-Zhuang/EventShock
```

修改后先查看任务与配置，再通过宝塔立即执行一次：

```bash
sudo /opt/eventshock/bin/register-baota-task.py --show
sudo /opt/eventshock/bin/register-baota-task.py --run
sudo tail -n 200 /opt/eventshock/shared/logs/github-sync.log
```

如果日志出现非快进拒绝，不要删除镜像、发布目录或状态文件。先核对：

```bash
git --git-dir=/opt/eventshock/shared/github-mirror.git log --oneline --decorate --all -n 20
sudo cat /opt/eventshock/shared/github-sync.state
```

## 9. 宝塔 Nginx 与真实流量统计

EventShock 不是 PHP 应用。仅向宝塔数据库伪造一条“PHP 项目”记录既不会产生真实流量统计，也可能让面板生成占用 80/443 的站点配置，与 Caddy 冲突。因此不得直接修改宝塔数据库或伪造站点。

首次引导链路是 `Caddy -> app:8000`，此时宝塔 Nginx 不在请求路径中，无法根据自己的 access log 统计 EventShock 流量。最终部署必须通过宝塔受支持接口创建真实反向代理，并保持以下拓扑：

```text
Internet :80/:443
  -> Caddy
  -> host.docker.internal:18080（宝塔 Nginx，仅内部监听）
  -> 127.0.0.1:18000（EventShock app）
```

安全约束：

- Caddy 继续独占公网 TCP 80/443 并负责 TLS，不能让宝塔 Nginx 再监听这两个端口。
- Nginx 的 `18080` 只绑定 Docker host-gateway 可达的宿主机内部地址，并且不得在云安全组或 UFW 对公网开放。
- Nginx 上游只能使用 `http://127.0.0.1:18000`；应用端口仍保持回环绑定。
- 宝塔站点 access log 必须确实接收到 Caddy 转发的请求，面板流量数据才有意义。

完成并验证 Nginx 内部反向代理后，在 `/opt/eventshock/shared/.env` 设置：

```dotenv
EVENTSHOCK_APP_HOST_PORT=18000
CADDY_UPSTREAM=host.docker.internal:18080
```

然后重新应用当前发布配置并检查整个链路：

```bash
sudo /opt/eventshock/current/scripts/compose-current.sh up -d --remove-orphans
curl --fail --show-error http://127.0.0.1:18000/api/health
curl --fail --show-error https://eventshock.mikezhuang.cn/api/health
sudo /opt/eventshock/current/scripts/compose-current.sh logs --tail=100 caddy
```

宝塔 Nginx 的具体监听地址必须以目标服务器实际的 Docker host-gateway 为准，可先查询：

```bash
sudo /opt/eventshock/current/scripts/compose-current.sh exec caddy \
  getent hosts host.docker.internal
```

目标服务器尚未安装宝塔 Nginx 时，先通过宝塔官方软件入口安装；当前宝塔 10.x 的 CLI 极速安装命令为：

优先在宝塔“软件商店”中安装 Nginx 1.30。宝塔 10.0.2 的命令行
`bt install/1/nginx/1.30` 存在参数解析缺陷；需要通过 SSH 自动化同一官方安装器时，
使用该版本面板实际调用的底层入口：

```bash
sudo bash -lc \
  'cd /www/server/panel/install && bash ./install_soft.sh 1 install nginx 1.30'
```

安装器会尝试创建公网 `listen 80` 并启动 Nginx，而 Caddy 已占用该端口，因此安装期间首次启动可能失败。不要停止或改写 Caddy；安装完成后立即使用仓库提供的注册工具创建端口 `18080`、PHP 版本 `00` 的真实宝塔站点和反向代理，并把 Nginx listener 限制到上一步查询出的私有 host-gateway：

```bash
gatewayAddress="$(
  sudo /opt/eventshock/current/scripts/compose-current.sh exec -T caddy \
    getent hosts host.docker.internal | awk 'NR == 1 {print $1}'
)"
sudo /opt/eventshock/bin/register-baota-site.py \
  --listen-address "${gatewayAddress}"
```

注册工具调用宝塔自己的 `panelSite.AddSite` 与 `CreateProxy`，不会直接插入 `sites` 数据库；它还会停用宝塔默认公网 vhost、要求 Nginx 只有一个私网 `18080` listener、运行 `nginx -t`，并通过内部地址检查 `/api/health`。生成的站点扩展配置包含 `proxy_buffering off`，使实验 SSE 状态流不会被 Nginx 聚合后才一次性返回。站点会以 `project_type=PHP`、`version=00` 出现在宝塔 PHP 项目列表，但实际业务是指向 FastAPI 的反向代理，不会安装或执行 PHP。工具还会通过 `SiteTotalConfig.one_site_status` 启用该站点的 `free_site_total`，并要求服务、Unix socket、站点扩展配置和三次真实请求计数全部通过后才报告成功。

只有上述内部健康检查通过后，才把共享配置的 `CADDY_UPSTREAM` 改为 `host.docker.internal:18080` 并重新应用 Compose。最后确认：

```bash
sudo ss -ltnp | grep -E ':(80|443|18000|18080)\b'
sudo /www/server/nginx/sbin/nginx -t
curl --fail --show-error https://eventshock.mikezhuang.cn/api/health
sudo find /www/server/site_total/data/total -type f -mmin -10 -print
sudo /opt/eventshock/bin/register-baota-site.py \
  --listen-address "${gatewayAddress}" --show
```

验收时必须看到 Caddy 独占公网 80/443、应用只监听 `127.0.0.1:18000`、宝塔 Nginx 只监听私有 host-gateway 的 18080，并且一次公网请求后宝塔 access log / `site_total` 文件实际增长。

不要在未确认内部监听、端口冲突和完整请求路径前启用该模式。是否已经产生真实统计，应同时核对 Nginx access log 与宝塔网页，不能只看站点列表中是否出现名称。

## 10. 域名与 IP 回退

持久配置位于：

```text
/opt/eventshock/shared/.env
```

默认值使用正式域名：

```dotenv
APP_DOMAIN=eventshock.mikezhuang.cn
APP_ENV=production
LOG_LEVEL=INFO
```

若 DNS 或证书签发临时不可用，可短期改为：

```dotenv
APP_DOMAIN=http://47.251.41.145
```

修改后执行：

```bash
sudo /opt/eventshock/current/scripts/compose-current.sh up -d
```

IP 回退没有 HTTPS，只用于排查；问题解决后必须恢复域名。自动部署的公网 SHA 健康检查依赖 `APP_DOMAIN`，错误的域名配置会使新版本安全失败并触发回滚。

## 11. 资源、安全与备份

- `app` 最多使用 1.5 个 CPU、1024 MiB 内存；`caddy` 最多使用 0.25 个 CPU、128 MiB 内存。
- 容器采用 `restart: unless-stopped` 与日志轮转。应用以非 root 用户运行、根文件系统只读，并删除不需要的 Linux capabilities。
- Caddy 将请求体限制为 2 MiB，并删除访问日志中的匿名会话请求头 `X-Session-ID`。
- Caddy 与 Python 基础镜像锁定到仓库中审核过的版本或 digest；依赖分别由 `package-lock.json`、`requirements.lock` 和 `requirements-dev.lock` 固定。
- GitHub 同步使用匿名只读请求；服务器不保存 GitHub Token。
- 每次更新前通过 SQLite online backup 在持久卷的 `deployment-backups/` 中创建一致性备份，并只保留最近 3 份。失败回滚不会自动覆盖数据库，因为新版本短暂对外期间可能已经产生合法写入；如需恢复数据，应先停写并人工核对备份时间点。
- 代码发布目录与唯一镜像默认保留最近 5 个版本，同时始终保留当前版本和直接回滚目标；清理失败只记录警告，不影响已经验证成功的版本。
- 服务器是单实例 MVP，不提供高可用。至少在重要演示前使用 SQLite 在线备份能力创建站外备份；不要在应用写入期间直接复制数据库文件。

如需停止服务但保留数据：

```bash
sudo /opt/eventshock/current/scripts/compose-current.sh down
```

再次强调，不要添加 `--volumes`。

## 12. 常见问题

### 日志持续显示 `WAIT_CI`

目标 SHA 尚未出现全部三项检查或检查仍在运行。打开 GitHub 对应提交查看 Actions；不要在服务器上绕过检查。下一轮 10 分钟任务会重新查询。

### 日志显示 `CI_BLOCKED`

至少一项必需检查不是 `success`。在同一功能分支修复、重新测试、commit 并 push；服务器只会考虑新的全绿 SHA。

### 日志显示 `refusing non-fast-forward deployment`

部署分支发生了 force-push、rebase 或切换到了不包含当前发布 SHA 的历史。同步脚本按设计拒绝。停止自动任务并核对分支历史；不要直接删除状态文件规避保护。

### Caddy 无法申请证书

依次确认 DNS、阿里云安全组 TCP 80/443、UFW、80/443 监听者和 Caddy 日志：

```bash
dig +short eventshock.mikezhuang.cn A @1.1.1.1
sudo ss -ltnp '( sport = :80 or sport = :443 )'
sudo /opt/eventshock/current/scripts/compose-current.sh logs --tail=100 caddy
```

### Docker 构建被系统终止

先用 `free -h` 和 `docker system df` 检查资源，不要删除持久卷。前端已经在本地与 CI 构建并提交，服务器构建只复制 `frontend/dist`，不会运行 Node；仍然内存不足时，应先保留失败日志并评估交换空间或主机资源。

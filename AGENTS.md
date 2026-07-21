# 项目代理协作规则

## 适用范围

本文件适用于项目根目录及所有子目录。若某个子目录存在更具体的 `AGENTS.md`，则该文件仅在对应子目录内补充或覆盖本规则。

## 开始工作前

1. 阅读根目录 `README.md`，并按任务需要阅读 `usage_documents/` 中的相关文档。
2. 使用 `git status --short` 检查工作区，保留用户已有的修改，不得覆盖或删除无关内容。
3. 先查找现有实现、接口、配置和依赖清单，再开始修改；禁止仅凭猜测创造接口或业务逻辑。
4. 修改应保持增量和最小范围，不得擅自删除原有功能或进行与任务无关的大规模重构。

## 语言与命名

- 回复、说明、文档和代码注释使用简体中文。
- 代码标识符使用有明确语义的英文，不使用拼音或难以理解的缩写。
- 变量和函数使用 `camelCase`。
- 类和组件使用 `PascalCase`。
- 常量使用 `UPPER_SNAKE_CASE`。
- 文件和文件夹使用 `kebab-case`，但已有文件的命名风格应保持一致。

## Python 环境

### 强制要求

- 项目的开发、测试、容器和部署运行时统一使用 **CPython 3.12.13**；当前基线不使用 Python 3.13 或 3.14。
- 项目包在 `pyproject.toml` 中必须声明 `requires-python = ">=3.12,<3.13"`。该声明约束 Python 3.12 系列，不负责锁定补丁版本；3.12.13 还必须由环境、容器和 CI 配置分别精确锁定。
- 除非开发者认为自己对 Python 及包管理器足够熟悉，并能够自行保证项目级环境隔离与依赖一致性，否则本地 Python 环境统一使用 Conda 管理。优先复用版本和依赖均兼容的项目专用 Conda 环境；没有合适环境时，创建名为 `eventshock` 的专用环境。
- 满足上述例外条件的开发者可以使用 `uv`、`venv`、`virtualenv`、Poetry 或其他环境管理工具，但仍必须使用项目专用的隔离环境，并精确锁定 CPython 3.12.13。
- Agent 只有在能够通过仓库配置与实际检查确认替代方案满足上述版本、隔离和依赖一致性要求时，才能套用例外；如有任何不确定，必须使用默认 Conda 方案。
- 无论使用哪种工具，都不得将项目依赖直接安装到共享的系统 Python、Conda 的 `base` 环境或其他项目的环境中。
- 未经用户明确要求，不得修改全局 Conda channel、pip index、代理或其他用户级环境配置。
- Docker 容器是本地环境管理策略之外的隔离运行环境，基础镜像必须使用 `python:3.12.13-slim-bookworm` 锁定 Python 补丁版本，且容器内不得再创建虚拟环境。若发布流程要求镜像内容不可变，还必须锁定经过审查的镜像 digest，并定期更新安全修复。
- GitHub Actions 的 Linux 必过任务必须使用 `runs-on: ubuntu-24.04`，Python 矩阵精确写为 `python-version: ["3.12.13"]`；不得假定该精确版本可直接用于 macOS 或 Windows runner。项目稳定后如需评估 Python 3.13，应新增独立的非阻塞兼容性任务，不得替换当前基线。

### 默认 Conda 流程

Agent 在无法确认替代方案满足上述例外条件时，默认执行以下 Conda 流程。用户明确指定替代工具或仓库已经存在明确的替代环境配置时，先验证其符合版本、隔离和依赖一致性要求，再改用相应流程。执行 Python 相关命令前，先检查项目中的 `environment.yml`、`requirements.txt`、`pyproject.toml`、`.python-version` 或其他版本声明，再执行：

```bash
conda env list
```

如果列表中没有 `eventshock` 环境，创建并激活项目专用环境：

```bash
conda create --name eventshock python=3.12.13
conda activate eventshock
```

如果 `eventshock` 已存在，只激活现有环境，不要再次执行同名 `conda create`：

```bash
conda activate eventshock
```

无论使用默认 Conda 流程还是经允许的替代工具，激活或选择项目隔离环境后都必须确认实际解释器属于该环境，且版本精确为 3.12.13：

```bash
python -c "import sys; print(sys.executable)"
python --version
python -c "import sys; assert sys.version_info[:3] == (3, 12, 13), sys.version"
```

如果精确版本检查失败，立即停止，不得继续安装依赖，也不得擅自升级、删除或重建现有环境；任何迁移或重建都必须先取得用户明确确认。使用默认 Conda 流程时，如果当前平台的软件源找不到 3.12.13，应先检查平台和软件源；确需使用 conda-forge 时可采用仅对本次命令生效的 `--channel conda-forge`，不得因此降低版本要求或修改全局 channel。

使用经允许的替代工具时，也必须复用或创建项目专用隔离环境，运行上述解释器路径与版本检查，并将依赖变更同步到仓库采用的依赖清单或锁文件中。

后续创建或修改版本配置时，必须保持以下五处一致：

```text
.python-version: 3.12.13
environment.yml: dependencies 中包含 python=3.12.13
pyproject.toml: requires-python = ">=3.12,<3.13"
Dockerfile: FROM python:3.12.13-slim-bookworm
GitHub Actions: python-version: ["3.12.13"]
GitHub Actions runner: ubuntu-24.04
```

安装 Python 包时，应先复用项目已有依赖清单。确需使用 pip 时，使用以下形式，确保包安装到当前解释器：

```bash
python -m pip install <package-name>
```

新增或调整依赖后，应同步更新仓库已有的依赖清单或环境文件；不得只修改本地环境而不记录项目依赖变化。

## 代码质量

- 函数和类应保持单一职责，避免过长函数和重复逻辑。
- 复杂业务逻辑必须添加中文注释，重点解释设计原因和约束。
- TypeScript 避免使用 `any`，优先定义明确的 `interface` 或 `type`。
- Python 的 I/O 密集型后端逻辑优先使用 `async` / `await`，但不得破坏现有同步架构。
- 优先复用已有模块、工具函数和配置，不得重复实现等价功能。
- 不得提交密钥、令牌、密码、私有地址或其他敏感信息。

## Git 协作

- 禁止直接向 `main` 分支提交或推送代码。
- 所有修改必须在个人功能分支中完成，并通过 Pull Request 合并。
- 用户已明确授权：完成其要求的代码或文档修改并验证后，默认执行提交、推送、创建 Pull Request、合并和部署，不需要在每次任务中重复询问。项目负责人兼仓库所有者 `Mike-Zhuang` 明确允许其本人发起的变更在所需 CI 全部通过后自行合并并触发部署，无需其他成员正式 Review Approve；其他贡献者仍应经过团队审核。CI、生产发布与健康检查门禁不得绕过；破坏性操作、变基以及任务范围外的外部写操作仍需单独取得授权。
- 禁止使用 `git reset --hard`、`git clean -fd`、`git checkout --` 等可能丢失用户修改的命令。
- 提交前只包含当前任务相关文件，不得顺手修改或提交无关内容。
- 具体协作流程参见 `usage_documents/git_use.md`。

## 验证与交付

- 修改代码后必须运行与变更范围相匹配的测试、静态检查或最小可执行验证。
- 修改配置后必须检查配置格式，并确认相关工具能够读取该配置。
- 修改 Markdown 后应检查标题层级、代码围栏、相对链接和命令完整性。
- 若仓库已有测试或构建命令，应优先执行现有命令，不得自行发明替代流程。
- 不得在未执行验证时声称测试通过；最终说明应列出实际执行的验证及结果。
- 若因客观条件无法完成某项验证，应明确说明未验证内容、原因和潜在风险。

## 许可证

- 本项目采用根目录 `LICENSE` 中的许可证。
- 未经用户明确授权，不得修改、替换或删除许可证及 README 中的许可证说明。
- 引入第三方代码、模型、数据或素材前，必须确认其许可证与本项目用途兼容，并保留必要的版权和归属信息。

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

- Python 环境统一使用 Conda 管理。
- 优先复用与项目版本和依赖兼容的已有 Conda 环境；没有合适环境时，创建项目专用的新 Conda 环境。
- 禁止创建或使用 `venv`、`.venv`、`virtualenv` 等非 Conda 虚拟环境。
- 禁止执行 `python -m venv`、`python3 -m venv` 或 `virtualenv`。
- 不得将项目依赖安装到系统 Python 或 Conda 的 `base` 环境中。
- 未经用户明确要求，不得修改全局 Conda channel、pip index、代理或其他用户级环境配置。

### 标准流程

执行 Python 相关命令前，先检查项目中的 `environment.yml`、`requirements.txt`、`pyproject.toml`、`.python-version` 或其他版本声明，再执行：

```bash
conda env list
```

如果存在兼容的环境，直接激活：

```bash
conda activate <environment-name>
```

如果不存在兼容环境，则按项目要求的 Python 版本创建专用环境：

```bash
conda create --name <environment-name> python=<python-version>
conda activate <environment-name>
```

激活后必须确认实际解释器来自目标 Conda 环境：

```bash
python -c "import sys; print(sys.executable)"
python --version
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
- 未经用户明确要求，不得执行提交、推送、合并、变基或创建 Pull Request。
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

# ENGIN 170E PROJECT

## 协作规范

1. 禁止任何人直接向 `main` 分支提交（包括 `push`、`merge`、`rebase` 后推送）。
2. 所有改动必须在个人功能分支完成。
3. 所有改动必须通过 Pull Request 合并，且 PR 必须包含变更说明。
4. 未经 Review Approve，不允许合并。

## 开发环境

项目约定开发、测试、容器和部署运行时统一为 **CPython 3.12.13**；后续创建 `pyproject.toml` 时，必须声明兼容范围 `>=3.12,<3.13`。除非你认为自己对 Python 及包管理器足够熟悉，并能够自行保证项目级环境隔离与依赖一致性，否则本地 Python 环境必须使用 Conda 管理，不使用 `uv`、`venv`、`virtualenv` 或其他替代工具。熟悉者可以自行选择环境管理工具，但所有方案都必须使用 CPython 3.12.13，且不得将项目依赖直接安装到共享的系统 Python 或 Conda `base` 环境；Docker 和 GitHub Actions 的 Linux 必过任务也必须锁定到 3.12.13，避免不同环境使用不同补丁版本。

默认 Conda 方案的完整安装与环境创建步骤，以及所有方案通用的版本验证要求，见[开发环境安装说明](usage_documents/install.md)。

## 许可证

本仓库采用 [PolyForm Strict License 1.0.0](LICENSE)。源码公开可见不等同于开放源代码软件；本项目属于源码可用（source-available）项目。
该许可证不授权分发软件，也不授权修改软件或基于软件创作新作品。其余使用仅在许可证规定的非商业用途等范围内获得授权；超出范围时，必须另行取得许可。
以上仅为便于阅读的摘要，不替代或修改 `LICENSE` 中的英文许可证原文。

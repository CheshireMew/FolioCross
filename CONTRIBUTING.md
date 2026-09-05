# Contributing to FolioCross

欢迎报告问题和提交改进。先阅读 [README](README.md) 了解当前能力，再按需要查看[架构](docs/architecture.md)和 [CLI 合同](docs/cli.md)。目前主要在 Windows 上开发与验证，从源码运行。

## 报告问题

在 [Issues](https://github.com/CheshireMew/FolioCross/issues) 中说明提交或版本、Windows 和 Python 版本、输入格式、复现步骤、预期与实际结果。样本请使用可以公开分享的自制内容，不要上传 API Key、私人书籍、译文、数据库或完整请求日志。

## 开发与检查

按 README 配置依赖目录，然后运行：

```powershell
uv sync --locked --group dev
$env:QT_QPA_PLATFORM = 'offscreen'
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
git diff --check
```

测试使用临时工作区和模拟模型。真实模型检查需显式执行，并会产生 API 调用费用。文档改动不需要制作安装包。

## 提交改动

一个 PR 说明一个清楚的问题：什么操作会触发、修改后有什么变化、如何验证。格式处理改动应覆盖结构保留；数据状态改动应覆盖恢复和版本冲突。不要提交 `workspace/`、凭据、原书、译文、日志、虚拟环境和构建产物。

长任务在独立 Worker 中执行，保持 GUI 响应。人工段落锁、修订历史、事务、EPUB 资源与阅读顺序都是现有合同。外部 Agent 通过 CLI 操作，不新增内置聊天或 Agent 运行时。Wenyi 迁移只读来源，KindleUnpack 与 Calibre 保持独立外部进程。

## 维护文档

公开说明使用中文、英文和日文 README，功能、命令和限制应同步。详细技术文档放在 `docs/`。`docs/assets/logo.svg` 根据 `src/foliocross/desktop/qml/Main.qml` 侧栏标志派生：42×42、圆角 12、底色 `#c86a3b`、居中白色粗体 F、字号 23。更改应用标志时同步这些值。

保留 [LICENSE](LICENSE) 和 [NOTICE](NOTICE) 的许可与来源声明。新增第三方代码或资源时说明来源与适用许可证。

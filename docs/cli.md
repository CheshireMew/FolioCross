# 命令行接口

所有查询和修改命令都支持统一工作区参数：

```powershell
foliocross --workspace E:\Code\FolioCross\workspace doctor --json
```

主要命令：

- `foliocross app`：启动桌面界面。
- `foliocross import PATH [--source-lang auto] [--output-format epub] [--soft-budget N] [--hard-budget N] [--fake]`：导入并创建暂停任务。
- `foliocross run BOOK_OR_JOB_ID [--no-export]`：开始或恢复最新任务。
- `foliocross jobs list|status|pause|resume|cancel`：查询和控制任务。
- `foliocross export JOB_ID --format epub|docx|html|txt|markdown`：从一致状态重新导出。
- `foliocross glossary export|import BOOK_OR_JOB_ID`：导出或导入术语 JSON。
- `foliocross review JOB_ID --estimate`：只查看主动深度审校的 token、调用次数和费用区间。
- `foliocross review JOB_ID`：执行主动深度审校，结果只进入问题列表。
- `foliocross retranslate JOB_ID SEGMENT_ID --instruction TEXT`：重译一个段落并保存锁定版本。
- `foliocross migrate-wenyi ROOT`：列出可迁移状态；增加 `--state` 与 `--source` 后执行复制导入。
- `foliocross doctor`：检查依赖、工作区、Calibre 和 DeepSeek 凭据。

`--json` 成功结果包含 `ok: true`；预期错误包含稳定的 `error.code`、`message` 和 `details`。
Worker 子进程还支持内部使用的 `--prepare-only` 与 `--export-format`，桌面界面通过这些入口
执行译前暂停和重新导出，避免在界面线程中运行耗时工作。

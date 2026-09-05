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
- `foliocross glossary export|import BOOK_OR_JOB_ID --json`：导出或导入术语 JSON。
- `foliocross glossary refresh BOOK_OR_JOB_ID --json`：明确刷新任务使用的冻结术语版本。
- `foliocross review JOB_ID --estimate`：只查看主动深度审校的 token、调用次数和费用区间。
- `foliocross review JOB_ID`：执行主动深度审校，结果只进入问题列表。
- `foliocross retranslate JOB_ID SEGMENT_ID --instruction TEXT`：重译一个段落并保存锁定版本。
- `foliocross migrate-wenyi ROOT`：列出可迁移状态；增加 `--state` 与 `--source` 后执行复制导入。
- `foliocross doctor`：检查依赖、工作区、KindleUnpack、可选 Calibre 和 DeepSeek 凭据。

## 外部 Agent 的调用约定

`foliocross --help` 和各级 `--help` 列出用途与参数，查看帮助不会创建工作区。
建议在每次调用中明确指定同一个绝对工作区路径。`--json` 可以放在根命令后或具体命令后；
业务结果在标准输出中返回一个完整 JSON 对象，长文本不会随终端宽度折行或解释为 Rich 标记。
`--help`、补全和 `app` 是交互入口，不作为 JSON 业务接口使用。

成功调用返回退出码 0。业务或初始化失败返回 1；命令、参数错误返回 2；可捕获的用户中断返回 130。
错误对象为 `{"ok":false,"error":{"code":"...","message":"...","details":{}}}`。
参数错误使用 `invalid_arguments`，段落版本冲突使用 `segment_version_conflict`。
`doctor` 的 `ok:false` 表示环境检查未通过，退出码为 1，具体原因在检查字段中。
查询操作成功不代表被查询的翻译成功：必须检查 `job.status` 或 `operation.status`。

导入按文件内容哈希复用已有任务，返回 `reused:true` 时，新提供的导入配置不会替换原配置。
命令中的任务参数可接受任务 ID 或书籍 ID；段落、章节、问题、历史版本、后台操作分别使用其自身 ID。
先用查询返回的 ID 操作，不需要直接访问 SQLite 或猜测磁盘目录。

## 后台执行与恢复

`run`、`jobs resume`、`review`、`retranslate`、`export` 默认同步执行，增加 `--background`
后将操作保存到持久队列并立即返回 `operation_id` 和 `job_id`。调度器与 Worker 独立运行，
发起命令退出后仍会继续。`run --prepare-only` 只完成译前准备后暂停；`run --no-export`
翻译完成后保持 `ready`，不生成导出文件。正常完成翻译和自动导出后为 `completed`。

```powershell
foliocross --workspace E:\Books\FolioState import "E:\Books\book.epub" --json
foliocross --workspace E:\Books\FolioState run <job-id> --background --json
foliocross --workspace E:\Books\FolioState operations wait <operation-id> --timeout 30 --json
foliocross --workspace E:\Books\FolioState jobs status <job-id> --json
```

`operations list [--job ID]` 列出操作；`operations status ID` 返回操作、任务、产物和日志路径。
`operations wait ID --timeout 0..60` 有限等待，返回 `terminal` 和 `timed_out`。
超时不会停止任务，也不表示失败。操作终态有 `completed`、`failed`、`cancelled`；
安全暂停后操作可能已经 `completed`，而书籍任务仍是 `paused`，应同时查看两者。

同一任务已有排队或运行操作时，相同动作及参数返回已有操作，不重复启动；不同动作返回
`background_operation_active`。终态操作再次提交会创建一次新的操作，重译和审校可能再次产生模型费用。
同步操作不会越过已有后台队列。重译在提交时记录段落版本，实际执行前与保存时均检查版本。

`jobs pause ID` 请求安全暂停翻译，`jobs cancel ID` 请求取消，已经保存的译文保留。
排队中的操作会直接停止；执行中的请求需要等待安全检查点，因此应再次查询状态确认。
审校、单段重译和导出不是可在中间安全暂停的整本翻译流程，需要立即停止时使用 `jobs stop ID`，
该命令仅控制后台 Worker，返回 `stop_requested` 后仍需查询操作是否已经结束。
`jobs resume ID --background` 从已保存进度继续整本翻译。

若调度器启动失败，`scheduler_start_failed` 中仍返回已保存的操作 ID；执行
`operations recover` 可重新启动调度器接管队列，不新建任务。该命令也可在意外关闭后使用。
运行中的孤立 Worker 会被接管，丢失的 Worker 会被记为失败；查看错误后明确重新提交原动作。

## 查看和编辑内容

```powershell
foliocross jobs chapters <job-id> --json
foliocross segments list <job-id> --limit 50 --offset 0 --json
foliocross segments list <job-id> --chapter <chapter-id> --query "检索文字" --json
foliocross segments show <segment-id> --json
foliocross segments edit <segment-id> --text-file "E:\Books\revision.txt" --expected-version 3 --json
foliocross revisions list <segment-id> --json
foliocross revisions restore <revision-id> --expected-version 4 --json
```

段落列表按原书顺序分页，每页 1–200 段，返回 `total`、`next_offset`；末页 `next_offset` 为 null。
`--query` 是区分大小写的原文或译文子串搜索。`segments show` 提供原译文、标记、锁状态、
当前版本以及全书和章节上下文。分页期间有并行编辑时，搜索结果可能变化，保存前以段落最新版本为准。

`segments edit` 从 UTF-8 文件（允许 BOM）读取完整译文，保留换行；不能为空，必须保留全部
`⟦FC:...⟧` 标记及其顺序。修改、恢复都必须提供读取时的 `--expected-version`，冲突时不写入，
应重新读取、核对内容后再提交。恢复创建新版本，历史保留。保存结果锁定，后续整本自动翻译不会覆盖。
单段 `retranslate` 是明确替换现有译文的操作，会生成锁定版本；建议也提供 `--expected-version`。

## 审校、术语与导出

`issues list JOB [--open]`、`issues show ISSUE` 读取审校问题。
`issues accept ISSUE --expected-version N [--text-file PATH]` 明确应用建议并锁定译文，
可用 UTF-8 文件修改建议后再应用；问题状态和译文版本在同一事务提交。
已经处理的问题不能再次接受。`issues dismiss ISSUE` 忽略问题，不修改译文。

`glossary list JOB` 直接读取当前术语表及冻结版本；导入术语后需要在暂停时明确执行
`glossary refresh JOB` 才更新冻结版本。它不会自动批量修改已有译文。

`export JOB --format txt --output "E:\Books\translation.txt" [--background]` 支持指定导出路径，
未指定格式时使用任务配置。同步结果含 `path`、`artifact_id`；后台完成后从操作查询的 `artifacts`
中读取产物。指定已有输出路径会按现有导出器行为覆盖该文件。编辑后请重新导出以更新文件。

离线验证可用 `import ... --fake`，不会消耗模型费用。真实翻译、审校和重译使用任务的模型配置；
`doctor --live-model` 会发起一次真实连接检查。密钥仍来自 Windows 凭据管理器或环境变量。

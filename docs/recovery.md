# 数据备份与恢复

FolioCross 的真实状态都在用户选定的 `workspace/` 中。界面显示的进度来自 SQLite，而不是
Worker 内存。直接关闭桌面窗口不会停止后台调度器和 Worker；重新打开后可以继续查看、暂停或
立即停止。Worker 意外退出也不会抹掉已经提交的段落。

## 安全暂停

“安全暂停”会等待当前模型请求结束，在批次边界停止。再次点击“继续翻译”时，Worker 会跳过
已有译文的段落。“立即停止 Worker”会终止进程并把任务标记为“已中断”；在途请求可能已经
计费，但尚未返回的结果不会写入段落版本。

后台操作记录不会在完成后删除。它们保留开始时间、Worker PID、退出码和错误，便于区分正常完成、
用户立即停止和进程异常退出。调度器进程在队列清空后自行退出；新操作会再次按需启动它。

## 备份

先暂停所有任务，再完整复制 `workspace/`。至少保留：

- `foliocross.db` 以及同目录可能存在的 `foliocross.db-wal`、`foliocross.db-shm`；
- `library/` 中的源书副本和规范化 EPUB；
- `jobs/` 中的任务产物；
- `exports/` 中的成品。

不要只复制数据库后继续让旧工作区运行。恢复时关闭 FolioCross，把整份备份放到一个目录，
再通过 `foliocross --workspace <目录> doctor --json` 检查。数据库迁移会按编号自动补齐。

## 不可恢复内容

模型 API Key 在 Windows 凭据管理器或环境变量中，不在工作区备份内。Wenyi 只读迁移也
不会复制 API Key。恢复到另一台机器后需要重新配置凭据，以及 KindleUnpack 或可选 Calibre。

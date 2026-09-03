# 从 Wenyi 只读导入

迁移器不会写入、移动或删除 Wenyi 仓库与状态。先列出状态：

```powershell
foliocross migrate-wenyi E:\Code\wenyi --json
```

选择一项状态和与其 SHA-256 匹配的原书后执行：

```powershell
foliocross migrate-wenyi E:\Code\wenyi `
  --state "E:\Code\wenyi\state\任务目录" `
  --source "E:\Books\原书.mobi" --json
```

如果 Wenyi 仍持有运行锁，导入会停止。MOBI/AZW 任务优先复制 Wenyi 已缓存的规范化 EPUB，
无需重新调用 Calibre。章节译文、润色前版本、术语和累计 token 会转换；旧 Review 的内部轮次
仍保留在 Wenyi 原目录。迁移报告写入 `workspace/imports/`，导入任务默认暂停。

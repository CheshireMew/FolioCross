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
无需重新调用转换后端。迁移器不会假设 Wenyi 的逻辑章节数等于 EPUB 物理资源数，而是按
`resource_href` 和规范化原文连续流校验；Wenyi 拆开的长段会重新合并到模板段落。章节译文、
润色前版本、全书分析、术语、未解决的术语冲突、冻结快照和累计 token 会转换；原书旁
`output` 目录中与该源文件同名的 EPUB、DOCX、HTML、TXT 或 Markdown 译本会复制到
FolioCross 的 `exports/<book_id>/wenyi-import/` 并登记为任务产物。旧 Review 的内部轮次仍保留在
Wenyi 原目录。迁移报告写入 `workspace/imports/` 并登记为任务产物，导入任务默认暂停，报告中
同时记录映射问题与迁移前后源文件哈希校验。

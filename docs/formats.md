# 格式兼容

## EPUB

导入时读取 OPF manifest 和 spine，以 XHTML 物理资源和块序号建立稳定定位。行内标签、图片、
普通链接及脚注链接会转换成受保护标记，翻译后恢复原 HTML。导出复制原 EPUB 包，只替换正文
块和语言元数据，因此 CSS、图片、封面、目录及未处理资源保持不变。

## MOBI/AZW

MOBI、AZW/AZW3/AZW4、PRC 等非原生格式调用外部 Calibre `ebook-convert` 规范化为 EPUB。
转换结果按原文件 SHA-256 缓存。FolioCross 不移除 DRM；受保护文件会明确失败。

## DOCX

正文段落、标题、列表和表格单元格会进入翻译。导出以原 DOCX 为模板，并在原段落中按原 run
比例分配译文，以尽量保留格式和包内其他对象。文本框和修订记录会在导入警告中明确说明。

## 其他格式

FB2、HTML、TXT 和 Markdown 会转换成统一章节模型。它们可以输出为 EPUB、DOCX、HTML、
TXT 或 Markdown。首版不支持 PDF 和 SRT。

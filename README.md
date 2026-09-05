<!-- readme-header:start -->

<p align="center">
  <img src="./docs/assets/logo.svg" width="84" alt="FolioCross">
</p>

<h1 align="center">FolioCross</h1>

<p align="center">
  <strong>在本地管理整本书翻译，保留书籍结构，随时编辑与续译。</strong>
</p>

<p align="center">
  <strong>中文</strong> · <a href="./README.en.md">English</a> · <a href="./README.ja.md">日本語</a> | <a href="./docs/cli.md">文档</a> | <a href="./CONTRIBUTING.md">贡献</a> | <a href="https://github.com/CheshireMew/FolioCross/issues">反馈</a>
</p>

<p align="center">
  <a href="https://x.com/0xCheshire" title="X"><img src="https://img.shields.io/badge/X-%400xCheshire-000000?logo=x&amp;logoColor=white" alt="X：@0xCheshire"></a>
  <a href="https://t.me/CheshireBTC" title="Telegram"><img src="https://img.shields.io/badge/Telegram-CheshireBTC-26A5E4?logo=telegram&amp;logoColor=white" alt="Telegram：CheshireBTC"></a>
  <a href="https://blog.blacknico.com/" title="Blog"><img src="https://img.shields.io/badge/Blog-blog.blacknico.com-2E7D32?logo=rss&amp;logoColor=white" alt="博客：blog.blacknico.com"></a>
  <a href="https://blacknico.com/" title="Homepage"><img src="https://img.shields.io/badge/Home-blacknico.com-1F6FEB?logo=googlechrome&amp;logoColor=white" alt="个人主页：blacknico.com"></a>
</p>

<p align="center">
  <a href="https://github.com/CheshireMew/FolioCross/stargazers"><img src="https://img.shields.io/github/stars/CheshireMew/FolioCross?style=flat" alt="GitHub Stars"></a>
  <a href="https://github.com/CheshireMew/FolioCross/forks"><img src="https://img.shields.io/github/forks/CheshireMew/FolioCross?style=flat" alt="GitHub Forks"></a>
  <a href="https://github.com/CheshireMew/FolioCross/blob/main/LICENSE"><img src="https://img.shields.io/github/license/CheshireMew/FolioCross?style=flat" alt="Repository License"></a>
</p>

<!-- readme-header:end -->

## 把一本外文书，译成可以继续阅读和编辑的书

FolioCross 是面向 Windows 的整本书翻译桌面应用。导入书籍后，它先整理全书概览和术语，再分批翻译正文，最后导出译本。书库、任务进度、原译文对照、人工修改和调用费用都在同一个工作台里。

书籍和任务状态保存在本地；真实翻译会把相关文本发送到你配置的模型 API。当前从源码运行，尚未提供安装包。

## 能做什么

- **保留书的结构。** EPUB 以原书为模板回填，保留图片、CSS、阅读顺序、链接和脚注，并同步目录标题；DOCX 保留原文件包中的图片、样式和其他部件。
- **长任务可以接着做。** 多本书进入持久队列，后台进程独立运行，关闭窗口后仍会继续。支持安全暂停、立即停止和恢复进度。
- **修改有记录，也有保护。** 对照原文编辑、比较版本、恢复历史或单段重译；人工保存的段落会锁定，整本自动翻译不会悄悄覆盖。
- **术语和审校由你控制。** 译前建立全书概览与术语表。深度审校需要主动启动，只生成问题列表，由你决定是否采纳。
- **看得见用量。** 开始前查看估算，运行后按阶段、模型和请求查看 token、缓存、重试与可计算费用，并可设置预算。
- **桌面与 CLI 共用任务。** 桌面提供中英文界面、缩放、预览和通知；JSON CLI 供脚本或外部 Agent 查询、编辑和调度，无需直接操作数据库。

默认“稳妥加速”模式使用项目配置中的 `deepseek-v4-flash`，关闭 thinking，跨章节有限并发，失败段落定向修复。它不会自动追加第二遍全文润色。

## 支持的格式

| 输入 | 处理说明 |
| --- | --- |
| EPUB | 原结构回填，适合保留电子书阅读体验 |
| DOCX | 按原文档顺序翻译段落、标题、列表和表格 |
| FB2、HTML、TXT、Markdown | 解析为章节与段落，可导出为支持的格式 |
| MOBI、AZW/AZW3/AZW4、PRC | 需要独立 KindleUnpack 环境，或外部 Calibre 转换 |

输出支持 **EPUB、DOCX、HTML、TXT、Markdown**。跨格式导出不等于原版式完全复刻；DOCX 文本框、修订记录等限制见[格式兼容说明](docs/formats.md)。Kindle 输入须无 DRM；不支持 PDF 和 SRT。

## 从源码启动

需要 Windows、Python 3.10 或以上、Git 和 [uv](https://docs.astral.sh/uv/getting-started/installation/)。在 PowerShell 中运行以下命令；示例将依赖和缓存放在 D 盘，你可以换成自己的工具目录。

```powershell
git clone https://github.com/CheshireMew/FolioCross.git
cd FolioCross

$env:UV_CACHE_DIR = 'D:\Tools\uv-cache'
$env:UV_PROJECT_ENVIRONMENT = 'D:\Tools\venvs\FolioCross'
uv sync --locked
uv run foliocross doctor --json
uv run foliocross app
```

首次运行时，`doctor` 可能提示尚未配置 API Key。打开应用的“设置”，将 DeepSeek API Key 保存到 Windows 凭据管理器；也可以通过当前终端的 `DEEPSEEK_API_KEY` 环境变量提供。再运行 `doctor` 查看检查结果。EPUB、DOCX 和文本格式不需要安装 Kindle 转换工具。

默认数据目录是**当前工作目录下的 `workspace/`**，包含原书副本、任务数据库、日志与导出文件，已被 Git 忽略。需要固定到其他位置时，在启动前设置 `FOLIOCROSS_WORKSPACE`；GUI 和 CLI 使用同一个目录才能看到同一批任务。

### 翻译第一本书

1. 在“设置”中配置 API Key，然后导入书籍，确认目标语言、导出格式和费用估算。
2. 直接开始翻译，或选择只完成译前准备后暂停，先检查全书概览和术语。
3. 在任务页查看进度、对照原译文，编辑需要调整的段落；保存后的人工修改会锁定。
4. 完成后预览并打开导出文件。后续修改译文后，重新导出才会更新成品。

`Ctrl+O` 导入，`Ctrl+,` 打开设置，`Ctrl+S` 保存编辑，`Ctrl+Shift+P` 开始或安全暂停。关闭窗口不会停止后台任务；需要停下时使用任务控制。备份与异常恢复见[数据恢复](docs/recovery.md)。

### 可选：Kindle 格式

KindleUnpack 通过独立 Python 进程运行，不需要把它装进 FolioCross 的依赖环境：

```powershell
python -m venv D:\Tools\venvs\FolioCross-KindleUnpack
D:\Tools\venvs\FolioCross-KindleUnpack\Scripts\python.exe -m pip install mobi==0.4.1
$env:FOLIOCROSS_KINDLEUNPACK_PYTHON = 'D:\Tools\venvs\FolioCross-KindleUnpack\Scripts\python.exe'
```

转换优先使用 KindleUnpack，失败后尝试可选的外部 Calibre `ebook-convert`。转换结果按原文件内容缓存；两者均不随本仓库分发。

## 用 CLI 或外部 Agent 操作

以下命令在仓库目录执行。把尖括号占位符换成前一步 JSON 返回的实际 ID；默认目标语言为简体中文。

```powershell
uv run foliocross import "E:\Books\book.epub" --json
uv run foliocross run <job-id> --background --json
uv run foliocross operations wait <operation-id> --timeout 30 --json
uv run foliocross jobs status <job-id> --json
```

后台提交返回 `operation_id`；等待超时不会终止任务。继续查询操作和书籍任务状态，完成后从结果读取产物位置。

```powershell
# 查看内容与版本；编辑前读取实际版本号
uv run foliocross segments list <job-id> --limit 50 --json
uv run foliocross segments show <segment-id> --json
uv run foliocross segments edit <segment-id> --text-file "E:\Books\revision.txt" --expected-version <version> --json

# 主动审校前查看估算；编辑后重新导出
uv run foliocross review <job-id> --estimate --json
uv run foliocross export <job-id> --format epub --json
```

[CLI 文档](docs/cli.md)包含暂停与恢复、术语导入导出、历史恢复、问题处理、单段重译和统一错误格式。导入时加 `--fake` 可试跑离线流程；它使用模拟译文，不代表真实翻译质量。已有 Wenyi v0.5.2 状态可按[迁移说明](docs/migration-wenyi.md)复制导入，原状态保持不变。

## 文档与开发

| 想了解什么 | 入口 |
| --- | --- |
| 命令、JSON 返回与外部 Agent 调用 | [命令行接口](docs/cli.md) |
| 输入输出、结构保留与格式限制 | [格式兼容](docs/formats.md) |
| 用量、价格与预算 | [用量与费用](docs/costs.md) |
| 备份、中断和恢复 | [数据恢复](docs/recovery.md) |
| 旧项目状态迁移 | [Wenyi 迁移](docs/migration-wenyi.md) |
| 代码结构与已有验证记录 | [架构](docs/architecture.md) · [验收记录](docs/acceptance.md) |
| 提交改动与本地检查 | [贡献指南](CONTRIBUTING.md) |

## 许可证与致谢

FolioCross 采用 [MIT 许可证](LICENSE)。部分格式处理与长文本翻译思路改编自 MIT 许可的 [Wenyi v0.5.2](https://github.com/BigDawnGhost/wenyi)，详细边界见 [NOTICE](NOTICE)。KindleUnpack 和 Calibre 是独立外部工具，各自遵循原许可证。

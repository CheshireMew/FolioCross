# FolioCross

FolioCross 是一个本地优先的整本书翻译工作台。它把图书解析、全书理解、术语统一、
有限并发翻译、人工编辑、用量核算和格式回填放在同一个 Windows 桌面应用中。

默认“稳妥加速”模式使用 DeepSeek Flash 直接翻译：译前建立全书概览和术语表，正文
跨章节有限并发，失败段落才定向修复；不会暗中执行第二遍全文润色或自动深度审校。

## 当前能力

- 输入：EPUB、MOBI、AZW/AZW3/AZW4、FB2、HTML、TXT、Markdown、DOCX。
- 输出：EPUB、DOCX、HTML、TXT、Markdown。
- EPUB 以原书为模板回填，保留包结构、CSS、图片、锚点和脚注，并同步翻译目录标题。
- MOBI/AZW3 默认通过独立 KindleUnpack 环境转换，Calibre 只是兼容性兜底；规范化 EPUB 按原文件 SHA-256 缓存。
- 多本任务自动排队、断点续跑、安全暂停、人工段落锁、撤销/恢复、版本对比和质量问题列表。
- 新建任务时可先查看 token/费用估算，直接开始或只完成译前准备后暂停。
- 单段重译、历史恢复、术语显式批量应用和用户主动启动的深度审校。
- 每次模型调用都记录实际模型、阶段、章节、token、缓存、重试和可计算费用，并可查看请求明细。
- 桌面端提供简体中文和英文界面、界面缩放、封面、应用内预览与完成通知。
- 提供稳定 JSON CLI，并支持只读导入 Wenyi v0.5.2 状态。

PDF、SRT、云端账户、团队协作和内置聊天不在当前范围内。

## 本机开发环境

本项目尚未打包，直接从源码运行。当前机器的依赖全部放在 D 盘：

```powershell
$env:UV_CACHE_DIR = 'D:\Tools\uv-cache'
$env:UV_PROJECT_ENVIRONMENT = 'D:\Tools\venvs\FolioCross'
$env:UV_PYTHON = 'D:\Tools\Python310\python.exe'
$env:UV_NO_MANAGED_PYTHON = '1'

D:\Tools\uv\Scripts\uv.exe sync --group dev
D:\Tools\uv\Scripts\uv.exe run foliocross doctor
D:\Tools\uv\Scripts\uv.exe run foliocross app
```

本机 KindleUnpack 独立环境位于 `D:\Tools\venvs\FolioCross-KindleUnpack`。它负责无 DRM 的
MOBI/KF8 拆包；FolioCross 只启动其独立进程，不把 GPL 代码放入 MIT 项目。Calibre 便携版位于
`D:\Tools\Calibre\Calibre Portable`，只在 KindleUnpack 失败时作为可选兜底。两者都不进入仓库。

若另一台 Windows 机器没有这个独立环境，可在 D 盘创建：

```powershell
D:\Tools\Python310\python.exe -m venv D:\Tools\venvs\FolioCross-KindleUnpack
D:\Tools\venvs\FolioCross-KindleUnpack\Scripts\python.exe -m pip install mobi==0.4.1
```

也可以用 `FOLIOCROSS_KINDLEUNPACK_PYTHON` 指向其他独立环境的 `python.exe`。两种 Kindle
后端都没有安装时，EPUB、DOCX、FB2、HTML 和文本格式仍可正常使用。

默认工作区是仓库下的 `workspace/`，整目录已被 Git 忽略。可以通过
`--workspace` 或 `FOLIOCROSS_WORKSPACE` 改用其他位置。

## DeepSeek API Key

推荐在“设置”页面保存到 Windows 凭据管理器。也可以只为当前终端设置：

```powershell
$env:DEEPSEEK_API_KEY = '你的 API Key'
```

API Key 不写入配置、数据库日志或 Git。默认模型角色均为 `deepseek-v4-flash`，
`thinking` 关闭。

## CLI 快速使用

```powershell
# 环境检查
foliocross doctor --json

# 导入书籍；返回 book_id 和 job_id
foliocross import "E:\Books\book.epub" --json

# 开始或恢复任务（可传 book_id 或 job_id）
foliocross run <book-or-job-id> --json

# 查询、暂停和恢复
foliocross jobs status <job-id> --json
foliocross jobs pause <job-id> --json
foliocross jobs resume <job-id> --json

# 导入、导出并明确刷新冻结术语版本
foliocross glossary import <book-or-job-id> terms.json --json
foliocross glossary export <book-or-job-id> --output terms.json --json
foliocross glossary refresh <book-or-job-id> --json

# 重新导出
foliocross export <job-id> --format epub --json

# 主动审校前先看估算；审校只生成问题，不直接覆盖译文
foliocross review <job-id> --estimate --json
foliocross review <job-id> --json

# 单段重译
foliocross retranslate <job-id> <segment-id> --instruction "保持简洁" --json
```

离线验证可在导入时加 `--fake`，不会发起网络请求。

更多说明见 [架构](docs/architecture.md)、[命令行](docs/cli.md)、
[格式兼容](docs/formats.md)、[用量与费用](docs/costs.md)和
[Wenyi 迁移](docs/migration-wenyi.md)。[数据恢复](docs/recovery.md)说明如何备份、恢复和处理
意外中断。

## 开发验证

```powershell
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
git diff --check
```

FolioCross 采用 MIT 许可证。部分格式处理思路改编自 MIT 许可的 Wenyi v0.5.2，
详见 [NOTICE](NOTICE)。KindleUnpack 和 Calibre 都是独立外部工具，不随 FolioCross 源码合并。

<!-- readme-header:start -->

<p align="center">
  <img src="./docs/assets/logo.svg" width="84" alt="FolioCross">
</p>

<h1 align="center">FolioCross</h1>

<p align="center">
  <strong>Translate complete books with structure preservation, manual editing, and resumable local tasks.</strong>
</p>

<p align="center">
  <a href="./README.md">中文</a> · <strong>English</strong> · <a href="./README.ja.md">日本語</a> | <a href="./docs/cli.md">文档</a> | <a href="./CONTRIBUTING.md">贡献</a> | <a href="https://github.com/CheshireMew/FolioCross/issues">反馈</a>
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

## Translate a whole book, then keep reading and editing

FolioCross is a Windows desktop application for translating complete books. It builds a book overview and glossary, translates text in batches, and exports the translated book. Your library, progress, source and translation, manual edits, and request costs stay in one workspace.

Books and task state are stored locally. Real translation sends relevant text to your configured model API. The app currently runs from source; no installer is provided.

## What it does

- **Preserves structure.** EPUB export fills the original package while retaining images, CSS, reading order, links, and notes, and updates TOC titles. DOCX retains images, styles, and other original package parts.
- **Resumes long tasks.** A persistent queue handles multiple books in independent background processes. Closing the window does not stop translation. Pause, stop, and resume controls are available.
- **Protects manual edits.** Edit beside the source, compare versions, restore history, or retranslate a segment. Manually saved segments are locked against automatic whole-book translation.
- **Keeps review explicit.** Preparation builds an overview and glossary. Deep review runs only when requested and produces issues for you to accept or dismiss.
- **Tracks usage.** Inspect estimates before starting and tokens, cache hits, retries, and calculable costs by stage, model, and request afterward. Budget limits are supported.
- **Shares tasks between GUI and CLI.** The desktop has Chinese and English interfaces, scaling, preview, and notifications. The JSON CLI lets scripts and external agents query, edit, and schedule work without accessing SQLite directly.

The default “Steady acceleration” mode uses the project's configured `deepseek-v4-flash`, with thinking disabled and bounded concurrency across chapters. Failed segments receive targeted repairs; a second full-book polishing pass is not added automatically.

## Formats

| Input | Handling |
| --- | --- |
| EPUB | Fills the original structure to preserve the reading experience |
| DOCX | Translates paragraphs, headings, lists, and tables in document order |
| FB2, HTML, TXT, Markdown | Parses chapters and segments for export to supported formats |
| MOBI, AZW/AZW3/AZW4, PRC | Requires a separate KindleUnpack environment or external Calibre |

Outputs: **EPUB, DOCX, HTML, TXT, Markdown**. Cross-format export does not guarantee identical layout. See [format support](docs/formats.md) for limitations such as DOCX text boxes and tracked changes. Kindle input must be DRM-free. PDF and SRT are unsupported.

## Run from source

Requires Windows, Python 3.10 or later, Git, and [uv](https://docs.astral.sh/uv/getting-started/installation/). Run in PowerShell. These examples put dependencies and caches on D:; adjust the tool directories to your machine.

```powershell
git clone https://github.com/CheshireMew/FolioCross.git
cd FolioCross

$env:UV_CACHE_DIR = 'D:\Tools\uv-cache'
$env:UV_PROJECT_ENVIRONMENT = 'D:\Tools\venvs\FolioCross'
uv sync --locked
uv run foliocross doctor --json
uv run foliocross app
```

On first use, `doctor` may report a missing API key. Open Settings and save your DeepSeek API key to Windows Credential Manager, or provide it through the current terminal's `DEEPSEEK_API_KEY` environment variable. Run `doctor` again to check the result. EPUB, DOCX, and text formats do not require Kindle conversion tools.

Data defaults to **`workspace/` under the current working directory**. It holds source copies, the task database, logs, and exports, and is ignored by Git. Set `FOLIOCROSS_WORKSPACE` before launching to choose a fixed location. The GUI and CLI must use the same directory to share tasks.

### Translate your first book

1. Configure your API key in Settings, import a book, and check the target language, export format, and cost estimate.
2. Start translation, or pause after preparation to inspect the overview and glossary first.
3. Follow progress and edit segments beside the source. Saved manual edits are locked.
4. Preview and open the exported book when complete. Export again after further edits to update the output file.

Use `Ctrl+O` to import, `Ctrl+,` for Settings, `Ctrl+S` to save, and `Ctrl+Shift+P` to start or safely pause. Closing the window leaves background work running; use task controls to stop it. See [recovery](docs/recovery.md) for backups and interruptions.

### Optional: Kindle formats

KindleUnpack runs in a separate Python process, outside the FolioCross environment:

```powershell
python -m venv D:\Tools\venvs\FolioCross-KindleUnpack
D:\Tools\venvs\FolioCross-KindleUnpack\Scripts\python.exe -m pip install mobi==0.4.1
$env:FOLIOCROSS_KINDLEUNPACK_PYTHON = 'D:\Tools\venvs\FolioCross-KindleUnpack\Scripts\python.exe'
```

Conversion tries KindleUnpack first and falls back to the optional external Calibre `ebook-convert`. Results are cached by source content. Neither tool is distributed in this repository.

## CLI and external agents

Run these commands from the repository. Replace angle-bracket placeholders with actual IDs returned by the preceding JSON result. The default target language is Simplified Chinese.

```powershell
uv run foliocross import "E:\Books\book.epub" --json
uv run foliocross run <job-id> --background --json
uv run foliocross operations wait <operation-id> --timeout 30 --json
uv run foliocross jobs status <job-id> --json
```

Background submission returns an `operation_id`. A wait timeout does not stop the task. Query both operation and book task status, then read artifact locations from the completed result.

```powershell
# Read the current segment version before editing
uv run foliocross segments list <job-id> --limit 50 --json
uv run foliocross segments show <segment-id> --json
uv run foliocross segments edit <segment-id> --text-file "E:\Books\revision.txt" --expected-version <version> --json

# Estimate an explicit review; export again after edits
uv run foliocross review <job-id> --estimate --json
uv run foliocross export <job-id> --format epub --json
```

The [CLI reference](docs/cli.md) covers pause/resume, glossary exchange, revision restoration, review issues, retranslation, and structured errors. Import with `--fake` to try the offline flow; simulated output does not demonstrate translation quality. Existing Wenyi v0.5.2 state can be copied using the [migration guide](docs/migration-wenyi.md), leaving source state unchanged.

## Documentation and development

Detailed project documents are currently in Chinese.

| Topic | Guide |
| --- | --- |
| Commands, JSON results, external agents | [CLI reference](docs/cli.md) |
| Format preservation and limitations | [Formats](docs/formats.md) |
| Usage, pricing, budgets | [Costs](docs/costs.md) |
| Backups and interrupted tasks | [Recovery](docs/recovery.md) |
| Importing old project state | [Wenyi migration](docs/migration-wenyi.md) |
| Code structure and existing verification records | [Architecture](docs/architecture.md) · [Acceptance records](docs/acceptance.md) |
| Changes and local checks | [Contributing](CONTRIBUTING.md) |

## License and acknowledgements

FolioCross is [MIT licensed](LICENSE). Selected format-handling and long-form translation ideas are adapted from the MIT-licensed [Wenyi v0.5.2](https://github.com/BigDawnGhost/wenyi); see [NOTICE](NOTICE) for scope. KindleUnpack and Calibre are independent external tools under their own licenses.

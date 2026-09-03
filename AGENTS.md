# FolioCross repository guide

FolioCross is an independent Windows-first local desktop application for translating complete
books. The Python package is `foliocross`, the CLI is `foliocross`, and the GUI uses PySide6/QML.

- Do not modify, move, or delete `E:\Code\wenyi` or its state. Migration is copy-only.
- Do not commit anything under `workspace/`, credentials, source books, translations, or logs.
- Do not add PDF, SRT, a chat surface, an embedded agent runtime, cloud accounts, or a server.
- Long-running work belongs in a worker process; the GUI must stay responsive.
- SQLite state transitions, segment revisions, request usage, and artifacts are transactional.
- Manual segment revisions are locked and must never be silently replaced by automation.
- EPUB changes must preserve package metadata, spine order, images, CSS, TOC, anchors, and notes.
- Calibre remains an external executable. Do not copy, import, or statically link its source.
- API keys come from Windows Credential Manager or environment variables, never config or Git.
- Use `D:\Tools` for installed toolchains, virtual environments, and dependency caches.
- Do not package, publish, create remotes, or push unless the user explicitly asks.
- Before delivery run pytest, Ruff check, Ruff format check, and `git diff --check`.

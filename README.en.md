# FolioCross

FolioCross is a local-first desktop workspace for translating complete books. It combines book
parsing, book-wide context, terminology, bounded concurrent translation, manual editing, usage
accounting, and format-preserving export in one Windows application.

The default **Steady Acceleration** preset translates directly with DeepSeek Flash. It performs a
single preflight pass for summaries and terminology, translates separate chapters concurrently,
and repairs only segments that fail deterministic checks. Full-book polishing and deep review are
never enabled implicitly.

The desktop workflow includes a pre-run token/cost estimate, preparation-only mode, safe pause and
resume, per-segment retranslation, locked manual revisions, explicit glossary application, review
suggestions, and re-export to every supported output format.

Supported inputs are EPUB, DRM-free MOBI/AZW variants, FB2, HTML, text, Markdown, and DOCX.
Supported outputs are EPUB, DOCX, HTML, text, and Markdown. PDF and subtitles are intentionally
outside the current product boundary.

This repository currently runs from source and is not packaged. See the
[Chinese README](README.md) for the configured Windows development paths and CLI examples.
The machine-local Calibre Portable installation lives under `D:\Tools\Calibre` and is not bundled.

FolioCross is MIT licensed. See [NOTICE](NOTICE) for attribution and the Calibre boundary.

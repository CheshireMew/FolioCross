<!-- readme-header:start -->

<p align="center">
  <img src="./docs/assets/logo.svg" width="84" alt="FolioCross">
</p>

<h1 align="center">FolioCross</h1>

<p align="center">
  <strong>書籍の構造を保ちながら、一冊全体を翻訳・編集・再開できるローカルアプリ。</strong>
</p>

<p align="center">
  <a href="./README.md">中文</a> · <a href="./README.en.md">English</a> · <strong>日本語</strong> | <a href="./docs/cli.md">文档</a> | <a href="./CONTRIBUTING.md">贡献</a> | <a href="https://github.com/CheshireMew/FolioCross/issues">反馈</a>
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

## 一冊の本を翻訳し、そのまま読み、編集する

FolioCross は、書籍全体を翻訳する Windows 向けデスクトップアプリです。書籍を取り込むと、全体の概要と用語集を作成し、本文を分割して翻訳した後、訳本を書き出します。書庫、進捗、原文と訳文の比較、手動編集、API 利用料金を一つの作業画面で扱えます。

書籍とタスクの状態はローカルに保存されます。実際の翻訳では、関連するテキストが設定したモデル API に送信されます。現在はソースコードから実行する形式で、インストーラーは提供していません。

## 主な機能

- **書籍の構造を保持。** EPUB は元のパッケージに訳文を反映し、画像、CSS、読書順序、リンク、注釈を保持して目次の見出しも更新します。DOCX は元の画像、スタイル、その他のパッケージ部品を保持します。
- **長いタスクを再開。** 複数の書籍を永続キューで管理し、独立したバックグラウンドプロセスで処理します。ウィンドウを閉じても続行し、一時停止、停止、再開に対応します。
- **手動編集を保護。** 原文と比較しながら編集し、版の比較、履歴の復元、段落の再翻訳ができます。手動保存した段落はロックされ、全体の自動翻訳では上書きされません。
- **用語と校閲を管理。** 翻訳前に概要と用語集を作成します。詳細な校閲は明示的に開始した場合だけ実行し、提案の採用は利用者が決めます。
- **利用量を確認。** 開始前の見積もりと、実行後の段階別・モデル別・リクエスト別のトークン、キャッシュ、再試行、計算可能な料金を確認できます。予算も設定できます。
- **GUI と CLI で同じタスクを操作。** デスクトップは中国語・英語 UI、表示倍率、プレビュー、通知に対応します。JSON CLI からスクリプトや外部 Agent が照会、編集、実行でき、データベースを直接操作する必要はありません。

既定の「Steady acceleration」モードは、プロジェクト設定の `deepseek-v4-flash` を thinking 無効で使用します。章をまたぐ並列数を制限し、失敗した段落を個別に修復します。全文の追加推敲は自動実行しません。

## 対応形式

| 入力 | 処理 |
| --- | --- |
| EPUB | 元の構造に訳文を反映 |
| DOCX | 文書順に段落、見出し、リスト、表を翻訳 |
| FB2、HTML、TXT、Markdown | 章と段落に解析し、対応形式へ出力 |
| MOBI、AZW/AZW3/AZW4、PRC | 独立した KindleUnpack 環境、または外部 Calibre が必要 |

出力は **EPUB、DOCX、HTML、TXT、Markdown** に対応します。形式を変える場合、同一のレイアウトは保証されません。DOCX のテキストボックスや変更履歴などの制限は[形式の説明](docs/formats.md)を参照してください。Kindle 入力は DRM のないファイルに限ります。PDF と SRT は非対応です。

## ソースコードから起動

Windows、Python 3.10 以上、Git、[uv](https://docs.astral.sh/uv/getting-started/installation/) が必要です。PowerShell で以下を実行します。例では依存環境とキャッシュを D ドライブに置きます。保存先は環境に合わせて変更できます。

```powershell
git clone https://github.com/CheshireMew/FolioCross.git
cd FolioCross

$env:UV_CACHE_DIR = 'D:\Tools\uv-cache'
$env:UV_PROJECT_ENVIRONMENT = 'D:\Tools\venvs\FolioCross'
uv sync --locked
uv run foliocross doctor --json
uv run foliocross app
```

初回の `doctor` は API キー未設定を報告する場合があります。Settings から DeepSeek API キーを Windows 資格情報マネージャーに保存するか、現在のターミナルの `DEEPSEEK_API_KEY` 環境変数で指定してください。その後、再度 `doctor` で確認します。EPUB、DOCX、テキスト形式には Kindle 変換ツールは不要です。

データは既定で**現在の作業ディレクトリ内の `workspace/`** に保存されます。原書のコピー、タスクのデータベース、ログ、出力を含み、Git の対象外です。保存先を固定する場合は、起動前に `FOLIOCROSS_WORKSPACE` を設定します。GUI と CLI で同じタスクを扱うには同じ保存先を使用してください。

### 最初の一冊を翻訳する

1. Settings で API キーを設定し、書籍を取り込んで、翻訳先の言語、出力形式、料金見積もりを確認します。
2. 翻訳を開始するか、準備だけを実行して一時停止し、概要と用語集を確認します。
3. 進捗と原文・訳文を確認し、必要な段落を編集します。手動保存した段落はロックされます。
4. 完了後、出力をプレビューして開きます。後から訳文を変更した場合は、再出力して完成ファイルに反映します。

`Ctrl+O` で取り込み、`Ctrl+,` で設定、`Ctrl+S` で保存、`Ctrl+Shift+P` で開始または安全に一時停止できます。ウィンドウを閉じても処理は続くため、停止にはタスクの操作を使います。バックアップと中断時の対応は[復旧手順](docs/recovery.md)を参照してください。

### 任意：Kindle 形式

KindleUnpack は独立した Python プロセスで実行するため、FolioCross の依存環境に追加する必要はありません。

```powershell
python -m venv D:\Tools\venvs\FolioCross-KindleUnpack
D:\Tools\venvs\FolioCross-KindleUnpack\Scripts\python.exe -m pip install mobi==0.4.1
$env:FOLIOCROSS_KINDLEUNPACK_PYTHON = 'D:\Tools\venvs\FolioCross-KindleUnpack\Scripts\python.exe'
```

KindleUnpack を優先し、失敗時は任意の外部 Calibre `ebook-convert` を試します。変換結果は元ファイルの内容に基づいてキャッシュします。どちらのツールも本リポジトリには同梱しません。

## CLI と外部 Agent

以下はリポジトリ内で実行します。山括弧の値は、前の JSON 結果で返された実際の ID に置き換えてください。既定の翻訳先は簡体字中国語です。

```powershell
uv run foliocross import "E:\Books\book.epub" --json
uv run foliocross run <job-id> --background --json
uv run foliocross operations wait <operation-id> --timeout 30 --json
uv run foliocross jobs status <job-id> --json
```

バックグラウンド操作は `operation_id` を返します。待機がタイムアウトしてもタスクは停止しません。操作と書籍タスクの両方の状態を照会し、完了結果から出力先を取得します。

```powershell
# 編集前に段落の現在の版を取得
uv run foliocross segments list <job-id> --limit 50 --json
uv run foliocross segments show <segment-id> --json
uv run foliocross segments edit <segment-id> --text-file "E:\Books\revision.txt" --expected-version <version> --json

# 校閲の見積もりと、編集後の再出力
uv run foliocross review <job-id> --estimate --json
uv run foliocross export <job-id> --format epub --json
```

[CLI リファレンス](docs/cli.md)には、一時停止と再開、用語集の入出力、履歴復元、校閲指摘、段落の再翻訳、JSON エラー形式を記載しています。取り込み時の `--fake` はオフライン動作確認用です。模擬訳文であり、翻訳品質の証明ではありません。Wenyi v0.5.2 の既存状態は[移行手順](docs/migration-wenyi.md)でコピーして取り込めます。元の状態は変更しません。

## 文書と開発

詳細なプロジェクト文書は現在中国語です。

| 内容 | 文書 |
| --- | --- |
| コマンド、JSON、外部 Agent | [CLI](docs/cli.md) |
| 形式と構造保持の制限 | [対応形式](docs/formats.md) |
| 利用量、料金、予算 | [費用](docs/costs.md) |
| バックアップと中断 | [復旧](docs/recovery.md) |
| 旧プロジェクトの状態取り込み | [Wenyi 移行](docs/migration-wenyi.md) |
| コード構造と既存の検証記録 | [アーキテクチャ](docs/architecture.md) · [検証記録](docs/acceptance.md) |
| 変更の提出とローカル検証 | [貢献ガイド](CONTRIBUTING.md) |

## ライセンスと謝辞

FolioCross は [MIT ライセンス](LICENSE)です。形式処理と長文翻訳の一部の考え方は、MIT ライセンスの [Wenyi v0.5.2](https://github.com/BigDawnGhost/wenyi) を参考にしています。範囲は [NOTICE](NOTICE) を参照してください。KindleUnpack と Calibre は、それぞれのライセンスに従う独立した外部ツールです。

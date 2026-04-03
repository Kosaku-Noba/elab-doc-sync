# elab-doc-sync

Markdown ドキュメントを eLabFTW に同期する CLI ツール。

## 特徴

- 差分検知（SHA-256）で変更があるファイルだけ更新
- 画像の自動アップロード・URL 書き換え
- 2つの同期モード: `merge`（全結合→1エンティティ）/ `each`（1ファイル=1エンティティ）
- アイテム (`items`) と実験ノート (`experiments`) の両方に対応
- Windows / Linux 両対応

## インストール

```bash
mkdir doc_sync
cd doc_sync
uv venv
uv pip install git+https://github.com/Kosaku-Noba/elab-doc-sync.git
uv run elab-doc-sync init

=== elab-doc-sync セットアップ ===

eLabFTW の URL: #elabFTWのURLを入力
SSL 証明書を検証しますか？ [Y/n]: n
Markdown ファイルを置くディレクトリ（空欄で docs/）: 
同期する Markdown のファイルパターン（空欄で *.md）: 
同期モード — merge: 全ファイルを1つに結合 / each: 1ファイル=1ノート [merge]: each
送信先 — items: アイテム / experiments: 実験ノート [items]: items

テンプレートファイルを展開中...
  .gitignore を作成しました
  README.md を作成しました
  docs/ ディレクトリを作成しました

✅ 設定ファイルを作成しました: .elab-sync.yaml
```

次に、eLabFTW の API キーを設定してください。以下のいずれかの方法で設定できます:

### 方法 1: `.elab-sync.yaml` に直接記載（最も簡単）

`.elab-sync.yaml` の `elabftw` セクションに `api_key` を追加:

```yaml
elabftw:
  url: "https://your-elabftw.example.com"
  api_key: "your_api_key"
  verify_ssl: false
```

> **⚠️ 注意:** yaml に API キーを書く場合、`.gitignore` に `.elab-sync.yaml` が含まれていることを確認してください（`init` で自動追加済み）。

### 方法 2: 環境変数で設定（yaml より優先されます）

#### Linux / macOS

```bash
export ELABFTW_API_KEY="your_api_key"
```

永続化するには `~/.bashrc` 等に追記してください:
```bash
echo 'export ELABFTW_API_KEY="your_api_key"' >> ~/.bashrc
```

#### Windows (PowerShell)

現在のセッションのみ有効:
```powershell
$env:ELABFTW_API_KEY = "your_api_key"
```

永続化（ユーザー環境変数に保存、設定後 PowerShell を再起動）:
```powershell
[System.Environment]::SetEnvironmentVariable("ELABFTW_API_KEY", "your_api_key", "User")
```

準備ができたら以下で同期を開始できます:
```bash
uv run elab-doc-sync --dry-run  （確認）
uv run elab-doc-sync            （実行）
```

> **Note:** `uv pip install` でインストールした場合、コマンドは `uv run elab-doc-sync` で実行してください。

実行後のリポジトリ構成:
```
./
├── docs/           ← Markdown を置く
├── .elab-sync.yaml ← init で自動生成
├── .gitignore      ← init で自動生成
└── README.md       ← init で自動生成
```

## 開発

```bash
git clone https://github.com/Kosaku-Noba/elab-doc-sync.git
cd elab-doc-sync
uv sync
```

## 同期モード

### merge（デフォルト）

複数の md を結合して 1 エンティティに送信:

```yaml
targets:
  - title: "プロジェクトドキュメント"
    docs_dir: "docs/"
```

### each

各 md を個別のエンティティとして送信（タイトルはファイル名から自動取得）:

```yaml
targets:
  - docs_dir: "experiments/"
    mode: each
    entity: experiments
```

### 組み合わせ

```yaml
targets:
  - title: "プロジェクト概要"
    docs_dir: "docs/"
    mode: merge
    entity: items

  - docs_dir: "experiments/"
    mode: each
    entity: experiments
```

## 設定リファレンス

| キー | 必須 | デフォルト | 説明 |
|------|------|-----------|------|
| `elabftw.url` | ✅ | — | eLabFTW の URL |
| `elabftw.api_key` | — | — | API キー（環境変数 `ELABFTW_API_KEY` が優先） |
| `elabftw.verify_ssl` | — | `true` | SSL 検証 |
| `targets[].title` | merge時✅ | — | エンティティのタイトル |
| `targets[].docs_dir` | ✅ | — | Markdown のディレクトリ |
| `targets[].pattern` | — | `*.md` | Glob パターン |
| `targets[].mode` | — | `merge` | `merge` / `each` |
| `targets[].entity` | — | `items` | `items` / `experiments` |
| `targets[].id_file` | — | `.elab-sync-ids/default.id` | ID 保存先 |

サンプル: [`.elab-sync.yaml.example`](.elab-sync.yaml.example)

## ライセンス

MIT

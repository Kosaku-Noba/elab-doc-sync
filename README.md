# elab-doc-sync

Markdown ドキュメントを eLabFTW に同期する CLI ツール。`esync` エイリアスでも使えます。

## 特徴

- 差分検知（SHA-256）で変更があるファイルだけ更新
- 画像の自動アップロード・URL 書き換え
- 2つの同期モード: `merge`（全結合→1エンティティ）/ `each`（1ファイル=1エンティティ）
- アイテム (`items`) と実験ノート (`experiments`) の両方に対応
- eLabFTW からのプル（pull）・差分表示（diff）に対応
- Windows / Linux 両対応

## セットアップ（初回のみ）

### ① ツールをインストール

**uv を使う場合（推奨）:**

```bash
uv pip install git+https://github.com/Kosaku-Noba/elab-doc-sync.git
```

**pip を使う場合:**

```bash
pip install git+https://github.com/Kosaku-Noba/elab-doc-sync.git
```

### ② 設定ファイルを作る（質問に答えるだけ）

```bash
# uv の場合
uv run elab-doc-sync init

# pip の場合
elab-doc-sync init

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

### ③ API キーを設定する

eLabFTW → ユーザー設定 → API Keys でキーを作成し、`.elab-sync.yaml` の `api_key` にキーを貼ってください:

```yaml
elabftw:
  url: "https://your-elabftw.example.com"
  api_key: "ここにキーを貼る"
  verify_ssl: false
```

## コマンド一覧

| コマンド | 説明 |
|---------|------|
| `esync` | ローカル → eLabFTW に同期（push） |
| `esync pull` | eLabFTW → ローカルに取得 |
| `esync pull --id 42` | 指定 ID のエンティティを取得 |
| `esync diff` | ローカルと eLabFTW の差分を表示 |
| `esync status` | 同期状態を確認 |
| `esync tag list` | リモートのタグ一覧を表示 |
| `esync tag add "タグ"` | タグを追加 |
| `esync tag remove "タグ"` | タグを外す |
| `esync metadata get` | メタデータを表示 |
| `esync metadata set k=v` | メタデータを設定 |
| `esync entity-status show` | エンティティのステータスを表示 |
| `esync entity-status set <ID>` | ステータスを変更 |
| `esync list` | リモートのアイテム一覧を表示 |
| `esync list --entity experiments` | 実験ノート一覧を表示 |
| `esync link <ID>` | 既存リモートエンティティとローカルを紐付け |
| `esync verify` | ローカルとリモートの整合性チェック |
| `esync init` | 対話的に設定ファイルを作成 |
| `esync update` | ツールを最新版に更新 |
| `esync log` | 同期ログを表示 |
| `esync clone` | eLabFTW からプロジェクトを構築 |
| `esync whoami` | 現在のユーザー情報を表示 |
| `esync new --list` | テンプレート一覧を表示 |
| `esync new --template-id <ID>` | テンプレートからファイル作成 |
| `esync --dry-run` | 実行せずに同期内容を確認 |
| `esync --force` | 変更がなくても強制同期 |
| `esync -t "名前"` | 特定のターゲットだけ同期 |

> **Note:** `esync` は `elab-doc-sync` のエイリアスです。どちらでも同じように使えます。
> uv でインストールした場合は `uv run esync` のように実行してください。

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
| `elabftw.api_key` | ✅ | — | API キー（環境変数 `ELABFTW_API_KEY` が優先） |
| `elabftw.verify_ssl` | — | `true` | SSL 検証 |
| `targets[].title` | merge時✅ | — | エンティティのタイトル |
| `targets[].docs_dir` | ✅ | — | Markdown のディレクトリ |
| `targets[].pattern` | — | `*.md` | Glob パターン |
| `targets[].mode` | — | `merge` | `merge` / `each` |
| `targets[].entity` | — | `items` | `items` / `experiments` |
| `targets[].id_file` | — | `.elab-sync-ids/default.id` | ID 保存先 |
| `targets[].tags` | — | `[]` | push 時に自動追加するタグ（追記のみ、既存タグは外さない） |

サンプル: [`.elab-sync.yaml.example`](.elab-sync.yaml.example)

## 困ったとき

| メッセージ | やること |
|-----------|---------|
| `API キーが設定されていません` | 上の③をやる |
| `設定ファイルが見つかりません` | `esync init` を実行 |
| `ファイルがありません` | `docs/` に `.md` ファイルを置く |

## 開発

```bash
git clone https://github.com/Kosaku-Noba/elab-doc-sync.git
cd elab-doc-sync
uv sync
```

## ライセンス

MIT

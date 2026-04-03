# ドキュメント同期

`docs/` の Markdown を eLabFTW に自動同期します。

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
| `esync update` | ツールを最新版に更新 |
| `esync --dry-run` | 実行せずに同期内容を確認 |
| `esync --force` | 変更がなくても強制同期 |
| `esync -t "名前"` | 特定のターゲットだけ同期 |

> **Note:** `esync` は `elab-doc-sync` のエイリアスです。どちらでも同じように使えます。
> uv でインストールした場合は `uv run esync` のように実行してください。

## 困ったとき

| メッセージ | やること |
|-----------|---------|
| `API キーが設定されていません` | 上の③をやる |
| `設定ファイルが見つかりません` | `esync init` を実行 |
| `ファイルがありません` | `docs/` に `.md` ファイルを置く |

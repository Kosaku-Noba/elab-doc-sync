# elab-doc-sync

Markdown ドキュメントを eLabFTW に同期する CLI ツール。

## 特徴

- 差分検知（SHA-256）で変更があるファイルだけ更新
- 画像の自動アップロード・URL 書き換え
- 2つの同期モード: `merge`（全結合→1エンティティ）/ `each`（1ファイル=1エンティティ）
- アイテム (`items`) と実験ノート (`experiments`) の両方に対応
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

## 使い方（毎回）

```bash
# uv の場合
uv run elab-doc-sync            # 同期
uv run elab-doc-sync --dry-run  # 同期前に確認

# pip の場合
elab-doc-sync                   # 同期
elab-doc-sync --dry-run         # 同期前に確認
```

## その他のコマンド

```bash
elab-doc-sync status     # 同期状態を確認
elab-doc-sync --force    # 変更がなくても強制同期
elab-doc-sync -t "名前"  # 特定のターゲットだけ同期
```

> **Note:** uv でインストールした場合は各コマンドの前に `uv run` を付けてください。

## 困ったとき

| メッセージ | やること |
|-----------|---------|
| `API キーが設定されていません` | 上の③をやる |
| `設定ファイルが見つかりません` | `elab-doc-sync init` を実行 |
| `ファイルがありません` | `docs/` に `.md` ファイルを置く |

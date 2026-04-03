# ドキュメント同期

`docs/` の Markdown を eLabFTW に自動同期します。

## セットアップ（初回のみ）

```bash
mkdir doc_sync
cd doc_sync
uv venv
uv pip install git+https://github.com/Kosaku-Noba/elab-doc-sync.git
uv run elab-doc-sync init

=== elab-doc-sync セットアップ ===

eLabFTW の URL: #elabFTWのURLを入力
SSL 証明書を検証しますか？ [Y/n]: n
ドキュメントディレクトリ [docs/]: 
ファイルパターン [*.md]: 
同期モード — merge: 全ファイルを1つに結合 / each: 1ファイル=1ノート [merge]: each
送信先 — items: アイテム / experiments: 実験ノート [items]: items

テンプレートファイルを展開中...
  .gitignore を作成しました
  README.md を作成しました
  docs/ ディレクトリを作成しました

✅ 設定ファイルを作成しました: .elab-sync.yaml
```

### ③ API キーを設定する

eLabFTW → ユーザー設定 → API Keys でキーを作成し、以下のいずれかの方法で設定してください。

`.elab-sync.yaml` に直接記載（最も簡単）**

`.elab-sync.yaml` の `elabftw` セクションに `api_key` を追加:

```yaml
elabftw:
  url: "https://your-elabftw.example.com"
  api_key: "ここにキーを貼る"
  verify_ssl: false
```


## 使い方（毎回）

```bash
# 同期
uv run elab-doc-sync

# 同期前に確認したいとき
uv run elab-doc-sync --dry-run
```

## その他のコマンド

```bash
uv run elab-doc-sync status     # 同期状態を確認
uv run elab-doc-sync --force    # 変更がなくても強制同期
uv run elab-doc-sync -t "名前"  # 特定のターゲットだけ同期
```

## 困ったとき

| メッセージ | やること |
|-----------|---------|
| `API キーが設定されていません` | 上の③をやる |
| `設定ファイルが見つかりません` | `uv run elab-doc-sync init` を実行 |
| `ファイルがありません` | `docs/` に `.md` ファイルを置く |

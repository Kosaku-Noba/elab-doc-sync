# ドキュメント同期

Markdown で書いた実験ノートやリソースを eLabFTW に自動同期するツールです。

```
ローカル（Markdown）  ←→  eLabFTW（リソース / 実験ノート）
       esync                esync pull --id 42 --entity items
```

## クイックスタート（5分で完了）

### ① インストール

```bash
# uv（推奨）
uv pip install git+https://github.com/Kosaku-Noba/elab-doc-sync.git

# pip
pip install git+https://github.com/Kosaku-Noba/elab-doc-sync.git
```

### ② 初期設定（質問に答えるだけ）

```bash
uv run esync init
# または: esync init
```

eLabFTW の URL、同期モード、送信先を聞かれるので入力してください。

### ③ API キーを設定

eLabFTW → ユーザー設定 → API Keys でキーを作成し、`.elab-sync.yaml` に貼ります:

```yaml
elabftw:
  url: "https://your-elabftw.example.com"
  api_key: "ここにキーを貼る"
  verify_ssl: true   # 自己署名証明書の場合のみ false に変更
```

> 💡 環境変数 `ELABFTW_API_KEY` でも設定できます（こちらが優先）

### ④ 書いて同期

```bash
# docs/ に Markdown を書く
echo "# 実験記録" > docs/experiment.md

# eLabFTW に同期
uv run esync
# → ✅ リソース #42 を更新しました
```

これだけです！以降は `docs/` のファイルを編集して `esync` を実行するだけで差分が同期されます。

## よく使うコマンド

| やりたいこと | コマンド |
|---|---|
| ローカル → eLabFTW に同期 | `esync` |
| eLabFTW → ローカルに取得 | `esync pull --id 42 --entity items` |
| 複数 ID を一括取得 | `esync pull --id 42 --id 43 --entity items` |
| 実験ノートとして取得 | `esync pull --id 42 --entity experiments` |
| 差分を確認 | `esync diff` |
| 同期状態を確認 | `esync status` |
| 実行せずにプレビュー | `esync --dry-run` |
| 変更がなくても強制同期 | `esync --force` |
| リモートの一覧を見る | `esync list` |
| タグを追加 | `esync tag add "タグ名"` |
| メタデータを設定 | `esync metadata set key=value` |
| テンプレートからファイル作成 | `esync new --template-id 1` |
| 整合性チェック | `esync verify` |
| ユーザー情報を確認 | `esync whoami` |
| ツールを更新 | `esync update` |

> `esync` は `elab-doc-sync` のエイリアスです。
> uv の場合は `uv run esync` で実行してください。

## 同期モード

| モード | 動作 | 設定例 |
|---|---|---|
| `merge`（デフォルト） | 複数 md を結合して 1 つのリソースに送信 | `mode: merge` |
| `each` | 各 md を個別のリソース/実験ノートとして送信 | `mode: each` |

## 困ったとき

| メッセージ | やること |
|---|---|
| `API キーが設定されていません` | 上の③をやる |
| `設定ファイルが見つかりません` | `esync init` を実行 |
| `ファイルがありません` | `docs/` に `.md` ファイルを置く |
| `--id を指定してください` | `esync pull --id <番号> --entity items` で ID を指定 |

## もっと詳しく

- 全コマンドの詳細: [CLI リファレンス](https://github.com/Kosaku-Noba/elab-doc-sync/blob/main/docs/05_CLI_REFERENCE.md)
- 設定ファイルの全オプション: [設定ファイル仕様](https://github.com/Kosaku-Noba/elab-doc-sync/blob/main/docs/04_CONFIGURATION.md)

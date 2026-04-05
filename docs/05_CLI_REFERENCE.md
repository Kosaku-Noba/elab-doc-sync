# CLI リファレンス

→ [設定ファイル](04_CONFIGURATION.md) | [API リファレンス](06_API_REFERENCE.md)

## コマンド一覧

| コマンド | 説明 |
|---|---|
| `esync` | ローカル → eLabFTW に同期（push） |
| `esync pull` | eLabFTW → ローカルに取得 |
| `esync pull --id 42` | 指定 ID のエンティティを取得 |
| `esync diff` | ローカルと eLabFTW の差分を表示 |
| `esync status` | 同期状態を確認 |
| `esync init` | 対話的に設定ファイルを作成 |
| `esync update` | ツールを最新版に更新 |
| `esync log` | 同期ログを表示 |
| `esync clone` | eLabFTW からプロジェクトを構築 |

> `esync` は `elab-doc-sync` のエイリアス。uv の場合は `uv run esync`。

## グローバルオプション

| オプション | 短縮 | 型 | デフォルト | 説明 |
|---|---|---|---|---|
| `--config` | `-c` | string | `.elab-sync.yaml` | 設定ファイルのパス |
| `--target` | `-t` | string | 全ターゲット | 同期対象のターゲット名 |
| `--force` | `-f` | flag | false | 変更がなくても強制同期 / pull 時は上書き |
| `--dry-run` | `-n` | flag | false | 実行せずに同期内容を確認 |

## コマンド詳細

### `esync`（push）

ローカルの Markdown を eLabFTW に同期する。デフォルト動作。

```bash
esync                    # 全ターゲットを同期
esync -t "名前"          # 特定ターゲットのみ
esync --dry-run          # プレビュー
esync --force            # 強制同期
```

処理フロー: ファイル収集 → 差分検知 → 画像アップロード → HTML 変換 → API 送信。
詳細は [同期エンジン](07_SYNC_ENGINE.md) を参照。

### `esync pull`

eLabFTW のエンティティをローカルに Markdown として保存する。

```bash
esync pull               # 全ターゲットを取得
esync pull --id 42       # 指定 ID を取得
esync pull --force       # 既存ファイルを上書き
```

- each モード: mapping.json の ID → 全件取得の順で対象を決定
- merge モード: 保存済み ID または `--id` で指定

### `esync diff`

ローカルと eLabFTW 上の内容を unified diff 形式で比較する。

```bash
esync diff               # 全ターゲット
esync diff -t "名前"     # 特定ターゲット
```

### `esync status`

各ターゲットの変更有無・同期先エンティティ ID を表示する。

```bash
esync status
```

出力例:
```
  [My Docs] 変更あり（アイテム #42）
  [API Ref] 最新（アイテム #43）
```

### `esync init`

対話形式で `.elab-sync.yaml` を生成する。テンプレートファイルも展開する。
詳細は [セットアップガイド](03_SETUP_GUIDE.md) を参照。

### `esync log`

同期ログを表示する。

```bash
esync log                # 直近 20 件
esync log --limit 50     # 件数指定
```

| オプション | 短縮 | デフォルト | 説明 |
|---|---|---|---|
| `--limit` | `-l` | 20 | 表示件数 |

### `esync clone`

eLabFTW のエンティティからローカルプロジェクトを構築する。

```bash
esync clone --url https://elab.example.com --id 42
esync clone --url https://elab.example.com --id 42 --id 43 --dir my-project
esync clone --url https://elab.example.com --id 42 --entity experiments --no-verify
```

| オプション | 必須 | デフォルト | 説明 |
|---|---|---|---|
| `--url` | ✅ | — | eLabFTW の URL |
| `--id` | ✅ | — | エンティティ ID（複数指定可） |
| `--dir` | — | `elab-clone-{id}` | プロジェクトディレクトリ名 |
| `--entity` | — | `items` | `items` / `experiments` |
| `--no-verify` | — | false | SSL 検証を無効化 |

### `esync update`

ツール自体を最新版に更新する。`uv` → `pip` の順で自動検出。

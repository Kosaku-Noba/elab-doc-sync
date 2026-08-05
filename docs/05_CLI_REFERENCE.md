# CLI リファレンス

→ [設定ファイル](04_CONFIGURATION.md) | [API リファレンス](06_API_REFERENCE.md)

## コマンド一覧

| コマンド | 説明 |
|---|---|
| `esync` | ローカル → eLabFTW に同期（push） |
| `esync pull` | eLabFTW → ローカルに取得 |
| `esync pull --id 42 --entity items` | 指定 ID のリソースを取得 |
| `esync diff` | ローカルと eLabFTW の差分を表示 |
| `esync status` | 同期状態を確認 |
| `esync tag list/add/remove` | タグ操作 |
| `esync category list/show/set` | カテゴリ操作 |
| `esync metadata get/set` | メタデータ操作 |
| `esync entity-status show/set` | エンティティステータス操作 |
| `esync list` | リモートのリソース/実験ノート一覧 |
| `esync link <ID>` | 手動紐付け |
| `esync verify` | 整合性チェック |
| `esync profile list/add/remove` | 接続プロファイル管理 |
| `esync whoami` | 現在のユーザー情報 |
| `esync new` | テンプレートからファイル作成 |
| `esync clone` | eLabFTW からプロジェクト構築 |
| `esync log` | 同期ログ表示 |
| `esync init` | 対話的に設定ファイルを作成 |
| `esync update` | ツールを最新版に更新 |

> `esync` は `elab-doc-sync` のエイリアス。

## グローバルオプション

| オプション | 短縮 | 型 | デフォルト | 説明 |
|---|---|---|---|---|
| `--config` | `-c` | string | `.elab-sync.yaml` | 設定ファイルのパス |
| `--target` | `-t` | string | 全ターゲット | 同期対象のターゲット名 |
| `--force` | `-f` | flag | false | 変更がなくても強制同期 / pull 時は上書き |
| `--dry-run` | `-n` | flag | false | 実行せずに同期内容を確認 |
| `--prune-attachments` | — | flag | false | ローカルに存在しないリモート添付を削除 |
| `--version` | `-V` | flag | — | バージョン表示 |

## コマンド詳細

### `esync`（push）

ローカルの Markdown を eLabFTW に同期する。デフォルト動作。

```bash
esync                    # 全ターゲットを同期
esync -t "名前"          # 特定ターゲットのみ
esync --dry-run          # プレビュー
esync --force            # 強制同期
```

処理フロー: ファイル収集 → 差分検知 → 画像アップロード → 変換 → API 送信 → 添付ファイルアップロード。
詳細は [同期エンジン](07_SYNC_ENGINE.md) を参照。

### `esync pull`

eLabFTW のエンティティをローカルに Markdown として保存する。

```bash
esync pull                              # 既存の同期済み ID を再取得
esync pull --id 42 --entity items       # 指定 ID を取得（--entity 必須）
esync pull --id 42 --id 43 --entity items  # 複数 ID を取得
esync pull --id 42 --entity items --auto   # 振り分けを自動決定
esync pull --id 42 --entity items --dir output/  # 保存先を明示指定
esync pull --force                      # 既存ファイルを上書き
```

| オプション | 説明 |
|---|---|
| `--id` | 取得するエンティティ ID（複数指定可） |
| `--entity` | `items` / `experiments` / `resources` |
| `--dir` | 保存先ディレクトリ（未指定時は自動振り分け） |
| `--auto` | 曖昧な振り分けもスコア最大で自動決定 |

#### pull の自動振り分け

`--id` で新しいエンティティを取得する際、以下の順で保存先を決定:

1. **既に紐付け済み** → そのディレクトリへ再同期
2. **ターゲットが1つだけ** → そのターゲットの `docs_dir` へ
3. **複数ターゲット** → タグ/カテゴリ/タイトルでスコアリング
4. **判定できない** → 対話で選択 or `--auto` で最高スコアを採用

スコアリング:
- `title_pattern` (glob) マッチ: +10
- `category` 一致: +10
- `tags` の包含率: 最大 5 + 特異性ボーナス

マッチするターゲットがない場合、リモートのメタデータから新しいターゲットが `.elab-sync.yaml` に自動追記される。

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

### `esync init`

対話形式で `.elab-sync.yaml` を生成する。テンプレートファイルも展開する。
詳細は [セットアップガイド](03_SETUP_GUIDE.md) を参照。

### `esync log`

同期ログを表示する。

```bash
esync log                # 直近 20 件
esync log --limit 50     # 件数指定
```

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
| `--entity` | — | `items` | `items` / `experiments` / `resources` |
| `--no-verify` | — | false | SSL 検証を無効化 |

### `esync tag`

エンティティのタグを管理する。

```bash
esync tag list                         # 全ターゲットのタグ一覧
esync tag list --id 42 --entity items  # 特定エンティティのタグ
esync tag add "実験" --id 42 --entity items
esync tag remove "古いタグ" --id 42 --entity items
```

### `esync category`

エンティティのカテゴリを管理する。

```bash
esync category list --entity items           # カテゴリ一覧
esync category show --id 42 --entity items   # 現在のカテゴリ
esync category set "試薬" --id 42 --entity items  # カテゴリ設定
```

### `esync metadata`

エンティティのメタデータ（extra fields）を管理する。

```bash
esync metadata get                    # メタデータを JSON で表示
esync metadata set project=ABC ver=2  # key=value ペアで設定（既存にマージ）
```

### `esync entity-status`

エンティティのステータス（draft/running/published 等）を管理する。

```bash
esync entity-status show              # 現在のステータスを表示
esync entity-status set 3             # ステータス ID を指定して変更
esync entity-status set 3 --id 42     # 特定エンティティのみ変更
```

### `esync list`

リモートのリソース/実験ノート一覧を表示する。

```bash
esync list                            # リソース一覧（デフォルト 20 件）
esync list --entity experiments       # 実験ノート一覧
esync list --limit 50                 # 件数指定
```

### `esync link`

既存のリモートエンティティとローカルプロジェクトを手動で紐付ける。

```bash
esync link 42                         # merge モード: ターゲットと ID を紐付け
esync link 42 --file exp1.md          # each モード: ファイルと ID を紐付け
esync link 42 -t "実験記録"           # 特定ターゲットに紐付け
```

### `esync verify`

ローカルとリモートの接続状態を検証する。

```bash
esync verify                          # 全ターゲット
esync verify -t "名前"               # 特定ターゲット
```

### `esync profile`

接続プロファイルを管理する。

```bash
esync profile list                    # プロファイル一覧
esync profile add team-b --url https://elab.example.com --api-key "key"
esync profile remove team-b           # プロファイル削除
```

| サブコマンド | 説明 |
|---|---|
| `list` | 登録済みプロファイル一覧 |
| `add <name> --url <url> [--api-key <key>] [--no-verify]` | プロファイル追加 |
| `remove <name>` | プロファイル削除 |

### `esync whoami`

現在の API キーに紐づくユーザー情報を表示する。

### `esync new`

eLabFTW のテンプレートから新規 Markdown ファイルを生成する。

```bash
esync new --list                      # テンプレート一覧
esync new --template-id 1             # テンプレートからファイル生成
esync new --template-id 1 --title "実験A" --output exp_a.md
```

### `esync update`

ツール自体を最新版に更新する。`uv tool install --force` で Git リポジトリから再インストールする。

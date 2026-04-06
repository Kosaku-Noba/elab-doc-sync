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
| `esync tag list` | リモートのタグ一覧を表示 |
| `esync tag add "タグ"` | タグを追加 |
| `esync tag remove "タグ"` | タグを外す |
| `esync metadata get` | メタデータを表示 |
| `esync metadata set k=v` | メタデータを設定 |
| `esync entity-status show` | エンティティのステータスを表示 |
| `esync entity-status set <ID>` | ステータスを変更 |
| `esync list` | リモートのリソース一覧を表示 |
| `esync list --entity experiments` | 実験ノート一覧を表示 |
| `esync link <ID>` | 既存リモートエンティティとローカルを紐付け |
| `esync verify` | ローカルとリモートの整合性チェック |
| `esync whoami` | 現在のユーザー情報を表示 |
| `esync new --list` | テンプレート一覧を表示 |
| `esync new --template-id <ID>` | テンプレートからファイル作成 |
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
esync pull --id 42 --entity items       # 指定 ID を取得（--entity 必須）
esync pull --id 42 --id 43 --entity items  # 複数 ID を取得
esync pull --id 42 --entity experiments  # 実験ノートとして取得
esync pull                            # 既存の同期済み ID を再取得（初回は --id 必須）
esync pull --force                    # 既存ファイルを上書き
```

- 初回 pull には `--id` が必須（全件ダウンロードは行わない）
- `--id` 指定時は `--entity` も必須（items / experiments の混在を防止）
- 2回目以降は mapping/ID ファイルから対象を自動決定
- each モード: 複数 `--id` で一括取得可能
- merge モード: 最初の `--id` を使用

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
  [My Docs] 変更あり（リソース #42）
  [API Ref] 最新（リソース #43）
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

### `esync tag`

エンティティのタグを管理する。

```bash
esync tag list                # 全ターゲットのタグ一覧
esync tag add "実験"          # タグを追加
esync tag remove "古いタグ"   # タグを外す（エンティティから解除、タグ自体は削除しない）
esync tag add "実験" --id 42  # 特定エンティティに追加
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

複数エンティティが対象の場合は確認プロンプトが表示される。

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

紐付け時にリモートの body を取得し、競合検出のベースライン（remote_hash）を初期化する。

### `esync verify`

ローカルとリモートの接続状態を検証する。

```bash
esync verify                          # 全ターゲット
esync verify -t "名前"               # 特定ターゲット
```

検証内容: ID/mapping の存在、リモートへのアクセス可否。内容の一致は `esync status` で確認。

### `esync whoami`

現在の API キーに紐づくユーザー情報を表示する。

```bash
esync whoami
```

### `esync new`

eLabFTW のテンプレートから新規 Markdown ファイルを生成する。

```bash
esync new --list                      # テンプレート一覧
esync new --template-id 1             # テンプレートからファイル生成
esync new --template-id 1 --title "実験A" --output exp_a.md
```

| オプション | 説明 |
|---|---|
| `--list` | テンプレート一覧を表示 |
| `--template-id` | テンプレート ID |
| `--title` | ファイルタイトル（省略時はテンプレート名） |
| `--output` / `-o` | 出力ファイルパス |

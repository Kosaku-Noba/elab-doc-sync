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

## push（デフォルトコマンド）

```bash
esync [--dry-run] [--force] [-t TARGET] [--prune-attachments]
```

| オプション | 説明 |
|---|---|
| `--dry-run` | 実際に送信せず変更予定を表示 |
| `--force` | 差分・競合を無視して強制送信 |
| `-t`, `--target` | 特定ターゲットのみ実行 |
| `--prune-attachments` | リモートの不要添付を削除 |

**push 処理フロー:**
1. リネーム検出（ファイル名変更 → mapping 更新 + タイトル同期）
2. パス1: 全ファイルの ID を確定（新規作成含む）
3. パス2: リンク変換 + body 送信
   - 画像 → 動画 → ファイルリンク → ローカルリンク変換

## pull

```bash
esync pull [--id ID] [--entity TYPE] [--force] [--auto] [--dir DIR] [-t TARGET]
```

| オプション | 説明 |
|---|---|
| `--id` | 取得するエンティティ ID（複数指定可） |
| `--entity` | `items` / `experiments`（--id 時は必須） |
| `--force` | 既存ファイルを上書き |
| `--auto` | 振り分けを自動決定 |
| `--dir` | 保存先ディレクトリを上書き |

**pull 時の特別動作:**
- eLabFTW 記事 URL → ローカルリンクに逆変換
- タイトル変更によるファイルリネーム

## init

```bash
esync init [--config PATH]
```

対話的に `.elab-sync.yaml` を生成する。

**質問項目:**
1. eLabFTW の URL
2. SSL 証明書検証の有無
3. Markdown ファイルディレクトリ
4. ファイルパターン
5. 送信先（items / experiments）
6. 送信形式（md / html）

> **注:** merge モードは廃止済み。mode は `each` 固定で設定される。

## update

```bash
esync update
```

ツール自体を最新版に更新する（`uv tool install --force`）。

**update 後の自動チェック:**
- PATH 上の `esync` が `.venv` 内のものでないかを確認
- `.venv` 版が優先されている場合は警告と解決方法を表示

## diff

```bash
esync diff [-t TARGET]
```

mapping に登録済みの全ファイルについて、ローカルとリモートの unified diff を表示。

## status

```bash
esync status [-t TARGET]
```

各ファイルの同期状態（変更あり / 最新）とエンティティ ID を一覧表示。

## clone

```bash
esync clone --url URL --entity TYPE --id ID [--dir DIR] [--no-verify]
```

リモートの eLabFTW エンティティからローカルプロジェクトを構築する。
`.elab-sync.yaml` とディレクトリ構造を自動生成。

## グローバルオプション

| オプション | 説明 |
|---|---|
| `--config PATH` | 設定ファイルパス（デフォルト: `.elab-sync.yaml`） |
| `--version`, `-V` | バージョン表示 |

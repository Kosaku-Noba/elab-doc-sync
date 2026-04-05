# elab-doc-sync 要求仕様書

バージョン: 0.1.0
作成日: 2026-04-05

---

## 1. 目的

ローカルの Markdown ドキュメントを eLabFTW（電子実験ノート）に同期する CLI ツールを提供する。研究者が使い慣れたテキストエディタで文書を管理しつつ、eLabFTW 上での共有・閲覧を自動化する。

## 2. ユーザーと利用環境

| 項目 | 内容 |
|---|---|
| 想定ユーザー | 研究者・技術者（CLI 操作に抵抗がない層） |
| 対応 OS | Linux / Windows |
| Python | 3.10 以上 |
| インストール方法 | `uv pip install` または `pip install`（Git リポジトリから） |

## 3. 機能要求

### FR-01: Push 同期（ローカル → eLabFTW）

- ローカルの Markdown ファイルを HTML に変換し、eLabFTW のアイテムまたは実験ノートに送信する。
- SHA-256 ハッシュによる差分検知を行い、変更があるファイルのみ更新する。
- `--force` オプションで差分に関わらず強制同期できる。
- `--dry-run` オプションで実行せずに同期内容をプレビューできる。
- `-t` オプションで特定のターゲットのみ同期できる。

### FR-02: 同期モード

| モード | 動作 |
|---|---|
| `merge` | 指定ディレクトリ内の全 Markdown を結合し、1 つのエンティティとして送信 |
| `each` | 1 ファイル = 1 エンティティとして個別に送信（タイトルはファイル名から取得） |

### FR-03: エンティティ種別

- `items`（アイテム）と `experiments`（実験ノート）の両方に対応する。
- ターゲットごとに独立して指定できる。

### FR-04: 画像の自動アップロード

- Markdown 内のローカル画像参照（`![alt](path)`）を検出する。
- 画像を eLabFTW にアップロードし、参照 URL を eLabFTW のダウンロード URL に書き換える。
- 外部 URL（`http://`, `https://`）はスキップする。
- 画像が見つからない場合は警告を出力し、元の参照を維持する。

### FR-05: Pull（eLabFTW → ローカル）

- eLabFTW 上のエンティティを取得し、HTML → Markdown に変換してローカルに保存する。
- `--id` オプションで特定のエンティティ ID を指定して取得できる。
- 既存ファイルがある場合はスキップし、`--force` で上書きできる。

### FR-06: Diff（差分表示）

- ローカルの Markdown と eLabFTW 上の内容を比較し、unified diff 形式で表示する。

### FR-07: Status（同期状態確認）

- 各ターゲットの変更有無・同期先エンティティ ID を一覧表示する。

### FR-08: Init（対話的セットアップ）

- 対話形式で `.elab-sync.yaml` を生成する。
- テンプレートファイル（`.gitignore`, `README.md`, `docs/`）を展開する。

### FR-09: Update（自動更新）

- `uv` または `pip` を使い、Git リポジトリから最新版にアップグレードする。

### FR-10: エイリアス

- `elab-doc-sync` と `esync` の両方のコマンド名で実行できる。

## 4. 非機能要求

### NFR-01: セキュリティ

- API キーは環境変数 `ELABFTW_API_KEY` を優先し、設定ファイルにも記載可能とする。
- `.elab-sync-ids/` を `.gitignore` に含め、ID・ハッシュの漏洩を防止する。
- `verify_ssl` オプションで SSL 検証の有無を制御できる。

### NFR-02: エラーハンドリング

- 設定不備（URL 未設定、API キー未設定、ターゲット未定義）に対して日本語のエラーメッセージと対処法を表示する。
- HTTP エラーは `requests.HTTPError` として伝播し、CLI 層でキャッチして表示する。
- 同期先エンティティが削除されていた場合、自動的に新規作成にフォールバックする。

### NFR-03: 冪等性

- 同一内容で複数回実行しても、ハッシュ比較により不要な更新を行わない。
- `--force` 指定時のみ無条件で更新する。

### NFR-04: 国際化

- CLI の全メッセージ（エラー、進捗、ヘルプ）は日本語で出力する。

## 5. 設定ファイル仕様

ファイル: `.elab-sync.yaml`

| キー | 必須 | デフォルト | 説明 |
|---|---|---|---|
| `elabftw.url` | ✅ | — | eLabFTW インスタンスの URL |
| `elabftw.api_key` | ✅ | — | API キー（環境変数 `ELABFTW_API_KEY` が優先） |
| `elabftw.verify_ssl` | — | `true` | SSL 証明書検証 |
| `targets[].title` | merge 時 ✅ | — | エンティティのタイトル |
| `targets[].docs_dir` | ✅ | — | Markdown ファイルのディレクトリ |
| `targets[].pattern` | — | `*.md` | Glob パターン |
| `targets[].mode` | — | `merge` | `merge` / `each` |
| `targets[].entity` | — | `items` | `items` / `experiments` |
| `targets[].id_file` | — | `.elab-sync-ids/default.id` | ID 保存先パス |

## 6. コマンド一覧

| コマンド | 説明 |
|---|---|
| `esync` | Push 同期（デフォルト動作） |
| `esync pull [--id N]` | Pull（eLabFTW → ローカル） |
| `esync diff` | 差分表示 |
| `esync status` | 同期状態確認 |
| `esync init` | 対話的セットアップ |
| `esync update` | ツール更新 |

| オプション | 短縮 | 説明 |
|---|---|---|
| `--config` | `-c` | 設定ファイルパス |
| `--target` | `-t` | 対象ターゲット名 |
| `--force` | `-f` | 強制実行 |
| `--dry-run` | `-n` | プレビュー |

## 7. 依存ライブラリ

| ライブラリ | バージョン | 用途 |
|---|---|---|
| requests | >=2.28 | HTTP 通信 |
| markdown | >=3.4 | Markdown → HTML 変換 |
| markdownify | >=0.11 | HTML → Markdown 変換（pull 用） |
| pyyaml | >=6.0 | YAML 設定読み込み |
| urllib3 | >=2.0 | SSL 警告制御 |

## 8. データ管理

| ファイル | 内容 |
|---|---|
| `*.id` | eLabFTW エンティティ ID（整数、1行） |
| `*.hash` | SHA-256 先頭 16 文字（差分検知用） |
| `mapping.json` | each モードのファイル名 → エンティティ ID マッピング |
| `.elab-sync-ids/sync-log.jsonl` | 同期履歴（JSONL 形式） |

---

## 9. 拡張機能要求（v0.2.0 ロードマップ）

### FR-11: 競合検出・解決

- push 前にリモートの body ハッシュを取得し、前回同期時のハッシュと比較する。
- リモートが変更されていた場合、push を中断し警告を表示する。
- `--force` で強制上書き、`--pull-first` でリモート変更を先に取り込むオプションを提供する。
- 将来的に 3-way diff（ローカル変更 / リモート変更 / 共通祖先）による自動マージを検討する。

### FR-12: Clone（リモートからプロジェクト構築）

- `esync clone --url <elabftw-url> --id <entity-id> [--dir <dir>]` で、リモートのエンティティからローカルプロジェクトを一発構築する。
- `.elab-sync.yaml`、ディレクトリ構造、ID マッピングを自動生成する。
- 複数 ID 指定（`--id 42 --id 43`）で複数エンティティを一括取得できる。

### FR-13: 同期ログ

- `esync log` で同期履歴を表示する。
- 各同期操作（push / pull）のタイムスタンプ、対象ファイル、エンティティ ID、操作種別を `.elab-sync-ids/sync-log.jsonl` に記録する。
- eLabFTW の revisions API を活用し、リモート側の変更履歴も `esync log --remote` で表示する。

### FR-14: Watch（ファイル監視・自動同期）

- `esync watch` でファイル変更を監視し、変更検出時に自動 push する。
- デバウンス間隔（デフォルト 5 秒）を `--interval` で設定可能とする。
- watchdog ライブラリを使用し、Linux / Windows 両対応とする。

### FR-15: タグ・メタデータ管理

- `esync tag add <tag>` / `esync tag remove <tag>` / `esync tag list` でタグを CLI から操作する。
- `esync meta set <key> <value>` / `esync meta get <key>` でメタデータを読み書きする。
- `.elab-sync.yaml` の `targets[].tags` でデフォルトタグを定義し、同期時に自動付与する。

### FR-16: ステータス管理

- タグまたはメタデータで `draft` / `published` のステータスを管理する。
- `esync publish` で draft → published に昇格する。
- `esync unpublish` で published → draft に戻す。

### FR-17: マルチユーザー対応

- `esync whoami` で現在の API キーに紐づくユーザー情報を表示する。
- 同期ログにユーザー名を記録する。
- 将来的にロック機構（編集中エンティティの排他制御）を検討する。

### FR-18: テンプレート機能

- `esync new <type> --template <name>` でテンプレートから新規ドキュメントを生成する。
- ローカルテンプレート（`templates/` ディレクトリ）と eLabFTW 側テンプレートの両方に対応する。

## 10. 拡張機能の優先度

| 優先度 | 機能 | 理由 |
|---|---|---|
| 高 | FR-11 競合検出 | データ消失防止。同期ツールとしての信頼性の根幹 |
| 高 | FR-12 Clone | 初回セットアップ体験を GitHub clone 並みにする |
| 高 | FR-13 同期ログ | 操作の追跡可能性。運用上必須 |
| 中 | FR-14 Watch | 同期の自動化。研究者の負担軽減 |
| 中 | FR-15 タグ・メタデータ | eLabFTW の整理機能をローカルから活用 |
| 中 | FR-16 ステータス管理 | draft/published ワークフロー |
| 低 | FR-17 マルチユーザー | チーム利用時に必要。まず個人利用を固める |
| 低 | FR-18 テンプレート | 利便性向上だが後回し可 |

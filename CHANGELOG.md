# Changelog

## v0.2.2 (2026-04-13)

### 新機能

#### カテゴリ機能
- `esync category list` でカテゴリ一覧を表示（`--entity experiments` 対応）
- `esync category show --id <ID> --entity <TYPE>` で現在のカテゴリを表示
- `esync category set <名前|ID> --id <ID> --entity <TYPE>` でカテゴリを設定
- YAML の `category` 設定で push 時にカテゴリを自動適用（本文更新時または `--force` 時）

### 修正

- `category show` / `category set` の `--id` `--entity` を必須化
- cp932 フォールバック読み込みを追加（Windows 環境対応）
- YAML 読み書きで `encoding='utf-8'` を明示
- `--force` で添付ファイルも再送されるように修正

## v0.2.1 (2026-04-09)

### 新機能

#### 添付ファイル対応
- `attachments_dir` 設定で画像以外のファイル（PDF, CSV, Excel 等）を自動アップロード・ダウンロード
- push 時: 指定ディレクトリ内の非画像ファイルをリモートにアップロード（サイズ比較で差分検知・再利用）
- pull / clone 時: リモートの非画像添付ファイルをローカルにダウンロード
- dry-run で添付ファイル件数を表示
- 同名・同サイズのファイルは再利用（内容変更時は `--force` で強制再送）

### 修正

#### LaTeX 数式保護
- `body_format: html` で `$$...$$` / `$...$` の LaTeX 数式が壊れる問題を修正
- 数式内の `<`, `>`, `&` を HTML エンティティに変換
- `\$` はリテラルドル記号として扱い、数式開始とみなさない

#### pull 時の過剰エスケープ抑制
- `markdownify` による `\_` `\*` 等の過剰エスケープを抑制
- push → pull → edit → push のラウンドトリップが安定

> 検証: 220 テスト通過（S-85〜S-104, CLI-54〜CLI-55 で数式保護・添付ファイル・エスケープ抑制をカバー）

## v0.2.0 (2026-04-06)

### 新機能

#### FR-11: 競合検出
- push 前にリモートの body ハッシュを前回同期時と比較し、リモートが変更されていたら push を中断
- `--force` で競合を無視して強制上書き可能
- pull 成功時・push 成功時に remote_hash を自動保存

#### FR-12: Clone
- `esync clone --url <url> --id <id>` でリモートからローカルプロジェクトを一発構築
- 複数 ID 対応（`--id 42 --id 43`）
- 全件取得失敗時のクリーンアップ、既存ディレクトリ保護

#### FR-13: 同期ログ
- push/pull の操作履歴を JSONL 形式で記録
- `esync log [--limit N]` で表示
- best-effort 設計（ログ書き込み失敗が同期を中断しない）

#### FR-15: タグ・メタデータ管理
- `esync tag list/add/remove` — リモートのタグを CLI から操作
- `esync metadata get/set` — メタデータを key=value 形式で管理
- `.elab-sync.yaml` の `targets[].tags` で push 時にタグを自動追記（追記のみ、既存タグは外さない）

#### FR-16: ステータス管理
- `esync entity-status show/set` — エンティティのステータスを表示・変更
- 複数エンティティ対象時は確認プロンプトを表示
- `--id` で単体指定可能

#### FR-17: マルチユーザー対応（whoami）
- `esync whoami` — 現在の API キーに紐づくユーザー名・メール・チームを表示
- 同期ログの `record()` に `user` パラメータを追加（API のみ。通常の push/pull では未使用）

#### FR-18: テンプレート機能
- `esync new --list` — eLabFTW のテンプレート一覧を表示
- `esync new --template-id <ID>` — テンプレートから Markdown ファイルを生成
- `--title`, `--output` オプション対応

#### FR-19: リモート一覧表示
- `esync list [--entity experiments] [--limit N]` — リモートのリソース/実験ノート一覧を表示

#### FR-20: 手動紐付け
- `esync link <ID> [--file name.md]` — 既存リモートエンティティとローカルを手動で接続
- 紐付け時に remote_hash を初期化（競合検出のベースライン設定）

#### FR-21: 整合性チェック
- `esync verify` — ローカルファイルとリモートエンティティの接続状態を検証

### 改善

#### pull の安全性向上
- 初回 pull で `--id` 必須に変更（全件ダウンロード廃止）
- `--id` を複数指定可能に（`--id 42 --id 43`）
- `--entity` オプションで items/experiments を明示指定可能
- merge モードで複数 `--id` 指定時は警告を表示

#### 用語統一: アイテム → リソース
- CLI のユーザー向け表示を「アイテム」から「リソース」に変更（eLabFTW Web UI の表示名に統一）
- `--entity resources` を `items` のエイリアスとして受け付け（API 引数の `items` は引き続き有効）
- `.elab-sync.yaml` の `entity: resources` も `items` に正規化

#### Codex 自動レビュー基盤
- post-commit フックで Codex による6観点レビューを自動実行
- 日本語出力を強制するカスタムプロンプト
- `SKIP_CODEX_REVIEW=1` でスキップ可能
- レビュー時に `pytest` を自動実行

### テスト

- テストケース: 0 → 138 件
- GitHub Actions で Python 3.10/3.12 の自動テスト
- 全 API 通信は mock、ファイル操作は `tmp_path` で完結

### ドキュメント

- 番号付きドキュメント体系（01〜12）を新設
- CLI リファレンス、API リファレンス、設定ファイル仕様、同期エンジン仕様、テスト仕様書、設計判断記録
- AI レビュー方法論ドキュメント
- template/README.md を初見ユーザー向けに全面改訂

### 破壊的変更

- `esync pull` の `--id` なし初回実行で全件ダウンロードしなくなりました。`--id` を指定してください。
- CLI の表示が「アイテム」から「リソース」に変更されました（`items` は引き続き `--entity` の値として使用可能）。

### 依存関係

変更なし（requests, markdown, markdownify, pyyaml, urllib3）

---

## v0.1.0 (2026-04-05)

初回リリース。

- Push 同期（差分検知、`--force`、`--dry-run`、`-t`）
- 同期モード（merge / each）
- エンティティ種別（items / experiments）
- 画像の自動アップロード・URL 書き換え
- Pull（eLabFTW → ローカル、`--id`、`--force`）
- Diff（unified diff 形式）
- Status（同期状態確認）
- Init（対話的セットアップ）
- Update（自動更新）
- エイリアス（`esync` / `elab-doc-sync`）

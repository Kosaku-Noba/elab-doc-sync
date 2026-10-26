# elab-doc-sync プロジェクト概要

対象バージョン: v1.2.0（2026-10-26）

## 目的

ローカルの Markdown ドキュメントを eLabFTW（電子実験ノート）に同期する CLI ツール。研究者が使い慣れたテキストエディタで文書を管理しつつ、eLabFTW 上での共有・閲覧を自動化する。

## 主な特徴

- 1 ファイル = 1 エンティティの同期（each モード。merge モードは v1.0 で廃止）
- SHA-256 差分検知で変更があるファイルだけ更新
- 画像の自動アップロード・URL 書き換え（同名で差し替えた画像の古い版は自動削除）
- 動画 (.mp4, .webm) の自動アップロード・`<video>` タグ変換
- 非画像・非動画ファイル (PDF, CSV 等) のリンクアップロード
- ファイル間リンクの自動変換（ローカルリンク ↔ eLabFTW 記事 URL。同じホストの別ターゲットの文書へのリンクを含む）
- ファイル名リネーム検出 → eLabFTW タイトル自動同期（`esync mv` で明示的な移動も可能）
- 添付ファイル（attachments_dir）の自動アップロード
- リソース (`items` / `resources`) と実験ノート (`experiments`) の両方に対応
- Pull（eLabFTW → ローカル）。両側が変更した文書は 3-way マージし、同じ箇所の変更は競合マーカーで残す
- 前回の同期からの「ローカルの変更」「eLabFTW 側の変更」を分けて表示する diff
- `esync push <ファイル>` など、文書を指定した push・diff・rm（ディレクトリ・glob・`--regex`）
- 文書ごとの状態表示と、次に実行できるコマンドの案内（`status` / `diff` / push の失敗時）
- 実験ノート・リソースどうしのリンク操作（`esync relate`）と、push 時のリンク自動追加（ターゲット設定 `links`）
- Pull 時のタグ/カテゴリ/タイトルによる自動振り分け
- 複数サーバー・チーム対応（プロファイル機能）
- `body_format: md` で Markdown のまま送信可能（MathJax 対応）
- 2パス sync 構造（全 ID 確定後にリンク変換+送信）
- 上書き前のバックアップと `esync restore`、途中失敗からの再開
- Windows / Linux 両対応
- `elab-doc-sync` と `esync` の 2 つのコマンド名で実行可能

## 想定ユーザー

| 項目 | 内容 |
|---|---|
| 対象 | 研究者・技術者（CLI 操作に抵抗がない層） |
| 対応 OS | Linux / Windows |
| Python | 3.10 以上（CI で 3.10・3.12・3.14 を検証） |
| インストール | `uv tool install`（Git リポジトリから） |
| eLabFTW | API v2。実機検証は 5.5.14 |

## ドキュメント一覧

| ファイル | 内容 |
|---|---|
| [01_README.md](01_README.md) | プロジェクト概要（本文書） |
| [02_SYSTEM_OVERVIEW.md](02_SYSTEM_OVERVIEW.md) | アーキテクチャ・ディレクトリ構成 |
| [03_SETUP_GUIDE.md](03_SETUP_GUIDE.md) | インストール・初期設定 |
| [04_CONFIGURATION.md](04_CONFIGURATION.md) | 設定ファイル仕様 |
| [05_CLI_REFERENCE.md](05_CLI_REFERENCE.md) | コマンド・オプション一覧 |
| [06_API_REFERENCE.md](06_API_REFERENCE.md) | モジュール・関数リファレンス |
| [07_SYNC_ENGINE.md](07_SYNC_ENGINE.md) | 同期エンジン詳細 |
| [08_PERFORMANCE.md](08_PERFORMANCE.md) | 性能仕様・制約・API エンドポイント |
| [09_TROUBLESHOOTING.md](09_TROUBLESHOOTING.md) | よくある問題と対処法 |
| [10_REQUIREMENTS.md](10_REQUIREMENTS.md) | 要求仕様・ロードマップ |
| [11_TEST_SPEC.md](11_TEST_SPEC.md) | テスト仕様 |
| [12_DESIGN_DECISIONS.md](12_DESIGN_DECISIONS.md) | 設計判断記録 |
| [13_MIGRATION_V1.md](13_MIGRATION_V1.md) | v1.0 への移行と復旧 |
| [14_RELEASE_VALIDATION.md](14_RELEASE_VALIDATION.md) | リリース検証記録 |

変更履歴は [CHANGELOG.md](../CHANGELOG.md) を参照。

# elab-doc-sync プロジェクト概要

## 目的

ローカルの Markdown ドキュメントを eLabFTW（電子実験ノート）に同期する CLI ツール。研究者が使い慣れたテキストエディタで文書を管理しつつ、eLabFTW 上での共有・閲覧を自動化する。

## 主な特徴

- 1 ファイル = 1 エンティティの同期（each モード）
- SHA-256 差分検知で変更があるファイルだけ更新
- 画像の自動アップロード・URL 書き換え
- 動画 (.mp4, .webm) の自動アップロード・`<video>` タグ変換
- 非画像・非動画ファイル (PDF, CSV 等) のリンクアップロード
- ファイル間リンクの自動変換（ローカルリンク ↔ eLabFTW 記事 URL）
- ファイル名リネーム検出 → eLabFTW タイトル自動同期
- 添付ファイル（attachments_dir）の自動アップロード
- リソース (`items`) と実験ノート (`experiments`) の両方に対応
- Pull（eLabFTW → ローカル）・差分表示（diff）に対応
- Pull 時のタグ/カテゴリ/タイトルによる自動振り分け
- 競合検出（リモートが前回同期以降に変更されていれば警告）
- 複数サーバー対応（プロファイル機能）
- `body_format: md` で Markdown のまま送信可能（MathJax 対応）
- 2パス sync 構造（全 ID 確定後にリンク変換+送信）
- Windows / Linux 両対応
- `elab-doc-sync` と `esync` の 2 つのコマンド名で実行可能

## 想定ユーザー

| 項目 | 内容 |
|---|---|
| 対象 | 研究者・技術者（CLI 操作に抵抗がない層） |
| 対応 OS | Linux / Windows |
| Python | 3.10 以上 |
| インストール | `uv tool install`（Git リポジトリから） |

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
| [08_PERFORMANCE.md](08_PERFORMANCE.md) | 性能仕様・制約 |
| [09_TROUBLESHOOTING.md](09_TROUBLESHOOTING.md) | よくある問題と対処法 |
| [10_REQUIREMENTS.md](10_REQUIREMENTS.md) | 要求仕様・ロードマップ |
| [11_TEST_SPEC.md](11_TEST_SPEC.md) | テスト仕様 |
| [12_DESIGN_DECISIONS.md](12_DESIGN_DECISIONS.md) | 設計判断記録 |

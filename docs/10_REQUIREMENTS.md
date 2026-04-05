# 要求仕様・ロードマップ

→ [トラブルシューティング](09_TROUBLESHOOTING.md) | [テスト仕様](11_TEST_SPEC.md)

## 実装済み機能

| ID | 機能 | 状態 |
|---|---|---|
| FR-01 | Push 同期（差分検知、`--force`、`--dry-run`、`-t`） | ✅ |
| FR-02 | 同期モード（merge / each） | ✅ |
| FR-03 | エンティティ種別（items / experiments） | ✅ |
| FR-04 | 画像の自動アップロード・URL 書き換え | ✅ |
| FR-05 | Pull（eLabFTW → ローカル、`--id`、`--force`） | ✅ |
| FR-06 | Diff（unified diff 形式） | ✅ |
| FR-07 | Status（同期状態確認） | ✅ |
| FR-08 | Init（対話的セットアップ） | ✅ |
| FR-09 | Update（自動更新） | ✅ |
| FR-10 | エイリアス（`esync` / `elab-doc-sync`） | ✅ |
| FR-11 | 競合検出（リモートハッシュ比較） | ✅ |
| FR-12 | Clone（リモートからプロジェクト構築） | ✅ |
| FR-13 | 同期ログ（JSONL 記録・表示） | ✅ |

## 非機能要求

| ID | 要求 | 状態 |
|---|---|---|
| NFR-01 | セキュリティ（環境変数優先、`.gitignore` 推奨） | ✅ |
| NFR-02 | エラーハンドリング（日本語メッセージ、フォールバック） | ✅ |
| NFR-03 | 冪等性（ハッシュ比較による不要更新防止） | ✅ |
| NFR-04 | 国際化（全メッセージ日本語） | ✅ |

## ロードマップ（未実装）

| 優先度 | ID | 機能 | 概要 |
|---|---|---|---|
| 中 | FR-14 | Watch | ファイル監視・自動同期（watchdog） |
| 中 | FR-15 | タグ・メタデータ管理 | CLI からタグ・メタデータを操作 | ✅ |
| 中 | FR-16 | ステータス管理 | draft / published ワークフロー | ✅ |
| 低 | FR-17 | マルチユーザー対応 | `whoami`、ロック機構 |
| 低 | FR-18 | テンプレート機能 | テンプレートから新規ドキュメント生成 |

## セキュリティ考慮事項

- API キーは環境変数 `ELABFTW_API_KEY` を優先（設定ファイルにも記載可能）
- `verify_ssl: false` 設定時、urllib3 の InsecureRequestWarning を抑制
- `.elab-sync-ids/` を `.gitignore` に追加することを推奨

## 依存ライブラリ

| ライブラリ | バージョン | 用途 |
|---|---|---|
| requests | >=2.28 | HTTP 通信 |
| markdown | >=3.4 | Markdown → HTML 変換 |
| markdownify | >=0.11 | HTML → Markdown 変換（pull 用） |
| pyyaml | >=6.0 | YAML 設定読み込み |
| urllib3 | >=2.0 | SSL 警告制御 |

# テスト仕様書

→ [要求仕様](10_REQUIREMENTS.md) | [プロジェクト概要](01_README.md)

## 1. 概要

elab-doc-sync v0.4.1 の全機能に対するユニットテスト・統合テストの仕様。
eLabFTW API への通信は全て mock し、ファイルシステム操作は `tmp_path` を使用する。

テストフレームワーク: `pytest`
モック: `unittest.mock` (`patch`, `MagicMock`)
ディレクトリ: `tests/`

## 2. テスト対象モジュールとテストファイル

| モジュール | テストファイル | テスト数 | 概要 |
|---|---|---|---|
| `config.py` | `tests/test_config.py` | 18 | 設定ファイルの読み込み・バリデーション |
| `client.py` | `tests/test_client.py` | 40 | API クライアントのリクエスト構築・レスポンス処理 |
| `sync.py` | `tests/test_sync.py` | 100 | merge/each 同期ロジック・ハッシュ管理・競合検出 |
| `sync_log.py` | `tests/test_sync_log.py` | 13 | JSONL ログの記録・読み取り・表示 |
| `cli.py` | `tests/test_cli.py` | 108 | CLI コマンドの統合テスト |
| **合計** | | **279** | |

## 3. テストカテゴリ

### 3.1 test_config.py (18 tests)

- 正常な設定ファイルの読み込み（url, api_key, targets）
- 環境変数 `ELABFTW_API_KEY` の優先
- バリデーションエラー（URL/API キー/targets 未設定）
- mode/entity のデフォルト値
- tags/category フィールドの読み込み
- body_format（デフォルト html, 明示 md）
- cp932 フォールバック読み込み・UTF-8 優先・再保存時 UTF-8 化
- profiles セクションのパース

### 3.2 test_client.py (40 tests)

- リソース CRUD（get/create/update/delete）
- 実験 CRUD
- ファイルアップロード（正常・URL 取得失敗）
- タグ操作（add/remove/get/untag_by_name）
- メタデータ操作（正常/null/不正JSON/list型）
- カテゴリ解決（数値/名前/不存在）
- 汎用エンティティ操作
- HTTP エラーハンドリング
- verify_ssl=False

### 3.3 test_sync.py (100 tests)

- ユーティリティ関数（_compute_hash, _count_local_images, _md_to_html）
- DocsSyncer（collect_docs, has_changed, save_hash, sync 新規/更新/スキップ/force）
- EachDocsSyncer（複数ファイル同期、一部スキップ、mapping.json）
- 画像アップロード（_rewrite_images: 正常/http URL スキップ/ファイル不在/フォールバック）
- 競合検出（remote_hash なし/一致/不一致/force バイパス）
- タグ同期（_sync_tags: 追記のみ動作/best-effort）
- カテゴリ同期（_sync_category: 正常/None スキップ/失敗時 best-effort）
- 添付ファイルアップロード
- body_format 対応（md/html）

### 3.4 test_sync_log.py (13 tests)

- record（正常/複数回/ディレクトリ自動作成/書き込み失敗）
- read_log（正常/limit/壊れた行スキップ/ファイルなし/壊れた UTF-8）
- format_log（正常/空リスト）
- user フィールドの記録

### 3.5 test_cli.py (108 tests)

- cmd_sync（push 正常/dry-run/force/ターゲット指定/ConflictError）
- cmd_pull（each/merge/ID指定/既存スキップ/force/自動振り分け/--auto）
- cmd_clone（正常/複数ID/既存ディレクトリ/全件失敗/gitignore/API キー未設定）
- cmd_log（正常/limit）
- cmd_init（正常/既存ファイル/テンプレート展開）
- cmd_update
- cmd_diff（差分あり/なし）
- cmd_status（変更あり/最新）
- cmd_tag（list/add/remove）
- cmd_category（list/show/set）
- cmd_metadata（get/set）
- cmd_entity_status（show/set）
- cmd_whoami
- cmd_new（list/template-id/既存エラー/output）
- cmd_list（items/experiments/limit）
- cmd_link（merge/each/ターゲット指定）
- cmd_verify（正常/失敗）
- cmd_profile（list/add/remove）
- 添付ファイル関連テスト
- pull 自動振り分けテスト

## 4. テスト環境・方針

### 4.1 依存パッケージ

```toml
[project.optional-dependencies]
test = ["pytest>=7.0"]
```

### 4.2 共通フィクスチャ（`tests/conftest.py`）

| フィクスチャ | 概要 |
|---|---|
| `mock_client` | `ELabFTWClient` の MagicMock。API 呼び出しを全てモック |
| `sample_config` | テスト用 `.elab-sync.yaml` を `tmp_path` に生成 |
| `sample_target` | `TargetConfig` インスタンス（merge/each 両方） |
| `docs_dir` | テスト用 Markdown ファイルを配置した `tmp_path/docs/` |

### 4.3 方針

- eLabFTW API への実通信は行わない（全て mock）
- ファイルシステム操作は `tmp_path`（pytest 組み込み）を使用
- 各テストは独立して実行可能（状態を共有しない）
- テスト実行: `uv run pytest -q -m "not integration"`
- 統合テスト（`@pytest.mark.integration`）は実サーバー接続が必要なため通常はスキップ

## 5. テスト実行

```bash
# 全テスト（統合テスト除外）
UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q -m "not integration"

# 特定モジュール
uv run pytest tests/test_cli.py -v

# 統合テスト（実サーバー接続が必要）
uv run pytest -m integration
```

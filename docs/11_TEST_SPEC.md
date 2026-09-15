# テスト仕様書

→ [要求仕様](10_REQUIREMENTS.md) | [プロジェクト概要](01_README.md)

## 1. 概要

単体・CLIテストはAPI通信をモックし、`tmp_path` の独立したファイルシステムを使用します。`test_v1.py` では更新内容を保持する擬似サーバーで、操作をまたぐ状態遷移と復旧を検証します。

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q
```

実機テストは `test_integration.py` で分離し、テストキー未設定時はスキップします。実行すると一時的な記事・添付を作成し、終了時に削除します。

## 2. v1.0の受け入れシナリオ

- ローカルのみ・リモートのみ・両側変更と、タイトルだけの変更。
- 本文・画像・添付・文書間リンク・フラグメント・数式の往復同期。
- 401/403/404/429/500/タイムアウトでの重複作成防止。
- POST結果不明、PATCH前後の通信切断、部分成功と再開。
- 上書き前バックアップ、復元、復元の取消、破損バックアップ、シンボリックリンク拒否。
- 原子的保存の失敗、同時実行、ローカル操作途中の中断と復旧。
- 読み取りコマンドとdry-runの無変更保証。
- mv、rm→link→新規文書追加、復元後に過去の作成IDを忘れないこと。
- 旧ハッシュ・mappingの移行、複数接続先の同一ID、merge拒否、終了コード。

環境別の最新結果は [リリース検証](14_RELEASE_VALIDATION.md) に記録します。以下のカテゴリは既存テストの分類です。

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
- 同期状態・ハッシュ管理（新規/更新/スキップ/force）
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
- cmd_pull（each/ID指定/既存スキップ/force/自動振り分け/--auto）
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

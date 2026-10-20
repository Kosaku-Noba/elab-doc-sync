# テスト仕様書

→ [要求仕様](10_REQUIREMENTS.md) | [プロジェクト概要](01_README.md)

## 1. 概要

単体・CLIテストはAPI通信をモックし、`tmp_path` の独立したファイルシステムを使用します。`test_v1.py` では更新内容を保持する擬似サーバーで、操作をまたぐ状態遷移と復旧を検証します。

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q
```

実機テストは `test_integration.py`・`test_integration_v1.py` に分離し、`ELABFTW_TEST_CONFIG`（`test_integration.py` は `ELABFTW_DEMO_API_KEY` でも可）が未設定ならスキップします。`ELABFTW_TEST_JOURNAL` にファイルパスを指定すると、作成・削除した ID を記録します。実行すると一時的な記事・添付を作成し、終了時に削除します。

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

件数は v1.1.2 時点の pytest の収集数（パラメータ化を展開した数）。合計 574 件で、実機接続 11 件と PowerShell の引用 5 件は環境によりスキップされる。

| ファイル | 件数 | 対象 |
|---|---|---|
| test_cli.py | 136 | CLI の各サブコマンド |
| test_v1.py | 137 | 擬似サーバーでの状態遷移・復旧・v1.0 以降の仕様 |
| test_sync.py | 108 | 同期ロジック・変換関数 |
| test_client.py | 57 | API クライアント |
| test_rm.py | 48 | `esync rm` の対象選択 |
| test_config.py | 36 | 設定の読み込み・検証 |
| test_push_select.py | 18 | 文書を指定した push |
| test_sync_log.py | 13 | 同期ログ |
| test_merge.py | 10 | 3-way マージ |
| test_integration.py | 6 | 実機（既存） |
| test_integration_v1.py | 5 | 実機（v1.0 以降） |

### 3.1 test_config.py

- 正常な設定ファイルの読み込み（url, api_key, targets）
- 環境変数 `ELABFTW_API_KEY` の優先
- バリデーションエラー（URL/API キー/targets 未設定、merge、entity、body_format）
- mode/entity のデフォルト値、`resources` → `items`
- tags/category/links フィールドの読み込みと `links` の検証
- body_format（デフォルト html, 明示 md）
- cp932 フォールバック読み込み・UTF-8 優先・再保存時 UTF-8 化
- profiles セクションのパース、`team` によるプロファイル選択

### 3.2 test_client.py

- リソース・実験ノートの CRUD、削除済み（`state=3`）の 404 扱い
- ファイルアップロード（正常・リトライ・Location による特定・同名添付の選択・URL 取得失敗）
- タグ操作（add/remove/get/untag_by_name、null 応答）
- メタデータ操作（正常/null/不正JSON/list型）
- カテゴリ解決（数値/名前/不存在/一覧にないカテゴリ）
- リンク操作（list_links/add_link/remove_link）
- 汎用エンティティ操作、HTTP エラーハンドリング、verify_ssl=False

### 3.3 test_sync.py

- ユーティリティ関数（_compute_hash, _count_local_images, _md_to_html）
- 同期状態・ハッシュ管理（新規/更新/スキップ/force）
- EachDocsSyncer（複数ファイル同期、一部スキップ、mapping.json）
- 画像・動画・ファイルリンクのアップロードと差し替え（古い版の削除）
- 文書間リンクの変換（別ターゲット、URL エンコード、サブディレクトリ）
- 競合検出、タグ・カテゴリ・`links` の同期と失敗時の扱い
- 添付ファイル、body_format 対応（md/html）、HTML エスケープの復元

### 3.4 test_sync_log.py

- record（正常/複数回/ディレクトリ自動作成/書き込み失敗）
- read_log（正常/limit/壊れた行スキップ/ファイルなし/壊れた UTF-8）
- format_log（正常/空リスト）
- user フィールドの記録

### 3.5 test_cli.py

- push・pull・clone・log・init・update・diff・status
- tag・category・metadata・entity-status・whoami・new・list・link・verify・profile
- relate（ID・パス指定、`--from`、`-t` とプロファイル、送信前の検証）
- 添付ファイル、pull 自動振り分け、次の操作の案内と引用（PowerShell は Windows のみ実行）

### 3.6 test_v1.py

更新内容を保持する擬似サーバーで、操作をまたぐ状態遷移を検証する。

- pull の 3-way マージと競合マーカー、`.base` / `.synced` の保存と旧形式の読み込み
- diff の「ローカルの変更」「eLabFTW 側の変更」
- 未完了の同期の再開（eLabFTW による本文の書き換えを含む）
- 作成結果不明・リモート削除・確認失敗、バックアップと restore
- カテゴリの事前解決、`<…>` の削除検出、`links` の記録と再試行

### 3.7 test_rm.py / test_push_select.py

- ファイル・ディレクトリ・glob・`--regex`・ID の選択、重複の除去、無一致・不正な正規表現の検出（何も変更しない）
- `--local`・`--dry-run`、除外した文書の扱い、指定しなかった文書を取得・送信しないこと

### 3.8 test_merge.py

- 片側だけの変更の取り込み、同じ箇所の変更のマーカー、基準なしのマージ、マーカーに似た行の扱い

### 3.9 実機テスト（test_integration.py / test_integration_v1.py）

- 画像・添付のアップロードとダウンロードの往復、push→pull→push の冪等性
- md/html の往復・競合・restore、タグなし記事の pull と最初のタグ追加
- eLabFTW が本文を書き換えた後の再開、差し替えた画像の古い版の削除

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
| `merge_target` / `each_target` | `TargetConfig` インスタンス（`merge_target` は旧形式の互換テスト用） |
| `docs_dir` | テスト用 Markdown ファイルを配置した `tmp_path/docs/` |
| `sample_config_path` | テスト用 `.elab-sync.yaml` を `tmp_path` に生成 |

実機テストの接続先は `tests/integration_support.py` で決める。

### 4.3 方針

- 単体・CLI テストは eLabFTW API への実通信を行わない（mock または擬似サーバー）
- ファイルシステム操作は `tmp_path`（pytest 組み込み）を使用
- 各テストは独立して実行可能（状態を共有しない）
- 統合テスト（`@pytest.mark.integration`）は実サーバー接続が必要なため通常はスキップ

## 5. テスト実行

```bash
# 全テスト（統合テスト除外）
UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q -m "not integration"

# 特定モジュール
uv run pytest tests/test_cli.py -v

# 実機テスト（接続先の指定が必要。一時記事を作成し、終了時に削除する）
ELABFTW_TEST_CONFIG=/path/to/test-config.yaml UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_integration.py tests/test_integration_v1.py -v
```

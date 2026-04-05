# テスト仕様書

→ [要求仕様](10_REQUIREMENTS.md) | [プロジェクト概要](01_README.md)

## 1. 概要

elab-doc-sync v0.2.0 の全機能に対するユニットテスト・統合テストの仕様。
eLabFTW API への通信は全て mock し、ファイルシステム操作は `tmp_path` を使用する。

テストフレームワーク: `pytest`
モック: `unittest.mock` (`patch`, `MagicMock`)
ディレクトリ: `tests/`

## 2. テスト対象モジュールとテストファイル

| モジュール | テストファイル | 概要 |
|---|---|---|
| `config.py` | `tests/test_config.py` | 設定ファイルの読み込み・バリデーション |
| `client.py` | `tests/test_client.py` | API クライアントのリクエスト構築・レスポンス処理 |
| `sync.py` | `tests/test_sync.py` | merge/each 同期ロジック・ハッシュ管理・競合検出 |
| `sync_log.py` | `tests/test_sync_log.py` | JSONL ログの記録・読み取り・表示 |
| `cli.py` | `tests/test_cli.py` | CLI コマンドの統合テスト |

## 3. テストケース詳細

### 3.1 test_config.py

| ID | テストケース | 検証内容 |
|---|---|---|
| C-01 | 正常な設定ファイルの読み込み | url, api_key, targets が正しくパースされる |
| C-02 | 環境変数 `ELABFTW_API_KEY` が優先される | 設定ファイルの api_key より環境変数が優先 |
| C-03 | URL 未設定でエラー | `sys.exit` が呼ばれる |
| C-04 | API キー未設定でエラー | `sys.exit` が呼ばれる |
| C-05 | targets 未定義でエラー | `sys.exit` が呼ばれる |
| C-06 | 設定ファイルが存在しない | `sys.exit` が呼ばれる |
| C-07 | mode/entity のデフォルト値 | 未指定時に merge/items になる |
| C-08 | each モード + experiments | mode=each, entity=experiments が正しく設定される |

### 3.2 test_client.py

| ID | テストケース | 検証内容 |
|---|---|---|
| CL-01 | get_item | 正しい URL・ヘッダーで GET リクエストが送信される |
| CL-02 | create_item | POST → PATCH の順で呼ばれ、ID が返る |
| CL-03 | update_item | PATCH リクエストに fields が含まれる |
| CL-04 | delete_item | DELETE リクエストが送信される |
| CL-05 | get_experiment / create_experiment / update_experiment | items と同様の動作 |
| CL-06 | upload_file | multipart POST → GET でアップロード結果を取得 |
| CL-07 | upload_file で URL が取得できない場合 | `{"url": None}` が返る |
| CL-08 | HTTP エラー時に例外が発生 | `requests.HTTPError` が raise される |
| CL-09 | verify_ssl=False | requests に `verify=False` が渡される |
| CL-10 | add_tag / remove_tag | 正しいエンドポイントに POST/DELETE される |
| CL-11 | list_items / list_experiments | GET リクエストで一覧が返る |
| CL-12 | delete_experiment | DELETE リクエストが送信される |
| CL-13 | update_metadata | PATCH に metadata JSON が含まれる |
| CL-14 | search_experiments | tags パラメータ付き GET が送信される |
| CL-15 | append_body | 既存 body に追記される |
| CL-16 | replace_body | body が置換される |

### 3.3 test_sync.py

#### 3.3.1 ユーティリティ関数

| ID | テストケース | 検証内容 |
|---|---|---|
| S-01 | `_compute_hash` | 同一文字列で同一ハッシュ、異なる文字列で異なるハッシュ |
| S-02 | `_count_local_images` | ローカル画像のみカウント、http(s) URL は除外 |
| S-03 | `_md_to_html` | Markdown が HTML に変換される |

#### 3.3.2 DocsSyncer（merge モード）

| ID | テストケース | 検証内容 |
|---|---|---|
| S-10 | collect_docs | 複数 md ファイルが `---` 区切りで結合される |
| S-11 | collect_docs でファイルなし | `FileNotFoundError` が発生 |
| S-12 | has_changed — 初回 | hash ファイルなしで True |
| S-13 | has_changed — 変更なし | hash 一致で False |
| S-14 | has_changed — 変更あり | hash 不一致で True |
| S-15 | save_hash / read | ハッシュファイルが正しく書き込み・読み取りされる |
| S-16 | read_item_id / save_item_id | ID ファイルの読み書き |
| S-17 | sync — 新規作成 | create_entity → update_entity が呼ばれ、ID・hash・remote_hash が保存される |
| S-18 | sync — 更新 | 既存 ID で update_entity が呼ばれる |
| S-19 | sync — 変更なし（スキップ） | update_entity が呼ばれない、False が返る |
| S-20 | sync — force | 変更なしでも update_entity が呼ばれる |
| S-21 | sync — エンティティ削除済み | 新規作成にフォールバック |
| S-22 | dry_run | ファイル数・画像数・変更有無・item_id が返る |

#### 3.3.3 画像アップロード（_rewrite_images）

| ID | テストケース | 検証内容 |
|---|---|---|
| S-25 | ローカル画像が upload_file で送信される | client.upload_file が呼ばれ、返却 URL で書き換えられる |
| S-26 | http(s) URL はそのまま保持 | upload_file が呼ばれない |
| S-27 | 画像ファイルが存在しない | 警告が出力され、元の参照が維持される |
| S-28 | docs_dir → project_root フォールバック | docs_dir になければ project_root から探す |

#### 3.3.4 競合検出（FR-11）

| ID | テストケース | 検証内容 |
|---|---|---|
| S-30 | remote_hash なし → チェックスキップ | `_check_remote_conflict` が即 return |
| S-31 | remote_hash 一致 → 正常通過 | ConflictError が発生しない |
| S-32 | remote_hash 不一致 → ConflictError | 例外メッセージにエンティティ ID が含まれる |
| S-33 | force=True → 競合チェックスキップ | ConflictError が発生しない |
| S-34 | sync 後に remote_hash が保存される | push 後に `_get_entity` で取得した body のハッシュが保存される |

#### 3.3.5 EachDocsSyncer（each モード）

| ID | テストケース | 検証内容 |
|---|---|---|
| S-40 | sync — 複数ファイル | 各ファイルが個別にエンティティとして同期される |
| S-41 | sync — 一部変更なし | 変更のないファイルはスキップされる |
| S-42 | mapping.json の読み書き | ファイル名 → エンティティ ID のマッピングが正しい |
| S-43 | 競合検出（each） | remote_hash 不一致で ConflictError |
| S-44 | sync 後に remote_hash が保存される | 各ファイルの remote_hash が保存される |

### 3.4 test_sync_log.py（FR-13）

| ID | テストケース | 検証内容 |
|---|---|---|
| L-01 | record — 正常書き込み | JSONL ファイルに1行追記される |
| L-02 | record — 複数回書き込み | 行数が増える |
| L-03 | record — ディレクトリ自動作成 | 親ディレクトリが存在しなくても作成される |
| L-04 | record — 書き込み失敗（best-effort） | 読み取り専用パスでも例外が発生しない |
| L-05 | read_log — 正常読み取り | 最新 N 件が返る |
| L-06 | read_log — limit 指定 | 指定件数だけ返る |
| L-07 | read_log — 壊れた行をスキップ | 不正な JSON 行が無視される |
| L-08 | read_log — ファイルなし | 空リストが返る |
| L-09 | read_log — 壊れた UTF-8 | UnicodeDecodeError が発生しない |
| L-10 | format_log — 正常表示 | タイムスタンプ・action・target・entity が含まれる |
| L-11 | format_log — 空リスト | 「同期ログはまだありません」が返る |

### 3.5 test_cli.py

#### 3.5.1 cmd_sync

| ID | テストケース | 検証内容 |
|---|---|---|
| CLI-01 | push 正常実行 | syncer.sync() が呼ばれ、更新件数が表示される |
| CLI-02 | --dry-run | syncer.sync() が呼ばれない |
| CLI-03 | --force | syncer.sync(force=True) が呼ばれる |
| CLI-04 | -t でターゲット指定 | 指定ターゲットのみ同期される |
| CLI-05 | ConflictError 時の表示 | 「⚠ 競合検出」が stderr に出力される |

#### 3.5.2 cmd_pull

| ID | テストケース | 検証内容 |
|---|---|---|
| CLI-10 | pull each モード | ファイルが作成され、mapping・hash・remote_hash が保存される |
| CLI-11 | pull merge モード | ファイルが作成され、ID・hash・remote_hash が保存される |
| CLI-12 | pull --id 指定 | 指定 ID のみ取得される |
| CLI-13 | pull 既存ファイルスキップ | --force なしで既存ファイルが上書きされない |
| CLI-14 | pull --force | 既存ファイルが上書きされる |

#### 3.5.3 cmd_clone（FR-12）

| ID | テストケース | 検証内容 |
|---|---|---|
| CLI-20 | clone 正常実行 | ディレクトリ・設定ファイル・docs・mapping が作成される |
| CLI-21 | clone 複数 ID | 複数ファイルが取得される |
| CLI-22 | clone 既存非空ディレクトリ | エラーで終了（exit 1） |
| CLI-23 | clone 全件失敗 | エラーで終了、ディレクトリがクリーンアップされる |
| CLI-24 | clone 全件失敗（既存空ディレクトリ） | ディレクトリ自体は残り、生成ファイルのみ削除 |
| CLI-25 | clone の .gitignore | `.elab-sync-ids/` と `.elab-sync.yaml` が含まれる |
| CLI-26 | ELABFTW_API_KEY 未設定 | エラーで終了 |

#### 3.5.4 cmd_log（FR-13）

| ID | テストケース | 検証内容 |
|---|---|---|
| CLI-30 | log 正常表示 | sync_log.format_log の出力が表示される |
| CLI-31 | log --limit | 指定件数で read_log が呼ばれる |

#### 3.5.5 cmd_init / cmd_update

| ID | テストケース | 検証内容 |
|---|---|---|
| CLI-40 | init 正常実行 | `.elab-sync.yaml` が作成される |
| CLI-41 | init 既存ファイル上書き確認 | 上書き確認プロンプトが表示される |
| CLI-42 | init テンプレート展開 | `.gitignore`, `README.md`, `docs/` が作成される |
| CLI-43 | update 実行 | subprocess が呼ばれる |

#### 3.5.6 cmd_diff / cmd_status

| ID | テストケース | 検証内容 |
|---|---|---|
| CLI-50 | diff 差分あり | unified diff が出力される |
| CLI-51 | diff 差分なし | 「差分なし」が表示される |
| CLI-52 | status 変更あり | 「変更あり」が表示される |
| CLI-53 | status 最新 | 「最新」が表示される |

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
- テスト実行: `uv run pytest tests/ -v`

## 5. テストケース数

| カテゴリ | 件数 |
|---|---|
| config | 8 |
| client | 16 |
| sync（ユーティリティ） | 3 |
| sync（merge） | 13 |
| sync（画像アップロード） | 4 |
| sync（競合検出） | 5 |
| sync（each） | 5 |
| sync_log | 11 |
| cli（sync） | 5 |
| cli（pull） | 5 |
| cli（clone） | 7 |
| cli（log） | 2 |
| cli（init/update） | 4 |
| cli（diff/status） | 4 |
| **合計** | **92** |

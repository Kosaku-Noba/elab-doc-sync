# API リファレンス

→ [同期エンジン](07_SYNC_ENGINE.md) | [CLI リファレンス](05_CLI_REFERENCE.md)

本パッケージは CLI ツールとして設計されており（単一プロセス・単一スレッド）、ライブラリとしての利用は想定していない。`elab_doc_sync` のトップレベルで公開しているのは `ELabFTWClient`、`EachDocsSyncer`、`ConflictError`、`load_config`、`Config`、`TargetConfig`、`sync_log` のみ。以下の `_` で始まる関数は内部実装で、予告なく変わる。

## モジュール構成

### `elab_doc_sync.sync`

同期ロジックの中核。

#### クラス

| クラス | 説明 |
|---|---|
| `EachDocsSyncer` | 1ファイル=1エンティティの同期。`inspect()` で状態判定、`sync()` で push、pull・diff・mv・rm・link の処理を持つ |
| `LinkTargets` | 同じホストの全ターゲットで追跡中の文書と、ローカルパスの対応 |
| `ConflictError` | リモート競合時に発生する例外 |

#### 内部関数 — 画像・動画・ファイル処理

| 関数 | 説明 |
|---|---|
| `_rewrite_images(body, entity, entity_id, client, docs_dir, project_root, strict=False, stale_out=None)` | ローカル画像をアップロードし URL に書き換え。`stale_out` に差し替えた古い版の添付 ID を集める |
| `_rewrite_videos(...)` | 動画をアップロードし `<video>` タグに変換（引数は同上） |
| `_rewrite_file_links(...)` | 非画像・非動画ファイルをアップロードし URL 書き換え（引数は同上） |
| `_download_images(body, entity, entity_id, client, docs_dir, strict=False, ...)` | リモート画像をダウンロードしローカルリンクに書き換え |
| `_download_attachments(entity, entity_id, client, attachments_dir, strict=False, ...)` | 添付ファイルをダウンロード |
| `_normalize_remote_image_urls(body, entity, entity_id, client, uploads=None)` | リモート画像 URL を正規化 |
| `_resolve_asset_path(docs_dir, project_root, source, strict=False)` | 画像・ファイルの参照先を解決（プロジェクト外・隠しファイル・シンボリックリンクを拒否） |

#### 内部関数 — 本文変換

| 関数 | 説明 |
|---|---|
| `_md_to_html(text)` | 数式保護付き Markdown → HTML 変換 |
| `_remote_markdown(data, target)` | eLabFTW の本文を Markdown にする（HTML は変換、Markdown はエスケープを戻す） |
| `_dropped_angle_fragments(sent, stored)` | eLabFTW が保存時に削除した `<…>` を検出 |

#### 内部関数 — リンク変換

| 関数 | 説明 |
|---|---|
| `_rewrite_local_links(body, entity, base_url, mapping, all_mappings=None, *, source=None, links=None)` | `[text](./file.md)` → eLabFTW URL に変換。`links` があれば、`source` からの相対パスで全ターゲットの文書を解決 |
| `_rewrite_elab_links_to_local(body, base_url, mapping, entity, all_mappings=None, target_docs_dir="", *, source=None, links=None)` | eLabFTW URL → `[text](./file.md)` に逆変換。`links` があれば、`source` からリンク先の実際の場所への相対パスにする |
| `EachDocsSyncer.link_targets(mapping=None)` | `LinkTargets` を作る |
| `_hosts_match(base_url, link_base)` | ホスト完全一致判定（urlparse） |

#### 内部関数 — カウント・判定

| 関数 | 説明 |
|---|---|
| `_count_local_images(body)` | 本文中のローカル画像リンク数 |
| `_count_local_videos(body)` | 本文中のローカル動画リンク数 |
| `_count_local_file_links(body)` | 本文中の非画像・非動画ローカルファイルリンク数 |
| `_count_local_attachments(attachments_dir)` | attachments_dir 内の非画像ファイル数 |
| `_is_image(filename)` | 画像拡張子判定 |
| `_is_video(filename)` | 動画拡張子判定 |
| `_compute_hash(body)` | SHA-256 ハッシュ（先頭16文字） |
| `_compute_file_hash(path)` | ファイルの SHA-256 ハッシュ |
| `_compute_meta_hash(title, category, tags)` | メタデータのハッシュ |

#### 内部関数 — 同期補助

| 関数 | 説明 |
|---|---|
| `_sync_tags(client, entity_type, entity_id, desired_tags)` | 設定タグを追記し既存タグを保持。成功・追加不要なら `True`、取得・更新失敗なら `False`。タグなしのnull応答は空タグとして扱う |
| `_sync_category(client, entity_type, entity_id, category, current=None)` | カテゴリ設定。現在値と同じなら PATCH を省略。成功・不要なら `True`、失敗なら警告を出して `False` |
| `_sync_links(client, entity_type, entity_id, desired_links)` | `links` の記事へのリンクのうち未作成のものを追加。既存は削除しない。1件でも失敗すれば `False`（残りは続行） |
| `_sync_attachments(attachments_dir, entity, entity_id, client, *, force=False, pattern="*", prune=False, strict=False)` | 添付ファイルの差分同期 |
| `_shell_quote(value, windows=None)` | 案内に表示するコマンドの引用（PowerShell 対応） |

#### 正規表現定数

| 定数 | パターン | 用途 |
|---|---|---|
| `IMAGE_RE` | `!\[...\](...)`  | 画像リンク検出 |
| `_LINK_RE` | `(?<!!)\[...\](...)` | 通常リンク検出（画像除外） |
| `_ELAB_URL_RE` | eLabFTW 記事 URL | pull 時の逆変換用 |
| `UPLOAD_ID_RE` | `/uploads/{id}` | アップロード ID 抽出 |
| `UPLOAD_LONGNAME_RE` | `?f=...` / `&f=...` | アップロードの `long_name` 抽出 |

#### 定数

| 定数 | 値 | 用途 |
|---|---|---|
| `IMAGE_EXTENSIONS` | `.png, .jpg, .jpeg, .gif, .svg, .webp, .bmp, .ico` | 画像判定 |
| `VIDEO_EXTENSIONS` | `.mp4, .webm` | 動画判定 |
| `MD_EXTENSIONS` | `tables, fenced_code, codehilite, toc, nl2br` | Markdown → HTML 変換の拡張 |

---

### `elab_doc_sync.merge`

pull 時の 3-way マージ。

| 関数・定数 | 説明 |
|---|---|
| `merge_text(base, local, remote, remote_label="")` | 行単位の 3-way マージ。`(結果, 競合数)` を返す。`base` が `None` なら差のある箇所をすべて競合にする |
| `has_conflict_markers(text)` | esync の競合マーカー（`<<<<<<< ローカル` と `>>>>>>> eLabFTW`）が残っているか |
| `LOCAL_MARKER` / `SEPARATOR` / `REMOTE_MARKER` | `<<<<<<< ローカル` / `=======` / `>>>>>>> eLabFTW` |

---

### `elab_doc_sync.safety`

ローカル書き込みの安全化。

| 関数・定数 | 説明 |
|---|---|
| `atomic_write(path, data, mode=None)` | 同じディレクトリの一時ファイルに書いて fsync してから置換 |
| `write_json(path, data)` | `atomic_write` で JSON を保存 |
| `safe_path(root, relative)` | `root` 配下に収まるパスだけを返す（外へ出るパス・シンボリックリンクを拒否） |
| `project_lock(root)` | プロジェクト単位の OS ロック（`fcntl` / `msvcrt`） |
| `project_command(fn)` | CLI の書き込みコマンド用デコレータ。ロックを取り、未完了の復旧記録があれば停止 |
| `snapshot(root, paths, reason, remote=None)` | `.elab-sync-backups/` にバックアップを作り ID を返す |
| `read_snapshot(root, backup_id)` | バックアップの記録を読む |
| `local_transaction(root, paths, reason, *, recovering=False)` | バックアップと復旧記録で囲むコンテキストマネージャ |
| `restore(root, backup_id, dry_run=False)` | バックアップの復元（復元直前もバックアップ） |
| `BACKUPS` / `RECOVERY` | `.elab-sync-backups` / `.elab-sync-recovery.json` |

---

### `elab_doc_sync.client`

eLabFTW API v2 クライアント（`ELabFTWClient(base_url, api_key, verify_ssl=True)`）。

| メソッド | 説明 |
|---|---|
| `get_user_info()` | ユーザー情報（`/users/me`） |
| `get_active_team()` | 現在のチーム（ID, 名前） |
| `list_items()` | リソース一覧 |
| `get_item(item_id)` | リソース取得。削除済み（`state=3`）は HTTP 404 と同じ例外にする |
| `create_item(title, body)` | リソース作成（ID を返す） |
| `update_item(item_id, **fields)` | リソース更新 |
| `delete_item(item_id)` | リソース削除 |
| `list_experiments()` | 実験ノート一覧 |
| `get_experiment(exp_id)` | 実験ノート取得。削除済みの扱いは `get_item` と同じ |
| `create_experiment(title, body)` | 実験ノート作成（ID を返す） |
| `update_experiment(exp_id, **fields)` | 実験ノート更新 |
| `delete_experiment(exp_id)` | 実験ノート削除 |
| `search_experiments(tags)` | タグで実験ノートを検索 |
| `append_body(exp_id, text)` / `replace_body(exp_id, body)` | 実験ノート本文の追記・置換 |
| `get_entity(entity_type, entity_id)` | 汎用エンティティ取得（削除済みの判定はしない） |
| `patch_entity(entity_type, entity_id, **fields)` | 汎用エンティティ更新 |
| `upload_file(entity_type, entity_id, filepath, comment="")` | ファイルアップロード（1回リトライ）。POST 応答の Location で新しい添付を特定 |
| `list_uploads(entity_type, entity_id)` | アップロード一覧 |
| `delete_upload(entity_type, entity_id, upload_id)` | アップロード削除 |
| `download_upload(*, entity_type, entity_id, upload_id)` | アップロードダウンロード |
| `list_items_types()` / `list_experiments_categories()` | カテゴリ一覧（リソース / 実験ノート） |
| `list_categories(entity_type)` | 種別に応じたカテゴリ一覧 |
| `resolve_category_id(entity_type, category, current=None)` | カテゴリ名→ID 解決（一覧にない場合は `current` の `category_title` も使う） |
| `resolve_category_name(entity_type, category_id)` | カテゴリ ID→名前 |
| `get_tags(entity_type, entity_id)` | タグ取得（null 応答は空リスト） |
| `add_tag(entity_type, entity_id, tag)` | タグ追加 |
| `remove_tag(entity_type, entity_id, tag_id)` | タグ削除 |
| `untag_by_name(entity_type, entity_id, tag_name)` | 名前でタグを外す。外したら `True` |
| `get_metadata(entity_type, entity_id)` | メタデータ（null・不正 JSON・非 dict は空 dict） |
| `get_metadata_raw(entity_type, entity_id)` | メタデータの生文字列 |
| `update_metadata(entity_type, entity_id, metadata)` | メタデータ更新 |
| `list_links(entity_type, entity_id, link_type)` | `link_type`（`experiments` / `items`）へのリンク一覧（`GET /{entity_type}/{id}/{link_type}_links`） |
| `add_link(entity_type, entity_id, link_type, target_id)` | リンク作成（`POST .../{link_type}_links/{target_id}`、`{"action": "create"}`） |
| `remove_link(entity_type, entity_id, link_type, target_id)` | リンク削除（リンク先は削除しない） |

---

### `elab_doc_sync.config`

YAML 設定読み込み・バリデーション。

| 関数/クラス | 説明 |
|---|---|
| `load_config(path)` | `.elab-sync.yaml` を読み込み `Config` を返す。不正な設定はメッセージを出して終了コード 2 |
| `get_client_for_target(config, target)` | ターゲットの `profile` / `team` から接続情報 `(url, api_key, verify_ssl)` を返す |
| `update_target_in_yaml(config_path, target_index, **fields)` | YAML のターゲット設定を更新 |
| `append_target_to_yaml(config_path, target_data)` | YAML に新しいターゲットを追記 |
| `Config` | 全体設定データクラス（`url`, `api_key`, `verify_ssl`, `targets`, `profiles`） |
| `TargetConfig` | ターゲット設定データクラス（[キー一覧](04_CONFIGURATION.md#キー一覧)） |
| `ProfileConfig` | プロファイル設定データクラス（`name`, `url`, `api_key`, `verify_ssl`, `team`） |
| `BODY_FORMAT_DEFAULT` / `BODY_FORMAT_INIT` | `html` / `md` |

---

### `elab_doc_sync.sync_log`

同期ログの記録・表示。

| 関数・定数 | 説明 |
|---|---|
| `record(log_path, *, action, target, entity, entity_id, files=None, user=None)` | ログエントリを JSONL に追記（JST のタイムスタンプ。`user` は指定時のみ）。書き込み失敗は無視 |
| `read_log(log_path, limit=20)` | 最新 `limit` 件を古い順に返す。壊れた行は飛ばす |
| `format_log(entries)` | 表示用にフォーマット |
| `DEFAULT_LOG_PATH` | `.elab-sync-ids/sync-log.jsonl` |

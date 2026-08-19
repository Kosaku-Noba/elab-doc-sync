# API リファレンス

→ [同期エンジン](07_SYNC_ENGINE.md) | [CLI リファレンス](05_CLI_REFERENCE.md)

## モジュール構成

### `elab_doc_sync.sync`

同期ロジックの中核。

#### クラス

| クラス | 説明 |
|---|---|
| `EachDocsSyncer` | 1ファイル=1エンティティの同期 |
| `ConflictError` | リモート競合時に発生する例外 |

#### 内部関数 — 画像・動画・ファイル処理

| 関数 | 説明 |
|---|---|
| `_rewrite_images(body, entity, entity_id, client, docs_dir, project_root)` | ローカル画像をアップロードし URL に書き換え |
| `_rewrite_videos(body, entity, entity_id, client, docs_dir, project_root)` | 動画をアップロードし `<video>` タグに変換 |
| `_rewrite_file_links(body, entity, entity_id, client, docs_dir, project_root)` | 非画像・非動画ファイルをアップロードし URL 書き換え |
| `_download_images(body_md, entity_type, eid, client, docs_dir)` | リモート画像をダウンロードしローカルリンクに書き換え |
| `_download_attachments(entity_type, eid, client, attachments_dir)` | 添付ファイルをダウンロード |
| `_normalize_remote_image_urls(body_md, entity_type, eid, client)` | リモート画像 URL を正規化 |

#### 内部関数 — リンク変換

| 関数 | 説明 |
|---|---|
| `_rewrite_local_links(body, entity, base_url, mapping, all_mappings=None)` | `[text](./file.md)` → eLabFTW URL に変換 |
| `_rewrite_elab_links_to_local(body, base_url, mapping, entity, all_mappings=None, target_docs_dir="")` | eLabFTW URL → `[text](./file.md)` に逆変換 |
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
| `_sync_tags(client, entity_type, entity_id, desired_tags)` | タグ追記同期（best-effort） |
| `_sync_category(client, entity_type, entity_id, category)` | カテゴリ設定（best-effort） |
| `_sync_attachments(attachments_dir, entity, entity_id, client, ...)` | 添付ファイルのサイズ差分同期 |
| `_md_to_html(body)` | 数式保護付き Markdown → HTML 変換 |

#### 正規表現定数

| 定数 | パターン | 用途 |
|---|---|---|
| `IMAGE_RE` | `!\[...\](...)`  | 画像リンク検出 |
| `_LINK_RE` | `(?<!!)\[...\](...)` | 通常リンク検出（画像除外） |
| `_ELAB_URL_RE` | eLabFTW 記事 URL | pull 時の逆変換用 |
| `UPLOAD_ID_RE` | `/uploads/{id}` | アップロード ID 抽出 |

#### 定数

| 定数 | 値 | 用途 |
|---|---|---|
| `IMAGE_EXTENSIONS` | `.png, .jpg, .jpeg, .gif, .svg, .webp, .bmp, .ico` | 画像判定 |
| `VIDEO_EXTENSIONS` | `.mp4, .webm` | 動画判定 |

---

### `elab_doc_sync.client`

eLabFTW API v2 クライアント。

| メソッド | 説明 |
|---|---|
| `list_items()` | リソース一覧 |
| `get_item(item_id)` | リソース取得 |
| `create_item(title, body)` | リソース作成 |
| `update_item(item_id, **fields)` | リソース更新 |
| `delete_item(item_id)` | リソース削除 |
| `list_experiments()` | 実験ノート一覧 |
| `get_experiment(exp_id)` | 実験ノート取得 |
| `create_experiment(title, body)` | 実験ノート作成 |
| `update_experiment(exp_id, **fields)` | 実験ノート更新 |
| `delete_experiment(exp_id)` | 実験ノート削除 |
| `get_entity(entity_type, entity_id)` | 汎用エンティティ取得 |
| `patch_entity(entity_type, entity_id, **fields)` | 汎用エンティティ更新 |
| `upload_file(entity_type, entity_id, filepath)` | ファイルアップロード（1回リトライ） |
| `list_uploads(entity_type, entity_id)` | アップロード一覧 |
| `delete_upload(entity_type, entity_id, upload_id)` | アップロード削除 |
| `download_upload(entity_type, entity_id, upload_id)` | アップロードダウンロード |
| `get_tags(entity_type, entity_id)` | タグ取得 |
| `add_tag(entity_type, entity_id, tag)` | タグ追加 |
| `untag(entity_type, entity_id, tag_id)` | タグ削除 |
| `resolve_category_id(entity_type, category)` | カテゴリ名→ID 解決 |
| `get_user_info()` | ユーザー情報 |

---

### `elab_doc_sync.config`

YAML 設定読み込み・バリデーション。

| 関数/クラス | 説明 |
|---|---|
| `load_config(path)` | `.elab-sync.yaml` を読み込み `Config` を返す |
| `get_client_for_target(config, target)` | ターゲットのプロファイルから接続情報を返す |
| `update_target_in_yaml(config_path, target, key, value)` | YAML のターゲット設定を更新 |
| `append_target_to_yaml(config_path, target_dict)` | YAML に新しいターゲットを追記 |
| `Config` | 全体設定データクラス |
| `TargetConfig` | ターゲット設定データクラス |
| `ProfileConfig` | プロファイル設定データクラス |

---

### `elab_doc_sync.sync_log`

同期ログの記録・表示。

| 関数 | 説明 |
|---|---|
| `record(log_path, action, target, entity, entity_id, files)` | ログエントリを JSONL に追記 |
| `read_log(log_path, limit)` | ログを読み込み |
| `format_log(entries)` | 表示用にフォーマット |

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
| `_body_links(body)` | Markdown の表示結果で確認したインライン記法の画像・リンクの種類、URL、元の本文中の位置を返す。空のリンク先は返さない。ローカルリンクの置換範囲を確定できない場合はエラー |
| `_rewrite_images(body, entity, entity_id, client, docs_dir, project_root, strict=False, stale_out=None, uploaded=None, verified=None, record=None, preferred=(), used_urls=None)` | ローカル画像をアップロードし URL に書き換え。`stale_out` に旧版候補の ID、`uploaded` に今回送信した添付の ID と名前・サイズ・SHA-256 を集める。`verified` は参照ごとの照合済みハッシュ、`record(receipt)` は URL 未確定時を含む受領記録の保存先、`preferred` は再開時に照合する確認済み ID、`used_urls` は本文に採用した ID と URL。push は本文の更新前にリモートの一覧・内容と照合する |
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
| `_shell_quote(value, windows=None)` | 案内に表示するコマンドの引用（PowerShell 対応） |

#### 正規表現定数

| 定数 | パターン | 用途 |
|---|---|---|
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
| `search_experiments(tags)` | タグで実験ノートを検索（`esync search` は `search.py` が `/items`・`/experiments` の検索パラメータを直接使う） |
| `append_body(exp_id, text)` / `replace_body(exp_id, body)` | 実験ノート本文の追記・置換 |
| `get_entity(entity_type, entity_id)` | 汎用エンティティ取得（削除済みの判定はしない） |
| `patch_entity(entity_type, entity_id, **fields)` | 汎用エンティティ更新 |
| `upload_file(entity_type, entity_id, filepath, comment="")` | ファイルアップロード。POST は一度。URL を取得できた場合の `receipt` は `id`・`name`・`size`・`sha256` を含む。正常応答では Location の ID を使う。ID が一覧にまだない場合や、受領した ID の名前・long_name・storage が未反映の場合は `url=None` と受領記録 `receipt` を返す。storage の数値 0 は有効。Location がなければ、旧ハッシュの候補は実体の SHA-256 を確認し、新規同名候補のうちハッシュ一致、ハッシュ未提供の順に最大 ID を採用し、候補がなければ `url=None`。応答不明時は新規 ID・名前・SHA-256 が一意に一致した場合に続行し、特定できない場合は確認手順を含む `UploadConfirmationError`。例外の `receipt` は受領した `id`・`name`・`size`・`sha256`、受領 ID がないときは `None` |
| `list_uploads(entity_type, entity_id)` | アップロード一覧 |
| `delete_upload(entity_type, entity_id, upload_id)` | アップロード削除 |
| `download_upload(*, entity_type, entity_id, upload_id)` | アップロードダウンロード |
| `upload_digest(*, entity_type, entity_id, upload_id)` | 本文用添付の照合用 SHA-256。テキストも含めて応答を分割して読み、16 進文字列を返す。呼び出し側がローカルの値と比較する |
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
| `get_client_for_target(config, target)` | ターゲットの `profile` / `team` から接続情報 `(url, api_key, verify_ssl)` を返す。プロファイルが `api_key_env` を指定していて、その環境変数が未設定・空のときは、環境変数の名前を示す `ValueError`（キーの値は含めない） |
| `profile_connection(profile)` | `ProfileConfig` から接続情報 `(url, api_key, verify_ssl)` を返す。`api_key_env` を指定していて、その環境変数が未設定・空のときは、環境変数の名前を示す `ValueError`（キーの値は含めない） |
| `update_target_in_yaml(config_path, target_index, **fields)` | YAML のターゲット設定を更新 |
| `append_target_to_yaml(config_path, target_data)` | YAML に新しいターゲットを追記 |
| `Config` | 全体設定データクラス（`url`, `api_key`, `verify_ssl`, `targets`, `profiles`） |
| `TargetConfig` | ターゲット設定データクラス（[キー一覧](04_CONFIGURATION.md#キー一覧)） |
| `ProfileConfig` | プロファイル設定データクラス（`name`, `url`, `api_key`, `verify_ssl`, `team`, `api_key_env`）。`api_key_env` を指定したときは `api_key` に環境変数の値が入る。環境変数は設定の読み込み時（`load_config`）に一度だけ `api_key` に取り込まれ、読み込みの後に環境変数を変えても反映されない |
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

### `elab_doc_sync.result`

コマンドの実行結果（MCP 対応の準備として v1.3.0 より後に追加）。

| クラス・関数 | 説明 |
|---|---|
| `CommandResult(exit_code=0, data={}, messages=[], warnings=[], echo=None)` | `run_*` が返す結果。`data` は機械可読な結果（JSON 化できる値のみ、API キーは含めない）、`messages` は人向けの表示行、`warnings` は警告・エラーの行。同期エンジンで従来 stdout に表示していた警告は CLI では同じ出力先を保つ |
| `CommandResult.say(message="")` | 表示行を追加し、`echo` があれば `echo(message)` を呼ぶ |
| `CommandResult.warn(message)` | 警告・エラーの行を追加し、`echo` があれば `echo(message, stderr=True)` を呼ぶ |
| `CommandResult.fail(message, exit_code=1)` | `warn` して終了コードを設定し、自身を返す |
| `CommandResult.to_dict()` | `exit_code`・`data`・`messages`・`warnings` の辞書 |
| `returns_partial_result(fn)` | `run_*` 用のデコレーター。途中で例外になったら、実行中に作った最初の `CommandResult` を例外の `partial_result` 属性に付ける（結果を作る前の例外には付けない） |
| `cli_echo(message, stderr=False)` | CLI 用の表示先（`stderr=True` は標準エラー出力）。`cmd_*` はこれを `echo` に渡して 1 行ずつ表示する |
| `redact(text, *secrets)` | `text` 中の秘密値（そのまま・repr・バイト列表記・改行で区切った 4 文字以上の各部分）を `***` に置き換える |

### `elab_doc_sync.cli` の `run_*`

`cmd_*(args)` は `run_*(args, echo=cli_echo).exit_code` を返す。`run_*` は `echo` を省略すると何も表示しない。

成功・失敗の判定:

- `exit_code` は CLI の終了コードと同じ。`run_status` は競合などの要対応状態で 1。引数の誤り（`tag` の `--id` と `--entity` の片方だけ、`metadata set` の `key=value` 以外、`new` の `--template-id` なし・既存ファイル）は `warnings` に理由を入れて 1。ローカル操作の終了判定は下記参照
- 書き換え系の各件の `result`（下表）で、実際に変更したか（`added` など）、dry-run の予定か（`would_*`）、変更不要だったか（`exists`・`already`・`not_found`・`self`）を区別する
- `run_verify` は問題を見つけても `exit_code` は 0。`data["issues"]` と各文書の `ok` を確認する
- `run_whoami` は接続に失敗したプロファイルも `exit_code` 0 で返し、そのプロファイルの `error` に理由を入れる（API キーは `redact` で除く）
- `run_clone` は次の順に確かめる。(1) 本実行のときだけ、作成先のロックと未完了の復旧記録を確かめ、失敗すると例外になる（CLI は終了コード 1。`dry_run=True` では確かめない）。(2) `--url` が [設定ファイル](04_CONFIGURATION.md) の `url` の条件を満たさなければ、何も作らずに `exit_code` 2 の `CommandResult` を返す。(3) `ELABFTW_API_KEY` が未設定または空白だけなら `exit_code` 1 を返す。(2)・(3) では理由を `warnings` に入れ、`data` は `dry_run` と空の `documents` だけで `server` を含まない。それ以降の結果では、`data["server"]` は認証情報を除いた URL
- 設定の誤り・通信の失敗など、上記以外のエラーは `CommandResult` にならず例外として呼び出し元に伝わる（CLI は終了コード 2 / 1 にする）。呼び出し側で例外を処理する。結果を作った後の例外には `partial_result` が付く。リモート書き換え系の各件は送信前に記録され、`result` のない件は完了未確認（応答を受け取れなかった場合を含む）なので、再試行の前に実際の状態を確認する（[設計判断 13.4](12_DESIGN_DECISIONS.md)）
- `run_*` が使う `read_config` は設定の検証失敗を `ConfigError`（`ValueError` の派生型）で通知する。互換 API の `config.load_config` は従来どおり理由を表示して `SystemExit(2)` を送出する
- 書き換え系（`tag`・`relate`・`metadata`・`category`・`entity-status`）の各件と `run_category` の `data` には、接続先のベース URL `server` が入る

| 関数 | `data` |
|---|---|
| `run_status` | `documents`（`target`・`file`・`entity`・`entity_id`・`state`・`remote_changes`・`error`・`next_actions`）、`recovery_pending` |
| `run_log` | `entries`（同期ログのエントリ） |
| `run_list` | `entity`、`results`（`id`・`title`・`status`） |
| `run_search` | `results`・`count`・`has_more`・`next_offset`・`truncated`（`--json` の出力と同じ。`--json` の有無に関わらず） |
| `run_whoami` | `profiles`（`profile`・`url`・`error`・`firstname`・`lastname`・`email`・`userid`・`team`・`teams`） |
| `run_verify` | `documents`（`target`・`file`・`entity`・`entity_id`・`ok`・`problem`）、`unsynced_targets`、`issues` |
| `run_backup` | `backups`（`id`・`reason`） |
| `run_profile_list` | `profiles`（`name`・`url`・`has_api_key`・`verify_ssl`）。`url` は、有効なら認証情報を伏せた URL、形が不正なら文字列 `（不正な URL）`、未設定なら `null`。`（不正な URL）` を接続先として使わないこと |
| `run_tag` | `action`・`dry_run`・`unsynced_targets`、`entities`（`target`・`entity`・`entity_id`。list は `tags`、add/remove は `tag`・`result`: `added`/`exists`/`would_add`/`removed`/`not_found`/`would_remove`） |
| `run_relate` | `action`・`dry_run`・`unsynced_targets`、`sources`（`entity`・`entity_id`。list は `links`: 種別ごとの `id`・`title`）、`changes`（`entity`・`entity_id`・`to_entity`・`to_id`・`result`: `added`/`exists`/`would_add`/`removed`/`not_found`/`would_remove`/`self`） |
| `run_metadata` | `action`・`dry_run`・`unsynced_targets`、`entities`（`target`・`entity`・`entity_id`・`metadata`。set は `result`: `updated`/`would_update`、既存を読めなかったとき `unreadable_existing`） |
| `run_category` | `action`。list は `entity`・`categories`（`id`・`title`）、show は `entity`・`entity_id`・`category`（`id`・`title` または null）、set は `entity`・`entity_id`・`dry_run`・`category_id`・`result`（`set`/`already`/`would_set`） |
| `run_entity_status(args, echo=None, confirm=None)` | `action`・`dry_run`・`unsynced_targets`、`entities`（`target`・`entity`・`entity_id`。show は `status`、set は `result`: `changed`/`would_change`/`already` と dry-run 時の `current`）、set は `status_id`、確認で中止したとき `cancelled`。`--id` なしで複数件を変更するときは `confirm(prompt) -> bool` で確認し、`confirm` が None なら変更せず `ValueError` |
| `run_new` | list は `templates`（`id`・`title`）。作成は `path`・`title`・`template_id`・`template_title`・`dry_run`・`created` |

| ローカル操作 | 主な `data` |
|---|---|
| `run_push` | ターゲット別の更新・スキップ・失敗件数。dry-run では `targets[].documents` にファイル名、変更の有無、ID、添付種別ごとの件数。各文書の `error` を先に確認する。件数や `changed` の計算に失敗した文書では、それらの項目を省略する。件数の計算後に削除候補の照合に失敗した文書は、件数と `changed` を保持する。`prune_attachments=True` かつ添付ディレクトリ設定ありなら削除候補を `prune_candidates`（`id`・`name`）に返す。確認に失敗した文書には代わりに `error` が入り、終了コードは 1 |
| `run_pull` | `documents` に取得、取得予定、スキップ、エラーの明細。`conflict_files` は競合を残したパス |
| `run_diff` | `documents` にパス、ID、状態と該当する差分行（`local_diff`、`remote_diff`、旧形式の `direct_diff`）。`has_diff` は全体の差分の有無 |
| `run_clone` | 作成先 `path`、サーバー、種別、ID ごとの結果。実際に作成した場合の件数は `cloned` |
| `run_link` / `run_mv` | 紐付け先パスと ID、または移動元・移動先と ID |
| `run_rm` | `documents` に追跡解除の対象、`local` にファイル削除の指定 |
| `run_restore` | バックアップ ID と復元対象の `paths` |

各変更操作は `dry_run` を結果に含める。CLI と直接呼び出しの両方で、本実行時には同じプロジェクトロックと復旧チェックが働く。途中まで成功した `pull` や `clone` は終了コードと文書ごとの結果を併せて確認する。

`run_pull(args, echo=None, choose_target=None)` は、保存先が曖昧で自動選択も指定されない場合に選択を求める。コールバックを省略すると、その ID の結果は `needs_target` となり、スキップとして数える。対話可能な CLI は `choose_target(config, entity, title)` を渡す。既存ターゲットを返すとそこに保存し、`"SKIP"` はスキップ、`None` は新規ターゲット作成を表す。dry-run では対話しない。

`pull` は ID に種別がなければ終了コード 2、取得失敗または競合マーカーが残れば 1 を返す。今回のマージで競合マーカーが生じた文書は `data["conflict_files"]` から、既存マーカーによる拒否や取得失敗は各明細の `error` から判定する。`diff` は取得失敗で 1、セレクター不正で 2 を返し、成功時は `data["has_diff"]` で差分の有無を判定する。`push` のターゲット別 `failed` は文書単位の失敗で、全体の失敗件数にはターゲットの中断（`error`）も含む。中断までの確定件数は保持する。保存時に本文の一部が欠落した文書は更新・失敗の両方に数える。

`rm` の `tracking` は予定（`would_untrack`）、完了未確認（`unconfirmed`）、解除済み（`untracked`）を表す。ローカル削除を指定すると、ファイルの不在を確認した件に `file_absent: true` が付く。途中失敗時にこの値がなければ追跡解除済みでもファイルの不在は未確認。`restore` の dry-run は例えば `paths: [{"path": "docs", "kind": "directory"}]` を返す。`file` はファイル、`absent` は退避時に存在せず復元で取り除く対象を表す。

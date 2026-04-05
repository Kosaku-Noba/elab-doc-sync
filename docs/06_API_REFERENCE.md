# API リファレンス

→ [CLI リファレンス](05_CLI_REFERENCE.md) | [同期エンジン](07_SYNC_ENGINE.md)

## config.py

### `Config`

```python
@dataclass
class Config:
    url: str              # eLabFTW の URL
    api_key: str          # API キー
    verify_ssl: bool      # SSL 検証
    targets: list[TargetConfig]
```

### `TargetConfig`

```python
@dataclass
class TargetConfig:
    title: str            # エンティティタイトル
    docs_dir: str         # Markdown ディレクトリ
    id_file: str          # ID 保存先
    pattern: str = "*.md"
    mode: str = "merge"   # "merge" / "each"
    entity: str = "items" # "items" / "experiments"
    tags: list[str] = []  # push 時に自動追加するタグ（追記のみ）
```

### `load_config(config_path: Path) -> Config`

YAML ファイルを読み込み `Config` を返す。バリデーション失敗時は日本語エラーメッセージを表示し `sys.exit(1)`。

---

## client.py — `ELabFTWClient`

### コンストラクタ

```python
ELabFTWClient(base_url: str, api_key: str, verify_ssl: bool = True)
```

### リソース操作

| メソッド | 戻り値 | 説明 |
|---|---|---|
| `list_items()` | `list[dict]` | 全リソース取得 |
| `get_item(item_id: int)` | `dict` | リソース取得 |
| `create_item(title="", body="")` | `int` | リソース作成、ID を返す |
| `update_item(item_id, **fields)` | `None` | リソース更新（PATCH） |
| `delete_item(item_id)` | `None` | リソース削除 |

### 実験操作

| メソッド | 戻り値 | 説明 |
|---|---|---|
| `list_experiments()` | `list[dict]` | 全実験取得 |
| `get_experiment(exp_id: int)` | `dict` | 実験取得 |
| `create_experiment(title="", body="")` | `int` | 実験作成、ID を返す |
| `update_experiment(exp_id, **fields)` | `None` | 実験更新 |
| `delete_experiment(exp_id)` | `None` | 実験削除 |
| `search_experiments(tags: list[str])` | `list[dict]` | タグで実験検索 |
| `append_body(exp_id, text)` | `None` | body に追記 |
| `replace_body(exp_id, body)` | `None` | body を置換 |

### ファイル・タグ・メタデータ

| メソッド | 戻り値 | 説明 |
|---|---|---|
| `upload_file(entity_type, entity_id, filepath, comment="")` | `dict` | ファイルアップロード。`{"id", "filename", "url"}` を返す |
| `get_tags(entity_type, entity_id)` | `list[dict]` | タグ一覧取得 |
| `add_tag(entity_type, entity_id, tag)` | `None` | タグ追加 |
| `remove_tag(entity_type, entity_id, tag_id)` | `None` | タグ削除（ID 指定） |
| `untag_by_name(entity_type, entity_id, tag_name)` | `bool` | タグ名指定でエンティティから解除。見つからない場合 False |
| `get_metadata(entity_type, entity_id)` | `dict` | メタデータを dict で取得。パース失敗時は空 dict |
| `get_metadata_raw(entity_type, entity_id)` | `str \| None` | メタデータの生の値を返す |
| `update_metadata(entity_type, entity_id, metadata)` | `None` | メタデータ更新 |

### 汎用エンティティ操作

| メソッド | 戻り値 | 説明 |
|---|---|---|
| `get_entity(entity_type, entity_id)` | `dict` | 汎用エンティティ取得 |
| `patch_entity(entity_type, entity_id, **fields)` | `None` | 汎用エンティティ更新 |

### 内部メソッド

| メソッド | 説明 |
|---|---|
| `_req(method, path, **kwargs)` | HTTP リクエスト実行。`raise_for_status()` で例外送出 |
| `_parse_id(resp)` | レスポンスからエンティティ ID を抽出（JSON `id` → `Location` ヘッダー） |

---

## sync.py

モジュールレベル関数とクラスの詳細は [同期エンジン](07_SYNC_ENGINE.md) を参照。

### ユーティリティ関数

| 関数 | 説明 |
|---|---|
| `_compute_hash(body: str) -> str` | SHA-256 先頭 16 文字を返す |
| `_count_local_images(body: str) -> int` | ローカル画像参照の数を返す |
| `_md_to_html(text: str) -> str` | Markdown → HTML 変換 |
| `_rewrite_images(body, entity, entity_id, client, docs_dir, project_root) -> str` | ローカル画像をアップロードし URL を書き換え |
| `_sync_tags(client, entity_type, entity_id, desired_tags)` | 設定のタグをリモートに追記（追記のみ、best-effort） |

### `ConflictError`

リモートが前回同期以降に変更されている場合に送出される例外。

---

## sync_log.py

| 関数 | 説明 |
|---|---|
| `record(log_path, *, action, target, entity, entity_id, files, user=None)` | ログエントリを JSONL に追記。例外を送出しない |
| `read_log(log_path, limit=20) -> list[dict]` | 直近 N 件のログを読み込み |
| `format_log(entries) -> str` | ログエントリを表示用文字列に整形 |

ログファイルパス: `.elab-sync-ids/sync-log.jsonl`

ログエントリの形式:

```json
{
  "timestamp": "2026-04-05T22:00:00+0900",
  "action": "push",
  "target": "My Docs",
  "entity": "items",
  "entity_id": 42,
  "files": ["doc1.md", "doc2.md"],
  "user": "taro@example.com"
}
```

---

## cli.py

CLI エントリポイント。`argparse` でコマンドを定義。

| 関数 | 説明 |
|---|---|
| `main()` | argparse パーサー構築・コマンドディスパッチ |
| `cmd_sync(args)` | push 同期の実行 |
| `cmd_status(args)` | 同期状態の表示 |
| `cmd_pull(args)` | eLabFTW → ローカルへの取得 |
| `cmd_diff(args)` | ローカルとリモートの差分表示 |
| `cmd_init(args)` | 対話的セットアップ |
| `cmd_clone(args)` | リモートからプロジェクト構築 |
| `cmd_log(args)` | 同期ログ表示 |
| `cmd_update(args)` | ツール更新 |
| `cmd_tag(args)` | タグ管理（list/add/remove） |
| `cmd_metadata(args)` | メタデータ管理（get/set） |
| `cmd_entity_status(args)` | ステータス管理（show/set） |
| `cmd_list(args)` | リモート一覧表示 |
| `cmd_link(args)` | 手動紐付け |
| `cmd_verify(args)` | 整合性チェック |
| `cmd_whoami(args)` | ユーザー情報表示 |
| `cmd_new(args)` | テンプレートからファイル生成 |
| `_make_syncer(client, target, project_root)` | モードに応じた Syncer インスタンスを生成 |
| `_get_entity_ids(client, syncer, target, args_id)` | ターゲットに紐づくエンティティ ID リストを返す |
| `_show_diff(title, local_text, remote_text)` | unified diff を表示 |
| `_template_dir()` | テンプレートディレクトリのパスを返す |
| `_copy_template_files(docs_dir)` | テンプレートファイルをコピー |

コマンドの使い方は [CLI リファレンス](05_CLI_REFERENCE.md) を参照。

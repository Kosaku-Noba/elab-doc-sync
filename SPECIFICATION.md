# elab-doc-sync 仕様書

## 1. 概要

elab-doc-sync は、ローカルの Markdown ドキュメントを eLabFTW の「リソース」に同期する CLI ツールである。YAML 設定ファイルに基づき、複数のドキュメントセット（ターゲット）をそれぞれ独立した eLabFTW リソースとして管理する。

## 2. システム構成

### 2.1 ツールリポジトリ

```
elab-doc-sync/
├── src/elab_doc_sync/
│   ├── __init__.py      # パブリック API エクスポート
│   ├── cli.py           # CLI エントリポイント (argparse)
│   ├── config.py        # YAML 設定読み込み・バリデーション
│   ├── client.py        # eLabFTW API v2 クライアント
│   └── sync.py          # 差分検知・同期ロジック
├── template/            # ユーザー配布用テンプレート
│   ├── sync.py          # ブートストラップスクリプト
│   ├── .gitignore
│   ├── docs/.gitkeep
│   └── README.md        # 研究者向けクイックスタート
├── pyproject.toml
└── SPECIFICATION.md
```

### 2.2 ユーザーのドキュメントリポジトリ（配布後）

```
my-docs-repo/
├── docs/                    # Markdown ドキュメント
├── .elab-sync.yaml          # 同期設定
├── .elab-sync-ids/          # 自動生成（.gitignore 対象）
├── .tool/                   # ツール自動 clone 先（.gitignore 対象）
│   └── elab-doc-sync/
├── sync.py                  # ブートストラップスクリプト
├── .gitignore
└── README.md
```

### 2.3 依存ライブラリ

| ライブラリ | バージョン | 用途 |
|-----------|-----------|------|
| requests | >=2.28 | HTTP 通信 |
| markdown | >=3.4 | Markdown → HTML 変換 |
| pyyaml | >=6.0 | YAML 設定ファイル読み込み |
| urllib3 | >=2.0 | SSL 警告制御 |

## 3. ブートストラップスクリプト (`template/sync.py`)

### 3.1 目的

ユーザーが `python sync.py` だけで全操作を行えるようにする。ツールの取得・インストールを自動化する。

### 3.2 動作フロー

1. `.tool/elab-doc-sync` が存在しなければ `git clone TOOL_REPO` で取得
2. `elab-doc-sync` コマンドが PATH にあるか確認
3. なければインストール: `uv sync` でインストール
4. `sys.argv[1:]` をそのまま `elab-doc-sync` コマンドに転送

### 3.3 設定

| 定数 | 説明 |
|------|------|
| `TOOL_REPO` | ツールリポジトリの Git URL。配布時に社内 URL に変更する |
| `TOOL_DIR` | ツールの clone 先。デフォルト: `.tool/elab-doc-sync` |

### 3.4 エラーメッセージ（日本語）

| 状況 | メッセージ |
|------|-----------|
| git 未インストール | `git が見つかりません。Git をインストールしてください。` |
| コマンド実行失敗 | `コマンドが失敗しました: <command>` |

## 4. 設定ファイル仕様 (`.elab-sync.yaml`)

### 4.1 スキーマ

```yaml
elabftw:
  url: <string>          # 必須。eLabFTW インスタンスの URL
  verify_ssl: <bool>     # 任意。デフォルト: true

targets:                  # 必須。1 件以上
  - title: <string>      # 必須。eLabFTW リソースのタイトル
    docs_dir: <string>   # 必須。Markdown ファイルのディレクトリ
    pattern: <string>    # 任意。Glob パターン。デフォルト: "*.md"
    id_file: <string>    # 任意。リソース ID 保存先。デフォルト: ".elab-sync-ids/default.id"
```

### 4.2 バリデーションルール

| 条件 | エラーメッセージ |
|------|----------------|
| 設定ファイル不在 | `設定ファイルが見つかりません: {path}` → `elab-doc-sync init で作成できます` |
| `elabftw.url` 未設定 | `eLabFTW の URL が設定されていません` → `.elab-sync.yaml の elabftw.url を確認してください` |
| `ELABFTW_API_KEY` 未設定 | `API キーが設定されていません` → `環境変数を設定してください: export ELABFTW_API_KEY="your_key"` |
| `targets` 空 | `同期ターゲットが定義されていません` → `.elab-sync.yaml の targets を確認してください` |

## 5. CLI 仕様

### 5.1 コマンド体系

```
elab-doc-sync [OPTIONS]           # 同期実行（デフォルト）
elab-doc-sync init [OPTIONS]      # 対話的セットアップ
elab-doc-sync status [OPTIONS]    # 同期状態の確認
```

### 5.2 オプション

| オプション | 短縮形 | 型 | デフォルト | 説明 |
|-----------|--------|-----|-----------|------|
| `--config` | `-c` | string | `.elab-sync.yaml` | 設定ファイルのパス |
| `--target` | `-t` | string | なし（全ターゲット） | 同期対象のターゲット名 |
| `--force` | `-f` | flag | false | 差分がなくても強制同期 |
| `--dry-run` | `-n` | flag | false | 実行せずに同期内容を確認 |

### 5.3 `init` コマンド

対話的に `.elab-sync.yaml` を生成する。

入力項目:

| 項目 | 必須 | デフォルト |
|------|------|-----------|
| eLabFTW の URL | ✅ | — |
| SSL 証明書検証 | — | yes |
| ドキュメントディレクトリ | — | `docs/` |
| ファイルパターン | — | `*.md` |
| リソースタイトル | ✅ | — |

完了後の処理:
- `.elab-sync.yaml` を生成
- `.gitignore` に `.tool/` と `.elab-sync-ids/` を追記
- `docs/` ディレクトリを作成（未存在時）
- API キー設定方法を案内（Linux / Windows 両方）

### 5.4 `--dry-run` オプション

同期を実行せずに、各ターゲットの要約を表示する。

出力例:
```
[My Project Docs] 変更あり
  ファイル: 3件  画像: 2件  → リソース #42 を更新します
[API Reference] 変更なし（スキップ）
  ファイル: 1件  画像: 0件  → リソース #43 を更新します
```

新規作成の場合:
```
[New Docs] 変更あり
  ファイル: 2件  画像: 1件  → 新しいリソース を更新します
```

## 6. モジュール仕様

### 6.1 `ELabFTWClient`

eLabFTW API v2 の HTTP クライアント。

#### コンストラクタ

```python
ELabFTWClient(base_url: str, api_key: str, verify_ssl: bool = True)
```

#### メソッド一覧

| メソッド | 戻り値 | 説明 |
|---------|--------|------|
| `list_items()` | `list[dict]` | 全リソース取得 |
| `get_item(item_id)` | `dict` | リソース取得 |
| `create_item(title, body)` | `int` | リソース作成。ID を返す |
| `update_item(item_id, **fields)` | `None` | リソース更新（PATCH） |
| `delete_item(item_id)` | `None` | リソース削除 |
| `list_experiments()` | `list[dict]` | 全実験取得 |
| `get_experiment(exp_id)` | `dict` | 実験取得 |
| `create_experiment(title, body)` | `int` | 実験作成。ID を返す |
| `update_experiment(exp_id, **fields)` | `None` | 実験更新 |
| `delete_experiment(exp_id)` | `None` | 実験削除 |
| `search_experiments(tags)` | `list[dict]` | タグで実験検索 |
| `append_body(exp_id, text)` | `None` | 実験の body に追記 |
| `replace_body(exp_id, body)` | `None` | 実験の body を置換 |
| `upload_file(entity_type, entity_id, filepath, comment)` | `dict` | ファイルアップロード |
| `add_tag(entity_type, entity_id, tag)` | `None` | タグ追加 |
| `remove_tag(entity_type, entity_id, tag_id)` | `None` | タグ削除（ID 指定） |
| `update_metadata(entity_type, entity_id, metadata)` | `None` | メタデータ更新 |
| `get_tags(entity_type, entity_id)` | `list[dict]` | タグ一覧取得 |
| `untag_by_name(entity_type, entity_id, tag_name)` | `bool` | タグ名指定で解除 |
| `get_metadata(entity_type, entity_id)` | `dict` | メタデータ取得（パース失敗時は空 dict） |
| `get_metadata_raw(entity_type, entity_id)` | `str \| None` | メタデータの生の値 |
| `get_entity(entity_type, entity_id)` | `dict` | 汎用エンティティ取得 |
| `patch_entity(entity_type, entity_id, **fields)` | `None` | 汎用エンティティ更新 |

#### エラーハンドリング

- HTTP エラーは `requests.HTTPError` として送出（`raise_for_status()`）
- タイムアウト: 通常 30 秒、ファイルアップロード 60 秒

### 6.2 `DocsSyncer`

差分検知付きドキュメント同期エンジン。

#### コンストラクタ

```python
DocsSyncer(client: ELabFTWClient, target: TargetConfig, project_root: Path)
```

#### メソッド一覧

| メソッド | 戻り値 | 説明 |
|---------|--------|------|
| `collect_docs()` | `str` | docs_dir から Markdown を収集し結合 |
| `collect_files()` | `list[Path]` | docs_dir からファイル一覧を取得 |
| `compute_hash(body)` | `str` | SHA-256 ハッシュ（先頭16文字） |
| `has_changed(body)` | `bool` | 保存済みハッシュとの差分判定 |
| `save_hash(body)` | `None` | ハッシュをファイルに保存 |
| `read_item_id()` | `int \| None` | 保存済みリソース ID の読み込み |
| `save_item_id(item_id)` | `None` | リソース ID をファイルに保存 |
| `count_local_images(body)` | `int` | ローカル画像参照の数を返す |
| `rewrite_images(body, item_id)` | `str` | ローカル画像をアップロードし URL を書き換え |
| `md_to_html(text)` | `str` | Markdown → HTML 変換（静的メソッド） |
| `dry_run()` | `dict` | 同期せずに要約情報を返す |
| `sync(force=False)` | `bool` | 同期実行。更新した場合 True |

#### `dry_run()` の戻り値

```python
{"files": int, "images": int, "changed": bool, "item_id": int | None}
```

#### 画像書き換えルール

- 正規表現 `!\[([^\]]*)\]\(([^)]+)\)` でローカル画像参照を検出
- `http://` / `https://` で始まる URL はスキップ
- 画像パスの解決順: `docs_dir` 相対 → `project_root` 相対
- アップロード成功時、URL を eLabFTW のダウンロード URL に置換
- 画像が見つからない場合、警告を出力し元の参照を維持

#### Markdown 変換

使用する markdown 拡張:

| 拡張 | 機能 |
|------|------|
| `tables` | テーブル記法 |
| `fenced_code` | フェンスドコードブロック |
| `codehilite` | コードハイライト |
| `toc` | 目次生成 |
| `nl2br` | 改行保持 |

### 6.3 `Config` / `TargetConfig`

```python
@dataclass
class TargetConfig:
    title: str
    docs_dir: str
    id_file: str
    pattern: str = "*.md"
    mode: str = "merge"   # "merge" / "each"
    entity: str = "items" # "items" / "experiments"
    tags: list[str] = []  # push 時に自動追加するタグ

@dataclass
class Config:
    url: str
    api_key: str
    verify_ssl: bool
    targets: list[TargetConfig]
```

### 6.4 `load_config(config_path: Path) -> Config`

YAML ファイルを読み込み `Config` を返す。バリデーション失敗時は日本語エラーメッセージを表示し `sys.exit(1)`。

## 7. ファイル管理

### 7.1 ID ファイル (`*.id`)

- 1行のみ。eLabFTW リソース ID（整数）を格納
- 初回同期時に自動作成
- ディレクトリが存在しない場合は自動作成

### 7.2 ハッシュファイル (`*.hash`)

- ID ファイルと同じディレクトリに、拡張子 `.hash` で保存
- SHA-256 の先頭 16 文字を格納
- 同期成功時に更新（raw Markdown のハッシュ。画像 URL 書き換え前の状態）

## 8. セキュリティ考慮事項

- API キーは環境変数 `ELABFTW_API_KEY` から取得（設定ファイルには含めない）
- `verify_ssl: false` 設定時、urllib3 の InsecureRequestWarning を抑制
- `.elab-sync-ids/` を `.gitignore` に追加することを推奨（ID・ハッシュの漏洩防止）
- `.tool/` を `.gitignore` に追加することを推奨（ツールコードの混入防止）

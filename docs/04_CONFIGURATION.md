# 設定ファイル仕様

→ [セットアップ](03_SETUP_GUIDE.md) | [CLI リファレンス](05_CLI_REFERENCE.md)

## ファイル: `.elab-sync.yaml`

### 全体スキーマ

```yaml
# 方法1: 従来形式（1サーバー）
elabftw:
  url: "https://your-elabftw.example.com"
  api_key: "your_key"        # 環境変数 ELABFTW_API_KEY が優先
  verify_ssl: true

# 方法2: profiles（複数サーバー/チーム）
profiles:
  default:
    url: "https://elab.example.com"
    api_key: "key-a"
    verify_ssl: true
  team-b:
    url: "https://elab.example.com"
    api_key: "key-b"
    verify_ssl: true

targets:
  - title: "プロジェクトドキュメント"
    docs_dir: "docs/"
    pattern: "*.md"
    mode: merge
    entity: items
    profile: default
    tags: ['プロジェクト']
    category: "ドキュメント"
    title_pattern: "*ドキュメント*"
    body_format: html
    attachments_dir: "attachments/"
    attachments_pattern: "*.pdf"
```

### 接続設定

`elabftw` セクションと `profiles` セクションは併用可能。`elabftw` セクションは暗黙の `default` プロファイルとして扱われる。

環境変数 `ELABFTW_API_KEY` は default プロファイルの `api_key` を上書きする。

### 設定キー一覧

| キー | 必須 | デフォルト | 説明 |
|---|---|---|---|
| `elabftw.url` | ✅ | — | eLabFTW インスタンスの URL |
| `elabftw.api_key` | ✅ | — | API キー（環境変数 `ELABFTW_API_KEY` が優先） |
| `elabftw.verify_ssl` | — | `true` | SSL 証明書検証 |
| `profiles.<name>.url` | ✅ | — | プロファイルの eLabFTW URL |
| `profiles.<name>.api_key` | ✅ | — | プロファイルの API キー |
| `profiles.<name>.verify_ssl` | — | `true` | SSL 証明書検証 |

### ターゲット設定キー一覧

| キー | 必須 | デフォルト | 説明 |
|---|---|---|---|
| `docs_dir` | ✅ | — | Markdown ファイルのディレクトリ |
| `title` | merge 時 ✅ | — | エンティティのタイトル |
| `pattern` | — | `*.md` | Glob パターン |
| `mode` | — | `merge` | `merge` / `each` |
| `entity` | — | `items` | `items`(`resources`) / `experiments` |
| `profile` | — | `default` | 使用する接続プロファイル名 |
| `tags` | — | `[]` | push 時に自動追加するタグ（追記のみ、pull 振り分けにも使用） |
| `category` | — | — | push 時のカテゴリ（ID or 名前、pull 振り分けにも使用） |
| `title_pattern` | — | — | pull 振り分け用タイトル glob |
| `body_format` | — | `html` | `md`（Markdown のまま送信）/ `html`（HTML 変換して送信） |
| `attachments_dir` | — | — | 添付ファイルディレクトリ |
| `attachments_pattern` | — | `*` | 添付ファイル glob フィルタ |
| `id_file` | — | `.elab-sync-ids/default.id` | ID 保存先パス |

### 同期モード

**merge（デフォルト）** — 複数の md を結合して 1 エンティティに送信:

```yaml
targets:
  - title: "プロジェクトドキュメント"
    docs_dir: "docs/"
```

**each** — 各 md を個別のエンティティとして送信:

```yaml
targets:
  - docs_dir: "experiments/"
    mode: each
    entity: experiments
```

**組み合わせ（プロファイル使用）:**

```yaml
targets:
  - title: "プロジェクト概要"
    docs_dir: "docs/"
    mode: merge
    entity: items
    profile: default

  - docs_dir: "shared_docs/"
    mode: each
    entity: items
    profile: team-b
    tags: ['共同研究']
```

### body_format

| 値 | 動作 |
|---|---|
| `html`（デフォルト） | Markdown → HTML 変換して送信。eLabFTW 上でリッチ表示。 |
| `md` | Markdown のまま送信。eLabFTW の MathJax でレンダリング。数式利用時に推奨。 |

### バリデーションルール

| 条件 | エラーメッセージ |
|---|---|
| 設定ファイル不在 | `設定ファイルが見つかりません` → `elab-doc-sync init で作成できます` |
| `elabftw.url` 未設定 | `eLabFTW の URL が設定されていません` |
| API キー未設定 | `API キーが設定されていません` |
| `targets` 空 | `同期ターゲットが定義されていません` |
| `body_format` 不正 | `body_format は 'md' または 'html' を指定してください` |

バリデーション処理は `config.py` の `load_config()` で実行される。詳細は [API リファレンス](06_API_REFERENCE.md) を参照。

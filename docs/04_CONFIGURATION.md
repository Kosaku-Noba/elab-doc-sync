# 設定ファイル仕様

→ [セットアップ](03_SETUP_GUIDE.md) | [CLI リファレンス](05_CLI_REFERENCE.md)

## ファイル: `.elab-sync.yaml`

### 全体スキーマ

```yaml
elabftw:
  url: "https://your-elabftw.example.com"
  api_key: "your_key"        # 環境変数 ELABFTW_API_KEY が優先
  verify_ssl: true

targets:
  - title: "プロジェクトドキュメント"
    docs_dir: "docs/"
    pattern: "*.md"
    mode: merge
    entity: items
    id_file: ".elab-sync-ids/default.id"
```

### 設定キー一覧

| キー | 必須 | デフォルト | 説明 |
|---|---|---|---|
| `elabftw.url` | ✅ | — | eLabFTW インスタンスの URL |
| `elabftw.api_key` | ✅ | — | API キー（環境変数 `ELABFTW_API_KEY` が優先） |
| `elabftw.verify_ssl` | — | `true` | SSL 証明書検証 |
| `targets[].title` | merge 時 ✅ | — | エンティティのタイトル |
| `targets[].docs_dir` | ✅ | — | Markdown ファイルのディレクトリ |
| `targets[].pattern` | — | `*.md` | Glob パターン |
| `targets[].mode` | — | `merge` | `merge` / `each` |
| `targets[].entity` | — | `items` | `items`(`resources`) / `experiments` |
| `targets[].id_file` | — | `.elab-sync-ids/default.id` | ID 保存先パス |
| `targets[].tags` | — | `[]` | push 時に自動追加するタグ（追記のみ、既存タグは外さない） |

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

**組み合わせ:**

```yaml
targets:
  - title: "プロジェクト概要"
    docs_dir: "docs/"
    mode: merge
    entity: items

  - docs_dir: "experiments/"
    mode: each
    entity: experiments
```

### バリデーションルール

| 条件 | エラーメッセージ |
|---|---|
| 設定ファイル不在 | `設定ファイルが見つかりません` → `elab-doc-sync init で作成できます` |
| `elabftw.url` 未設定 | `eLabFTW の URL が設定されていません` |
| API キー未設定 | `API キーが設定されていません` |
| `targets` 空 | `同期ターゲットが定義されていません` |

バリデーション処理は `config.py` の `load_config()` で実行される。詳細は [API リファレンス](06_API_REFERENCE.md) を参照。

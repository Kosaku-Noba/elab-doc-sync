# 設定ファイル仕様

→ [セットアップ](03_SETUP_GUIDE.md) | [CLI リファレンス](05_CLI_REFERENCE.md)

## ファイル: `.elab-sync.yaml`

プロジェクトルートに配置する。`esync init` で対話的に生成可能。

## 接続設定

### 方法1: 単一サーバー（従来形式）

```yaml
elabftw:
  url: "https://elab.example.com"
  api_key: "your_key"
  verify_ssl: true
```

### 方法2: 複数サーバー/チーム（profiles）

```yaml
profiles:
  default:
    url: "https://elab.example.com"
    api_key: "key-a"
    verify_ssl: true
    team: "TeamA"
  team-b:
    url: "https://elab.example.com"
    api_key: "key-b"
    verify_ssl: true
    team: "TeamB"
```

環境変数 `ELABFTW_API_KEY` は default プロファイルの api_key を上書きする。

## ターゲット設定

```yaml
targets:
  - docs_dir: "docs/"
    pattern: "*.md"
    entity: items
    body_format: html
    tags: ['Aptamer', 'AWS']
    category: "プロトコル"
    title_pattern: "*プロトコル*"
    profile: default
    attachments_dir: "attachments/"
    attachments_pattern: "*"
```

### キー一覧

| キー | 必須 | デフォルト | 説明 |
|---|---|---|---|
| `docs_dir` | ✅ | — | Markdown ファイルディレクトリ |
| `pattern` | — | `*.md` | Glob パターン |
| `entity` | — | `items` | `items` / `experiments` |
| `profile` | — | `default` | 使用する接続プロファイル |
| `tags` | — | `[]` | push 時に自動追加するタグ（pull 振り分けにも使用） |
| `category` | — | — | push 時のカテゴリ（pull 振り分けにも使用） |
| `links` | — | — | push 時に追加するリンク。キーは `experiments` / `items`（`resources` は `items` と同じ）、値は正の整数 ID のリスト。追加のみで削除はしない |
| `title_pattern` | — | — | pull 振り分け用タイトル glob |
| `body_format` | — | `html` | `md` / `html` |
| `attachments_dir` | — | — | 添付ファイルディレクトリ |
| `attachments_pattern` | — | `*` | 添付ファイル glob フィルタ |
| `id_file` | — | `.elab-sync-ids/{docs_dir}/default.id` | 状態ファイルのパス |

### links（実験ノート・リソースへのリンク）

```yaml
targets:
  - docs_dir: "experiments/"
    entity: experiments
    links:
      items: [42, 43]      # リソース
      experiments: [12]    # 実験ノート
```

push 時に、ターゲットの全文書から指定した記事へのリンクのうち、まだないものを追加します。既存のリンク（eLabFTW の画面で張ったものを含む）は削除せず、設定から ID を外してもリンクは外しません。文書自身へのリンクは張りません。

張り終えたリンクは文書ごとの同期状態（`state.json` の `links`）に記録します。設定に未記録の ID がある文書は「送信待ち」になり、次の push でリンクだけを追加します（失敗後の再試行を含め、タグ・カテゴリは再適用しません）。pull・`esync link` はリンクを張らず、新しく取得・紐付けした文書は次の push で追加します。張り終えた後に外したリンクは通常の push では張り直さないため、`esync relate add` を使います（`push --force` も張り直しますが、本文の強制送信とタグ・カテゴリの再適用も行います）。

### 同期モードとターゲット名

`mode` は省略または `each` のみ有効です。`merge` は移行案内を表示して停止します。`title` は `--target` で指定するターゲット名として利用できます。記事タイトルはMarkdownのファイル名から決まります。`title` を省略した場合は `docs_dir` でターゲットを指定できます。

バックアップ対象の `docs_dir`・`attachments_dir`・状態ディレクトリはプロジェクト内に配置し、シンボリックリンクを使わないでください。別サーバーや別ターゲットには独立した状態ディレクトリを指定してください。

## id_file のデフォルトパス

ターゲットごとに独立した状態ディレクトリを持つ:

```
.elab-sync-ids/{docs_dir_name}/default.id
```

例:
- `docs_dir: "elab_docs"` → `.elab-sync-ids/elab_docs/default.id`
- `docs_dir: "weekly/"` → `.elab-sync-ids/weekly/default.id`

明示的に `id_file` を指定することで任意のパスに変更可能。

## 複数ターゲット例

```yaml
targets:
  - docs_dir: "weekly_reports/"
    entity: items
    tags: ['週報']
    title_pattern: "*週報*"

  - docs_dir: "experiments/"
    entity: experiments
    tags: ['実験']

  - docs_dir: "shared_docs/"
    profile: team-b
    tags: ['共同研究']
```

push 時は各 `docs_dir` から送信され、pull 時はタグやタイトルから適切なディレクトリに自動配置される。

## 環境変数

| 変数名 | 説明 |
|---|---|
| `ELABFTW_API_KEY` | default プロファイルの api_key を上書き |

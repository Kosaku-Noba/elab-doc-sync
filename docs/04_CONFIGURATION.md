# 設定ファイル仕様

→ [セットアップ](03_SETUP_GUIDE.md) | [CLI リファレンス](05_CLI_REFERENCE.md)

## ファイル: `.elab-sync.yaml`

プロジェクトルートに配置する。`esync init` で対話的に生成可能。UTF-8 で読み込み、読めない場合は cp932 で読み込む。記入例はリポジトリの [`.elab-sync.yaml.example`](../.elab-sync.yaml.example) を参照。

## 接続設定

### 方法1: 単一サーバー（従来形式）

```yaml
elabftw:
  url: "https://elab.example.com"
  api_key: "your_key"
  verify_ssl: true
```

`elabftw` セクションは暗黙の `default` プロファイルとして扱われる（`profiles` に `default` がある場合はそちらが優先）。

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

| キー | 必須 | デフォルト | 説明 |
|---|---|---|---|
| `url` | ✅ | — | eLabFTW の URL |
| `api_key` | ✅ | — | API キー（`default` は環境変数で上書き可） |
| `verify_ssl` | — | `true` | SSL 証明書を検証するか |
| `team` | — | — | このキーが紐づくチーム名または ID。ターゲットの `team` からプロファイルを選ぶのに使う |

環境変数 `ELABFTW_API_KEY` は default プロファイルの api_key を上書きする。`profiles` に `default` がなく `elabftw` セクションもない場合は、最初のプロファイルを既定の接続先として使う。プロファイルは `esync profile list/add/remove` でも編集できる。

## ターゲット設定

```yaml
targets:
  - title: "プロトコル"
    docs_dir: "docs/"
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
| `title` | — | 空文字 | `--target` / `-t` で指定するターゲット名。記事タイトルは「記事タイトルの決まり方」を参照 |
| `pattern` | — | `*.md` | Glob パターン |
| `mode` | — | `each` | `each` のみ有効（`merge` はエラー） |
| `entity` | — | `items` | `items` / `experiments`（`resources` は `items` と同じ） |
| `profile` | — | `default` | 使用する接続プロファイル |
| `team` | — | — | 送信先チーム名または ID。`profile` を省略した場合、同じ `team` を持つプロファイルを自動選択する |
| `tags` | — | `[]` | push 時に自動追加するタグ（pull 振り分けにも使用） |
| `category` | — | — | push 時のカテゴリ。名前または数字の ID（pull 振り分けにも使用）。一覧 API に出ない（読み取り権限のない）カテゴリは ID で指定 |
| `links` | — | — | push 時に追加するリンク。キーは `experiments` / `items`（`resources` は `items` と同じ）、値は正の整数 ID のリスト。追加のみで削除はしない |
| `title_map` | — | `{}` | ローカルファイル名 → eLabFTW タイトルの別名。値は非空文字列。「記事タイトルの決まり方」を参照 |
| `title_pattern` | — | — | pull 振り分け用タイトル glob |
| `body_format` | — | `html` | `md` / `html`（`esync init` で作る場合の既定は `md`） |
| `attachments_dir` | — | — | 添付ファイルディレクトリ |
| `attachments_pattern` | — | `*` | 添付ファイル glob フィルタ |
| `id_file` | — | `.elab-sync-ids/{docs_dir_name}/default.id` | 状態ディレクトリの指定（このパスの親ディレクトリを使う） |

### 接続先の選び方

1. `profile` が `default` 以外なら、そのプロファイルを使う（存在しなければエラー）
2. `team` があれば、同じ `team` を持つプロファイルを使う（チーム名は大文字小文字を区別せず、数字は ID として比較）。見つからなければ警告を出して次へ
3. `profile`（既定 `default`）のプロファイル、なければ既定の接続先

push・pull・`tag`・`relate`・`metadata`・`entity-status`・`verify` はターゲットごとにこの接続先で送信する。`category`・`list`・`new` は `-t` で選んだターゲットの接続先（`-t` 省略時は既定の接続先）を使う。

### 記事タイトルの決まり方

eLabFTW の記事タイトルは、ローカル Markdown ごとに次の優先順位で決まります。

1. **front matter の `title`**: 先頭の YAML front matter に `title: 任意のタイトル` があればその値。
2. **本文先頭のタイトルマーカー見出し**: 本文の先頭の非空行が `# title: 任意のタイトル` 形式（ATX レベル 1、`title:` は大文字小文字を区別しない）のときその値。
3. **`title_map`**: ターゲットの `title_map` にファイル名が登録されていればその値。
4. **ファイル名**: 上記のいずれもなければ、拡張子を除いたファイル名（従来の振る舞い）。

> ※ 通常の見出し（`# 見出し`）はタイトルにはなりません。既存ノートの見出しが意図せずタイトルにならないよう、`# title:` マーカー付きのときだけ採用します。

```yaml
targets:
  - docs_dir: "docs/"
    title_map:
      report01.md: "2026年度 第1四半期レポート"
      memo.md: "設計メモ"
```

リネーム検出・競合ガード・pull の各経路でもこの決定タイトルが一貫して使われます。別名を指定しないファイルは従来どおりファイル名がタイトルになります。

### category

名前を指定した場合は、push の前にターゲットごとに 1 回だけ ID に解決する。解決できないときは、カテゴリの設定が必要な文書（新規作成、前回から設定・タイトル・本文形式が変わった文書、`--force`、同期再開）だけを eLabFTW を変更せずにスキップし、数字の ID で指定する方法を案内する。本文だけの変更は通常どおり送信する。

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

リンクの追加に失敗すると、失敗したリンク先と原因（`HTTP 404（見つかりません）` など）を表示し、その文書は失敗として扱います（残りのリンクの追加は続けます）。本文・タグ・カテゴリは送信済みの場合があります。リンク先の ID と権限を確認し、もう一度 push すると不足分だけ追加します。

`links` のキーが不正、値が正の整数でない場合は設定エラーになります。

### 同期モードとターゲット名

`mode` は省略または `each` のみ有効です。`merge` を指定すると移行案内を表示して停止します（終了コード 2、[移行手順](13_MIGRATION_V1.md#mergeを使っていた場合)）。`title` は `--target` で指定するターゲット名として利用できます。記事タイトルは front matter / 本文先頭の `# title: ...` / `title_map` / ファイル名の優先順で決まります（「記事タイトルの決まり方」を参照）。`title` を省略した場合は `docs_dir` でターゲットを指定できます。

バックアップ対象の `docs_dir`・`attachments_dir`・状態ディレクトリはプロジェクト内に配置し、シンボリックリンクを使わないでください。別サーバーや別ターゲットには独立した状態ディレクトリを指定してください。

## id_file のデフォルトパス

ターゲットごとに独立した状態ディレクトリを持つ:

```
.elab-sync-ids/{docs_dir_name}/default.id
```

`docs_dir_name` は `docs_dir` の末尾の `/` を除き、途中の `/`・`\` を `_` に置き換えた名前です。状態ファイルは `id_file` の親ディレクトリに置かれ、`default.id` ファイル自体は作成されません。

例:
- `docs_dir: "elab_docs"` → `.elab-sync-ids/elab_docs/default.id`
- `docs_dir: "weekly/"` → `.elab-sync-ids/weekly/default.id`
- `docs_dir: "notes/weekly/"` → `.elab-sync-ids/notes_weekly/default.id`

明示的に `id_file` を指定することで任意のパスに変更可能。

## 複数ターゲット例

```yaml
targets:
  - title: "週報"
    docs_dir: "weekly_reports/"
    entity: items
    tags: ['週報']
    title_pattern: "*週報*"

  - title: "実験メモ"
    docs_dir: "experiments/"
    entity: experiments
    tags: ['実験']
    links:
      items: [42]

  - docs_dir: "shared_docs/"
    profile: team-b
    tags: ['共同研究']
```

push 時は各 `docs_dir` から送信され、pull 時はタグやタイトルから適切なディレクトリに自動配置される（[pull 自動振り分け](12_DESIGN_DECISIONS.md#4-fr-23-pull-自動振り分け)）。

## 環境変数

| 変数名 | 説明 |
|---|---|
| `ELABFTW_API_KEY` | default プロファイル（`elabftw` セクション）の api_key を上書き。`esync clone` でも使用 |
| `ELABFTW_TEST_CONFIG` | 実機接続テストの設定ファイル（テスト専用、[テスト仕様](11_TEST_SPEC.md)） |

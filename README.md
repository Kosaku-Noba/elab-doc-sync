# elab-doc-sync

Markdown ドキュメントを eLabFTW に同期する CLI ツール。`esync` エイリアスでも使えます。

## これは何？

ローカルの Markdown ファイルを eLabFTW のリソースや実験ノートとして管理するツールです。普段使い慣れたエディタで書いて、コマンド一発で eLabFTW に反映できます。

---

## まず使えるようにする（初回セットアップ）

### 必要なもの

- Python 3.10 以上
- [uv](https://docs.astral.sh/uv/)

### インストール

```bash
uv tool install --force git+https://github.com/Kosaku-Noba/elab-doc-sync.git
```

### 初期設定（質問に答えるだけ）

```bash
esync init
```

URL、同期モード、送信先を聞かれるので順に答えると `.elab-sync.yaml` が生成されます。

### API キーを設定する

eLabFTW → ユーザー設定 → API Keys でキーを作成し、`.elab-sync.yaml` に貼る:

```yaml
elabftw:
  url: "https://your-elabftw.example.com"
  api_key: "ここにキーを貼る"
  verify_ssl: true
```

あるいは環境変数でもOK:

```bash
export ELABFTW_API_KEY="your_key"
```

---

## 日常の使い方

### 書いたものを eLabFTW に送る（push）

```bash
esync
```

変更があるファイルだけ自動で送信されます。変更がなければスキップ:

```bash
$ esync
  [実験メモ] 変更なし（スキップ）
```

### 送信前に確認だけしたい

```bash
esync --dry-run
```

### eLabFTW から最新を取得する（pull）

既に同期済みのファイルを再取得:

```bash
esync pull
```

新しいエンティティを取得:

```bash
esync pull --id 42 --entity items
```

複数まとめて:

```bash
esync pull --id 42 --id 43 --id 44 --entity items
```

pull 時、ローカルのどのディレクトリに保存するかは **タグ・カテゴリ・タイトル** から自動判定されます。判定できない場合は対話で聞かれます。

### ローカルと eLabFTW の差分を見る

```bash
esync diff
```

---

## 応用: こういう場面ではこうする

### eLabFTW にある既存プロジェクトをローカルに持ってきたい

```bash
export ELABFTW_API_KEY="your_key"
esync clone --url https://elab.example.com --entity items --id 42
```

プロジェクトディレクトリ一式が生成されます。

### 週報と実験メモを別ディレクトリで管理したい

`.elab-sync.yaml` でターゲットを分ける:

```yaml
targets:
  - docs_dir: "weekly_reports/"
    mode: each
    entity: items
    tags: ['週報']
    title_pattern: "*週報*"    # pull 時のタイトル自動振り分け

  - docs_dir: "experiments/"
    mode: each
    entity: experiments
```

push 時は各 `docs_dir` から送信され、pull 時はタグやタイトルから適切なディレクトリに自動配置されます。

### 別チームの eLabFTW にも投稿したい（複数 API キー）

プロファイルを追加:

```bash
esync profile add team-b --url https://elab.example.com --api-key "team-b-key"
```

ターゲットごとにプロファイルを指定:

```yaml
targets:
  - docs_dir: "my_docs/"
    profile: default

  - docs_dir: "shared_docs/"
    profile: team-b
    tags: ['共同研究']
```

プロファイル一覧の確認:

```bash
esync profile list
```

### タグやカテゴリを操作したい

```bash
# タグ一覧
esync tag list --id 42 --entity items

# タグ追加
esync tag add "new-tag" --id 42 --entity items

# カテゴリ設定
esync category set "試薬" --id 42 --entity items
```

### リモートに何があるか見たい

```bash
esync list                        # リソース一覧
esync list --entity experiments   # 実験ノート一覧
```

### ファイルを既存のエンティティに手動で紐付けたい

```bash
esync link 42 --file "実験メモ.md"
```

### PDF や CSV も一緒に送りたい（添付ファイル）

```yaml
targets:
  - docs_dir: "docs/"
    attachments_dir: "attachments/"
    entity: items
```

`attachments/` に置いたファイルが push 時に自動アップロードされます。

### 数式を使いたい

```yaml
targets:
  - docs_dir: "docs/"
    body_format: md    # ← Markdown のまま送信（MathJax でレンダリング）
```

```markdown
インライン: $E = mc^2$

ブロック:
$$\frac{\partial f}{\partial x} = 2x + 1$$
```

---

## pull の自動振り分け

`esync pull --id` で新しいエンティティを取得する際、以下の順で保存先を決定します:

1. **既に紐付け済み** → そのディレクトリへ再同期
2. **ターゲットが1つだけ** → そのターゲットの `docs_dir` へ
3. **複数ターゲット** → タグ/カテゴリ/タイトルでスコアリング
4. **判定できない** → 対話で選択 or `--auto` で最高スコアを採用

スコアリング:
- `title_pattern` (glob) マッチ: +10
- `category` 一致: +10
- `tags` の包含率: 最大 5 + 特異性ボーナス

判定を常に自動で行いたい場合:

```bash
esync pull --id 42 --entity items --auto
```

マッチするターゲットがない場合、リモートのメタデータから新しいターゲットが `.elab-sync.yaml` に自動追記されます。

---

## 同期モード

| モード | 動作 | 使いどころ |
|--------|------|-----------|
| `merge` | 複数 md を結合して 1 エンティティに送信 | プロジェクトドキュメントをまとめたい |
| `each` | 1 ファイル = 1 エンティティ | 実験ノートを個別に管理したい |

---

## コマンド一覧

| コマンド | やること |
|---------|---------|
| `esync` | push（ローカル → eLabFTW） |
| `esync pull` | pull（eLabFTW → ローカル） |
| `esync pull --id 42 --entity items` | 指定 ID を取得 |
| `esync diff` | 差分表示 |
| `esync status` | 同期状態を確認 |
| `esync list` | リモート一覧 |
| `esync clone` | プロジェクトを構築 |
| `esync tag list/add/remove` | タグ操作 |
| `esync category list/show/set` | カテゴリ操作 |
| `esync profile list/add/remove` | 接続プロファイル管理 |
| `esync link <ID>` | 手動紐付け |
| `esync verify` | 整合性チェック |
| `esync init` | 初期設定 |
| `esync update` | ツール更新 |
| `esync --dry-run` | 実行せず確認 |
| `esync --force` | 強制同期 |
| `esync -t "名前"` | 特定ターゲットだけ |

---

## 設定リファレンス

### 接続設定

```yaml
# 方法1: 従来形式（1サーバー）
elabftw:
  url: "https://elab.example.com"
  api_key: "your_key"
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
```

環境変数 `ELABFTW_API_KEY` は default プロファイルの api_key を上書きします。

### ターゲット設定

| キー | 必須 | デフォルト | 説明 |
|------|------|-----------|------|
| `docs_dir` | ✅ | — | Markdown ディレクトリ |
| `title` | merge時✅ | — | エンティティのタイトル |
| `pattern` | — | `*.md` | Glob パターン |
| `mode` | — | `merge` | `merge` / `each` |
| `entity` | — | `items` | `items` / `experiments` |
| `profile` | — | `default` | 使用する接続プロファイル |
| `tags` | — | `[]` | push 時に自動追加するタグ（pull 振り分けにも使用） |
| `category` | — | — | push 時のカテゴリ（pull 振り分けにも使用） |
| `title_pattern` | — | — | pull 振り分け用タイトル glob |
| `body_format` | — | `html` | `md` / `html` |
| `attachments_dir` | — | — | 添付ファイルディレクトリ |
| `attachments_pattern` | — | `*` | 添付ファイル glob フィルタ |

---

## トラブルシューティング

| メッセージ | やること |
|-----------|---------|
| `API キーが設定されていません` | `.elab-sync.yaml` の api_key を確認 |
| `設定ファイルが見つかりません` | `esync init` を実行 |
| `ファイルがありません` | `docs_dir` に `.md` ファイルを置く |
| タイムアウト | 自動で1回リトライされます |

---

## 開発

```bash
git clone https://github.com/Kosaku-Noba/elab-doc-sync.git
cd elab-doc-sync
uv sync --extra test
uv run pytest -q -m "not integration"
```

## ライセンス

MIT

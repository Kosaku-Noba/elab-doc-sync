# elab-doc-sync

Markdown ドキュメントを eLabFTW に同期する CLI ツール。`esync` エイリアスでも使えます。

## 特徴

- 差分検知（SHA-256）で変更があるファイルだけ更新
- 画像の自動アップロード・URL 書き換え
- 2つの同期モード: `merge`（全結合→1エンティティ）/ `each`（1ファイル=1エンティティ）
- リソース (`items`) と実験ノート (`experiments`) の両方に対応
- eLabFTW からのプル（pull）・差分表示（diff）に対応
- Windows / Linux 両対応

## 前提条件

- Python 3.10 以上
- [uv](https://docs.astral.sh/uv/) （パッケージ管理・実行に使用）

> **pip からの移行:** 以前 `pip install` でインストールしていた場合は、`pip uninstall elab-doc-sync` で削除してから下記の手順で再インストールしてください。設定ファイル（`.elab-sync.yaml`）はそのまま使えます。

## セットアップ（初回のみ）

### ① ツールをインストール

```bash
uv pip install git+https://github.com/Kosaku-Noba/elab-doc-sync.git
```

### ② 設定ファイルを作る（質問に答えるだけ）

```bash
uv run elab-doc-sync init

=== elab-doc-sync セットアップ ===

eLabFTW の URL: #elabFTWのURLを入力
SSL 証明書を検証しますか？ [Y/n]: n
Markdown ファイルを置くディレクトリ（空欄で docs/）: 
同期する Markdown のファイルパターン（空欄で *.md）: 
同期モード — merge: 全ファイルを1つに結合 / each: 1ファイル=1ノート [merge]: each
送信先 — items(resources): リソース / experiments: 実験ノート [items]: items

テンプレートファイルを展開中...
  .gitignore を作成しました
  README.md を作成しました
  docs/ ディレクトリを作成しました

✅ 設定ファイルを作成しました: .elab-sync.yaml
```

### ③ API キーを設定する

eLabFTW → ユーザー設定 → API Keys でキーを作成し、`.elab-sync.yaml` の `api_key` にキーを貼ってください:

```yaml
elabftw:
  url: "https://your-elabftw.example.com"
  api_key: "ここにキーを貼る"
  verify_ssl: true   # 自己署名証明書の場合のみ false に変更
```

## 基本的な使い方

### ローカル → eLabFTW に同期（push）

```bash
$ esync
  [プロジェクトドキュメント] 2 件のドキュメントを収集しました（1234 文字）
  [プロジェクトドキュメント] リソース #42 を更新しました

完了: 1 ターゲットを同期しました
```

変更がないファイルは自動でスキップされます:

```bash
$ esync
  [プロジェクトドキュメント] 変更なし（スキップ）
```

### eLabFTW → ローカルに取得（pull）

初回は `--id` と `--entity` を指定:

```bash
$ esync pull --id 42 --entity items
  [実験メモ] リソース #42 → docs/実験メモ.md
    画像をダウンロード: figure1.png

完了: 1 件取得しました
```

2回目以降は ID を覚えているのでそのまま:

```bash
$ esync pull
  [実験メモ] リソース #42 → docs/実験メモ.md

完了: 1 件取得しました
```

### 差分を確認（diff）

```bash
$ esync diff
--- eLabFTW: 実験メモ
+++ ローカル: 実験メモ
@@ -1,3 +1,3 @@
 # 実験メモ
-古い内容
+新しい内容
```

差分がなければ:

```bash
$ esync diff
  [実験メモ] 差分なし

すべて最新です
```

### 同期状態を確認（status）

```bash
$ esync status
  [プロジェクトドキュメント] 変更あり（2 ファイル, 画像 1 枚, ID: #42）
```

### 実行前に確認（dry-run）

```bash
$ esync --dry-run
  [プロジェクトドキュメント] 2 ファイル, 画像 1 枚, 変更あり → 同期対象
```

## よくある操作例

### 既存プロジェクトを eLabFTW から構築（clone）

```bash
$ export ELABFTW_API_KEY="your_key"
$ esync clone --url https://elab.example.com --entity items --id 42 --id 43

=== esync clone: https://elab.example.com ===

  .elab-sync.yaml を作成しました
  [実験メモ] リソース #42 → elab-clone-42/docs/実験メモ.md
  [結果まとめ] リソース #43 → elab-clone-42/docs/結果まとめ.md

✅ プロジェクトを作成しました: elab-clone-42/ (2 件)
```

> **Tip:** `clone` はリモートの添付ファイルも `attachments/` にダウンロードしますが、生成される `.elab-sync.yaml` には `attachments_dir` が含まれません。再 push で添付も同期したい場合は、設定ファイルに `attachments_dir: "attachments/"` を手動で追記してください。複数 ID を clone した場合、`mode: each` では同じ添付ディレクトリが各エンティティに適用されるため、添付一式が全エンティティへ複製されます。エンティティごとに異なる添付が必要な場合はターゲットと添付ディレクトリを分けてください。

### タグ操作

```bash
# タグ一覧を表示（同期済みターゲットから自動解決）
$ esync tag list
  リソース #42: biology, 2025-Q1

# ID とエンティティを直接指定して操作
$ esync tag list --id 42 --entity items
  リソース #42: biology, 2025-Q1

# タグを追加
$ esync tag add "new-tag" --id 42 --entity items
  リソース #42: タグ「new-tag」を追加しました

# タグを外す
$ esync tag remove "old-tag" --id 42 --entity items
  リソース #42: タグ「old-tag」を外しました

# 実験ノートのタグを操作
$ esync tag add "urgent" --id 1 --entity experiments
  実験ノート #1: タグ「urgent」を追加しました
```

### カテゴリ操作

```bash
# カテゴリ一覧を表示
$ esync category list
  #1  試薬
  #2  機器
  #3  プロトコル

# 実験ノートのカテゴリ一覧
$ esync category list --entity experiments

# 現在のカテゴリを表示
$ esync category show --id 42 --entity items
  リソース #42: 試薬 (#1)

# カテゴリを設定（名前で指定）
$ esync category set "試薬" --id 42 --entity items
  リソース #42: カテゴリを設定しました (#1)

# カテゴリを設定（ID で指定）
$ esync category set 1 --id 42 --entity items
  リソース #42: カテゴリを設定しました (#1)
```

YAML で `category` を設定すると push 時に自動適用されます:

```yaml
targets:
  - title: "試薬リスト"
    docs_dir: "docs/"
    entity: items
    category: "試薬"       # 名前または ID で指定
```

> **Note:** カテゴリは単一値で、push 時に上書きされます（タグの追記方式とは異なります）。本文に変更がない場合はスキップされるため、既存エンティティに後からカテゴリを設定する場合は `--force` または `esync category set` を使ってください。カテゴリ名は完全一致で解決されます。

### リモート一覧を表示

```bash
# リソース一覧
$ esync list
  #42  実験メモ
  #43  結果まとめ

# 実験ノート一覧
$ esync list --entity experiments
  #1  Day 1 実験記録
  #2  Day 2 実験記録
```

### 添付ファイルを同期する（v0.2.1〜）

PDF や CSV など画像以外のファイルも eLabFTW に自動アップロードできます。

#### ① 設定ファイルに `attachments_dir` を追加

```yaml
targets:
  - title: "実験レポート"
    docs_dir: "docs/"
    attachments_dir: "attachments/"   # ← このディレクトリ内のファイルを自動アップロード
    entity: items
```

#### ② ファイルを配置して push

```
project/
├── docs/
│   └── レポート.md
├── attachments/
│   ├── raw_data.csv
│   └── protocol.pdf
└── .elab-sync.yaml
```

```bash
$ esync
  [実験レポート] 2 件のドキュメントを収集しました（1234 文字）
  [実験レポート] 添付ファイルをアップロード: raw_data.csv
  [実験レポート] 添付ファイルをアップロード: protocol.pdf
  [実験レポート] リソース #42 を更新しました

完了: 1 ターゲットを同期しました
```

同名・同サイズのファイルは再アップロードされません。内容を差し替えた場合は `--force` で強制送信:

```bash
$ esync --force
```

#### ③ pull / clone で添付ファイルもダウンロード

```bash
$ esync pull --id 42 --entity items
  [実験レポート] リソース #42 → docs/レポート.md
    添付ファイルをダウンロード: raw_data.csv
    添付ファイルをダウンロード: protocol.pdf

完了: 1 件取得しました
```

dry-run でも添付ファイル件数が表示されます:

```bash
$ esync --dry-run
  [実験レポート] 2 ファイル, 添付 2 件, 変更あり → 同期対象
```

> **Note:** `mode: each` で `attachments_dir` を使うと、同じ添付ファイルが各エンティティに複製されます。エンティティごとに異なる添付が必要な場合はターゲットを分けてください。

### LaTeX 数式を使う（v0.2.1〜）

Markdown 内の LaTeX 数式は eLabFTW の MathJax でレンダリングできます。

```yaml
targets:
  - title: "数式メモ"
    docs_dir: "docs/"
    body_format: md    # ← 数式を使う場合は md を推奨
```

Markdown ファイル内でそのまま LaTeX を記述:

```markdown
# 実験結果

インライン数式: $E = mc^2$

ブロック数式:

$$
\frac{\partial f}{\partial x} = 2x + 1
$$

ドル記号をそのまま使いたい場合は \$ でエスケープ: 価格は \$100 です。
```

`body_format: html` でも数式は保護されますが、`md` の方がシンプルで確実です。

### 特定のターゲットだけ同期

```bash
$ esync -t "プロジェクト概要"
  [プロジェクト概要] リソース #42 を更新しました
```

### 既存エンティティとローカルを紐付け（link）

```bash
$ esync link 42
  [実験メモ.md] → リソース #42 に紐付けました
```

## コマンド一覧

| コマンド | 説明 |
|---------|------|
| `esync` | ローカル → eLabFTW に同期（push） |
| `esync pull` | eLabFTW → ローカルに取得（既存同期済み ID を再取得） |
| `esync pull --id 42 --entity items` | 指定 ID のリソースを取得 |
| `esync pull --id 42 --id 43 --entity items` | 複数 ID を一括取得 |
| `esync pull --id 42 --entity experiments` | 実験ノートとして取得 |
| `esync diff` | ローカルと eLabFTW の差分を表示 |
| `esync status` | 同期状態を確認 |
| `esync tag list` | リモートのタグ一覧を表示 |
| `esync tag list --id 42 --entity items` | 指定エンティティのタグ一覧 |
| `esync tag add "タグ" --id 42 --entity items` | タグを追加 |
| `esync tag remove "タグ" --id 42 --entity items` | タグを外す |
| `esync metadata get` | メタデータを表示 |
| `esync metadata set k=v` | メタデータを設定 |
| `esync category list` | カテゴリ一覧を表示 |
| `esync category show` | 現在のカテゴリを表示 |
| `esync category set "名前"` | カテゴリを設定（名前または ID） |
| `esync entity-status show` | エンティティのステータスを表示 |
| `esync entity-status set <ID>` | ステータスを変更 |
| `esync list` | リモートのリソース一覧を表示 |
| `esync list --entity experiments` | 実験ノート一覧を表示 |
| `esync link <ID>` | 既存リモートエンティティとローカルを紐付け |
| `esync verify` | ローカルとリモートの整合性チェック |
| `esync init` | 対話的に設定ファイルを作成 |
| `esync update` | ツールを最新版に更新 |
| `esync log` | 同期ログを表示 |
| `esync clone` | eLabFTW からプロジェクトを構築 |
| `esync whoami` | 現在のユーザー情報を表示 |
| `esync new --list` | テンプレート一覧を表示 |
| `esync new --template-id <ID>` | テンプレートからファイル作成 |
| `esync --dry-run` | 実行せずに同期内容を確認 |
| `esync --force` | 変更がなくても強制同期 |
| `esync -t "名前"` | 特定のターゲットだけ同期 |

> **Note:** `esync` は `elab-doc-sync` のエイリアスです。どちらでも同じように使えます。
> `uv run esync` のように実行してください。

## 同期モード

### merge（デフォルト）

複数の md を結合して 1 エンティティに送信:

```yaml
targets:
  - title: "プロジェクトドキュメント"
    docs_dir: "docs/"
```

### each

各 md を個別のエンティティとして送信（タイトルはファイル名から自動取得）:

```yaml
targets:
  - docs_dir: "experiments/"
    mode: each
    entity: experiments
```

### 組み合わせ

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

## 設定リファレンス

| キー | 必須 | デフォルト | 説明 |
|------|------|-----------|------|
| `elabftw.url` | ✅ | — | eLabFTW の URL |
| `elabftw.api_key` | ✅ | — | API キー（環境変数 `ELABFTW_API_KEY` が優先） |
| `elabftw.verify_ssl` | — | `true` | SSL 検証 |
| `targets[].title` | merge時✅ | — | エンティティのタイトル |
| `targets[].docs_dir` | ✅ | — | Markdown のディレクトリ |
| `targets[].pattern` | — | `*.md` | Glob パターン |
| `targets[].mode` | — | `merge` | `merge` / `each` |
| `targets[].entity` | — | `items` | `items`(`resources`) / `experiments` |
| `targets[].id_file` | — | `.elab-sync-ids/default.id` | ID 保存先 |
| `targets[].tags` | — | `[]` | push 時に自動追加するタグ（追記のみ、既存タグは外さない） |
| `targets[].category` | — | — | push 時に自動設定するカテゴリ（名前または ID） |
| `targets[].body_format` | — | `html` | `md`（Markdown のまま送信）/ `html`（HTML に変換して送信） |
| `targets[].attachments_dir` | — | — | 添付ファイルディレクトリ（画像以外のファイルを自動アップロード・ダウンロード） |

> **Note:** `attachments_dir` を `mode: each` で使用すると、同じディレクトリの添付ファイルが各エンティティに複製されます。エンティティごとに異なる添付が必要な場合は、ターゲットを分けてください。pull 時に複数エンティティから同名の添付ファイルがダウンロードされた場合、後のファイルで上書きされます。

> **Note:** `esync init` で新規作成する場合、`body_format` のデフォルト提案は `md` です。既存の設定ファイルで `body_format` を省略した場合は互換性のため `html` が適用されます。

> **Tip:** LaTeX 数式（`$...$` / `$$...$$`）を使う場合は `body_format: md` を推奨します。eLabFTW の MathJax が直接レンダリングします。`html` モードでも数式は保護されますが、`md` の方がシンプルです。

サンプル: [`.elab-sync.yaml.example`](.elab-sync.yaml.example)

> **Note:** `.elab-sync.yaml` は **UTF-8** で保存してください。Windows のメモ帳等で編集すると Shift-JIS (cp932) で保存される場合があります。既存の cp932 ファイルも読み込み可能ですが、次回保存時に UTF-8 で書き出されます。

## 困ったとき

| メッセージ | やること |
|-----------|---------|
| `API キーが設定されていません` | 上の③をやる |
| `設定ファイルが見つかりません` | `esync init` を実行 |
| `ファイルがありません` | `docs/` に `.md` ファイルを置く |

## 開発

```bash
git clone https://github.com/Kosaku-Noba/elab-doc-sync.git
cd elab-doc-sync
uv sync
```

## ライセンス

MIT

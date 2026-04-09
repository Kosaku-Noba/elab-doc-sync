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
| `targets[].body_format` | — | `html` | `md`（Markdown のまま送信）/ `html`（HTML に変換して送信） |
| `targets[].attachments_dir` | — | — | 添付ファイルディレクトリ（画像以外のファイルを自動アップロード・ダウンロード） |

> **Note:** `attachments_dir` を `mode: each` で使用すると、同じディレクトリの添付ファイルが各エンティティに複製されます。エンティティごとに異なる添付が必要な場合は、ターゲットを分けてください。pull 時に複数エンティティから同名の添付ファイルがダウンロードされた場合、後のファイルで上書きされます。

> **Note:** `esync init` で新規作成する場合、`body_format` のデフォルト提案は `md` です。既存の設定ファイルで `body_format` を省略した場合は互換性のため `html` が適用されます。

> **Tip:** LaTeX 数式（`$...$` / `$$...$$`）を使う場合は `body_format: md` を推奨します。eLabFTW の MathJax が直接レンダリングします。`html` モードでも数式は保護されますが、`md` の方がシンプルです。

サンプル: [`.elab-sync.yaml.example`](.elab-sync.yaml.example)

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

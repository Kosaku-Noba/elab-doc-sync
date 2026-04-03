# elab-doc-sync

Markdown ドキュメントを eLabFTW に同期する CLI ツール。

## 特徴

- 差分検知（SHA-256）で変更があるファイルだけ更新
- 画像の自動アップロード・URL 書き換え
- 2つの同期モード: `merge`（全結合→1エンティティ）/ `each`（1ファイル=1エンティティ）
- アイテム (`items`) と実験ノート (`experiments`) の両方に対応
- Windows / Linux 両対応

## インストール

```bash
pip install git+https://github.com/Kosaku-Noba/elab-doc-sync.git
```

## ユーザーへの配布方法

1. ユーザーに `pip install` → `elab-doc-sync init` を実行してもらう
2. `init` で設定ファイル・`.gitignore`・`README.md`・`docs/` が自動生成される

```bash
pip install git+https://github.com/Kosaku-Noba/elab-doc-sync.git
elab-doc-sync init
```

実行後のリポジトリ構成:
```
my-docs-repo/
├── docs/           ← Markdown を置く
├── .elab-sync.yaml ← init で自動生成
├── .gitignore      ← init で自動生成
└── README.md       ← init で自動生成
```

## 開発

```bash
git clone https://github.com/Kosaku-Noba/elab-doc-sync.git
cd elab-doc-sync
uv sync
```

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
| `elabftw.api_key` | — | — | API キー（環境変数 `ELABFTW_API_KEY` が優先） |
| `elabftw.verify_ssl` | — | `true` | SSL 検証 |
| `targets[].title` | merge時✅ | — | エンティティのタイトル |
| `targets[].docs_dir` | ✅ | — | Markdown のディレクトリ |
| `targets[].pattern` | — | `*.md` | Glob パターン |
| `targets[].mode` | — | `merge` | `merge` / `each` |
| `targets[].entity` | — | `items` | `items` / `experiments` |
| `targets[].id_file` | — | `.elab-sync-ids/default.id` | ID 保存先 |

サンプル: [`.elab-sync.yaml.example`](.elab-sync.yaml.example)

## ライセンス

MIT

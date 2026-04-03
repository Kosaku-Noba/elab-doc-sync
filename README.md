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
mkdir doc_sync
cd doc_sync
uv venv
uv pip install git+https://github.com/Kosaku-Noba/elab-doc-sync.git
uv run elab-doc-sync init

=== elab-doc-sync セットアップ ===

eLabFTW の URL: #elabFTWのURLを入力
SSL 証明書を検証しますか？ [Y/n]: n
ドキュメントディレクトリ [docs/]: 
ファイルパターン [*.md]: 
同期モード — merge: 全ファイルを1つに結合 / each: 1ファイル=1ノート [merge]: each
送信先 — items: アイテム / experiments: 実験ノート [items]: items

テンプレートファイルを展開中...
  .gitignore を作成しました
  README.md を作成しました
  docs/ ディレクトリを作成しました

✅ 設定ファイルを作成しました: .elab-sync.yaml
```

次に、eLabFTW の API キーを環境変数に設定してください:

Linux

```bash
export ELABFTW_API_KEY="your_api_key"
```

永続化するには ~/.bashrc (Linux) に追記してください:
```bash
echo 'export ELABFTW_API_KEY="your_api_key"' >> ~/.bashrc
```

Windows (PowerShell) 

```PowerShell
[System.Environment]::SetEnvironmentVariable("ELABFTW_API_KEY","your_api_key","User")
```

準備ができたら以下で同期を開始できます:
```bash
elab-doc-sync --dry-run  （確認）
elab-doc-sync            （実行）
```

実行後のリポジトリ構成:
```
./
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

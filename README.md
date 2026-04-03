# elab-doc-sync

Markdown ドキュメントを eLabFTW のアイテム・実験ノートに同期する CLI ツール。

## 概要

- 差分検知（SHA-256）による効率的な更新
- 画像の自動アップロード・URL 書き換え
- 複数ターゲットへの一括同期
- 2つの同期モード: `merge`（全結合→1エンティティ）/ `each`（1ファイル=1エンティティ）
- アイテム (`items`) と実験ノート (`experiments`) の両方に対応
- 対話的セットアップ (`init`)
- ドライラン (`--dry-run`)
- Windows / Linux 両対応

## アーキテクチャ

```
ツールリポジトリ (elab-doc-sync)          ユーザーのドキュメントリポジトリ
├── src/elab_doc_sync/                    ├── docs/*.md
│   ├── cli.py      (CLI)                ├── .elab-sync.yaml
│   ├── config.py   (設定読み込み)        ├── sync.py          ← template/ からコピー
│   ├── client.py   (API クライアント)    ├── .gitignore
│   └── sync.py     (同期エンジン)        └── README.md
├── template/        (ユーザー配布用)
│   ├── sync.py      (ブートストラップ)
│   ├── .gitignore
│   ├── docs/.gitkeep
│   └── README.md    (研究者向け)
└── pyproject.toml
```

`template/sync.py` がツールの自動取得・インストール・実行を担います。ユーザーは `python sync.py` だけで操作できます。

## 開発環境セットアップ

```bash
git clone <this-repo>
cd elab-doc-sync
uv sync
```

## ユーザーへの配布方法

1. `template/` の中身をユーザーのドキュメントリポジトリにコピー
2. `python sync.py init` を実行

## CLI リファレンス

```
elab-doc-sync [OPTIONS] [COMMAND]

コマンド:
  init       対話的に設定ファイルを作成
  status     同期状態を確認

オプション:
  -c, --config PATH    設定ファイルのパス（デフォルト: .elab-sync.yaml）
  -t, --target NAME    特定のターゲットのみ同期
  -f, --force          変更がなくても強制同期
  -n, --dry-run        実行せずに同期内容を確認
```

## 同期モード

### merge モード（デフォルト）

複数の Markdown ファイルを `---` 区切りで結合し、1つのエンティティとして送信します。

```yaml
targets:
  - title: "プロジェクトドキュメント"
    docs_dir: "docs/"
    pattern: "*.md"
    mode: merge          # デフォルト。省略可
    entity: items        # デフォルト。省略可
```

### each モード

各 Markdown ファイルを個別のエンティティとして送信します。タイトルはファイル名（拡張子なし）から自動取得されます。

```yaml
targets:
  - docs_dir: "experiments/"
    pattern: "*.md"
    mode: each
    entity: experiments  # 実験ノートとして送信
```

ID は `.elab-sync-ids/mapping.json` で一括管理されます:
```json
{
  "experiment_a.md": 42,
  "experiment_b.md": 43
}
```

### 複数ターゲットの組み合わせ

```yaml
elabftw:
  url: "https://your-elabftw.example.com"
  verify_ssl: false

targets:
  # プロジェクト全体のドキュメントを 1 アイテムにまとめる
  - title: "プロジェクト概要"
    docs_dir: "docs/"
    mode: merge
    entity: items
    id_file: ".elab-sync-ids/overview.id"

  # 各実験記録を個別の実験ノートとして送る
  - docs_dir: "experiments/"
    mode: each
    entity: experiments
    id_file: ".elab-sync-ids/experiments.id"
```

## 設定リファレンス (`.elab-sync.yaml`)

| キー | 必須 | デフォルト | 説明 |
|------|------|-----------|------|
| `elabftw.url` | ✅ | — | eLabFTW インスタンスの URL |
| `elabftw.verify_ssl` | — | `true` | SSL 証明書の検証 |
| `targets[].title` | merge時✅ | — | eLabFTW エンティティのタイトル |
| `targets[].docs_dir` | ✅ | — | Markdown ファイルのディレクトリ |
| `targets[].pattern` | — | `*.md` | ファイル選択の Glob パターン |
| `targets[].mode` | — | `merge` | `merge`: 全結合→1エンティティ / `each`: 1ファイル=1エンティティ |
| `targets[].entity` | — | `items` | `items`: アイテム / `experiments`: 実験ノート |
| `targets[].id_file` | — | `.elab-sync-ids/default.id` | ID の保存先（each モードでは同ディレクトリに `mapping.json` を生成） |

サンプル設定ファイル: [`.elab-sync.yaml.example`](.elab-sync.yaml.example)

## ライセンス

MIT

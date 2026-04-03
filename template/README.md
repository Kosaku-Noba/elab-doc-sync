# ドキュメント同期リポジトリ

このリポジトリの Markdown ドキュメントを eLabFTW に同期します。

## クイックスタート

### 1. 初回セットアップ

```bash
python sync.py init
```

対話形式で設定ファイル (`.elab-sync.yaml`) を作成します。

### 2. API キーの設定

eLabFTW の「ユーザー設定 → API キー」からキーを取得し、環境変数に設定してください。

Linux / macOS:
```bash
export ELABFTW_API_KEY="your_api_key"
```

Windows (PowerShell):
```powershell
[System.Environment]::SetEnvironmentVariable("ELABFTW_API_KEY","your_api_key","User")
```

### 3. 同期

```bash
# まず確認（実際には同期しません）
python sync.py --dry-run

# 同期を実行
python sync.py
```

## コマンド一覧

| コマンド | 説明 |
|---------|------|
| `python sync.py` | ドキュメントを同期 |
| `python sync.py init` | 設定ファイルを対話的に作成 |
| `python sync.py status` | 同期状態を確認 |
| `python sync.py --dry-run` | 実行せずに同期内容を確認 |
| `python sync.py --force` | 変更がなくても強制同期 |
| `python sync.py -t "名前"` | 特定のターゲットのみ同期 |

## 同期モード

### merge モード（デフォルト）

`docs/` 内の全 Markdown を結合して、eLabFTW の 1 つのアイテムとして送信します。

### each モード

各 Markdown ファイルを個別のエンティティ（アイテムまたは実験ノート）として送信します。タイトルはファイル名から自動取得されます。

設定例:
```yaml
targets:
  # 全ドキュメントを 1 アイテムにまとめる
  - title: "プロジェクト概要"
    docs_dir: "docs/"
    mode: merge
    entity: items

  # 各実験記録を個別の実験ノートとして送る
  - docs_dir: "experiments/"
    mode: each
    entity: experiments
```

## ドキュメントの追加

`docs/` ディレクトリに Markdown ファイルを追加してください。画像はドキュメント内で相対パスで参照すれば、同期時に自動アップロードされます。

```markdown
# 実験結果

![結果グラフ](images/result.png)
```

## トラブルシューティング

| 症状 | 対処法 |
|------|--------|
| `git が見つかりません` | Git をインストールしてください |
| `API キーが設定されていません` | 環境変数 `ELABFTW_API_KEY` を設定してください |
| `設定ファイルが見つかりません` | `python sync.py init` を実行してください |
| `ドキュメントがありません` | `docs/` に `.md` ファイルを追加してください |
| 同期されたか不安 | `python sync.py --dry-run` で事前確認できます |

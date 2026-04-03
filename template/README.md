# ドキュメント同期

`docs/` の Markdown を eLabFTW に自動同期します。

## 使い方（初回のみ）

```bash
# ① 設定ファイルを作る（質問に答えるだけ）
python sync.py init

# ② API キーを設定する
#    eLabFTW → ユーザー設定 → API Keys でキーを作成し、以下を実行:

# Linux / macOS
export ELABFTW_API_KEY="ここにキーを貼る"

# Windows (PowerShell)
[System.Environment]::SetEnvironmentVariable("ELABFTW_API_KEY","ここにキーを貼る","User")
```

## 使い方（毎回）

```bash
# 同期
python sync.py

# 同期前に確認したいとき
python sync.py --dry-run
```

## その他のコマンド

```bash
python sync.py status     # 同期状態を確認
python sync.py --force    # 変更がなくても強制同期
python sync.py -t "名前"  # 特定のターゲットだけ同期
```

## 困ったとき

| メッセージ | やること |
|-----------|---------|
| `API キーが設定されていません` | 上の②をやる |
| `設定ファイルが見つかりません` | `python sync.py init` を実行 |
| `ファイルがありません` | `docs/` に `.md` ファイルを置く |
| `git が見つかりません` | Git をインストールする |

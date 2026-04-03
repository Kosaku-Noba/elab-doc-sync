# ドキュメント同期

`docs/` の Markdown を eLabFTW に自動同期します。

## 使い方（初回のみ）

```bash
# ① ツールをインストール
pip install git+https://github.com/Kosaku-Noba/elab-doc-sync.git

# ② 設定ファイルを作る（質問に答えるだけ）
elab-doc-sync init

# ③ API キーを設定する
#    eLabFTW → ユーザー設定 → API Keys でキーを作成し、以下を実行:

# Linux / macOS
export ELABFTW_API_KEY="ここにキーを貼る"

# Windows (PowerShell)
[System.Environment]::SetEnvironmentVariable("ELABFTW_API_KEY","ここにキーを貼る","User")
```

## 使い方（毎回）

```bash
# 同期
elab-doc-sync

# 同期前に確認したいとき
elab-doc-sync --dry-run
```

## その他のコマンド

```bash
elab-doc-sync status     # 同期状態を確認
elab-doc-sync --force    # 変更がなくても強制同期
elab-doc-sync -t "名前"  # 特定のターゲットだけ同期
```

## 困ったとき

| メッセージ | やること |
|-----------|---------|
| `API キーが設定されていません` | 上の③をやる |
| `設定ファイルが見つかりません` | `elab-doc-sync init` を実行 |
| `ファイルがありません` | `docs/` に `.md` ファイルを置く |

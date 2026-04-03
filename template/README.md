# ドキュメント同期

`docs/` の Markdown を eLabFTW に自動同期します。

## 使い方（初回のみ）

### ① ツールをインストール

```bash
uv pip install git+https://github.com/Kosaku-Noba/elab-doc-sync.git
```

### ② 設定ファイルを作る（質問に答えるだけ）

```bash
uv run elab-doc-sync init
```

### ③ API キーを設定する

eLabFTW → ユーザー設定 → API Keys でキーを作成し、以下のいずれかの方法で設定してください。

**方法 A: `.elab-sync.yaml` に直接記載（最も簡単）**

`.elab-sync.yaml` の `elabftw` セクションに `api_key` を追加:

```yaml
elabftw:
  url: "https://your-elabftw.example.com"
  api_key: "ここにキーを貼る"
  verify_ssl: false
```

> ⚠️ `.elab-sync.yaml` は `.gitignore` に含まれているため、キーが Git に公開されることはありません。

**方法 B: 環境変数で設定（yaml より優先されます）**

Linux / macOS:
```bash
export ELABFTW_API_KEY="ここにキーを貼る"
```

Windows (PowerShell) — 現在のセッションのみ:
```powershell
$env:ELABFTW_API_KEY = "ここにキーを貼る"
```

Windows (PowerShell) — 永続化（設定後 PowerShell を再起動）:
```powershell
[System.Environment]::SetEnvironmentVariable("ELABFTW_API_KEY", "ここにキーを貼る", "User")
```

## 使い方（毎回）

```bash
# 同期
uv run elab-doc-sync

# 同期前に確認したいとき
uv run elab-doc-sync --dry-run
```

## その他のコマンド

```bash
uv run elab-doc-sync status     # 同期状態を確認
uv run elab-doc-sync --force    # 変更がなくても強制同期
uv run elab-doc-sync -t "名前"  # 特定のターゲットだけ同期
```

## 困ったとき

| メッセージ | やること |
|-----------|---------|
| `API キーが設定されていません` | 上の③をやる |
| `設定ファイルが見つかりません` | `uv run elab-doc-sync init` を実行 |
| `ファイルがありません` | `docs/` に `.md` ファイルを置く |

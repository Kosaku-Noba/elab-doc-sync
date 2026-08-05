# セットアップガイド

→ [プロジェクト概要](01_README.md) | [設定ファイル](04_CONFIGURATION.md)

## 前提条件

- Python 3.10 以上
- [uv](https://docs.astral.sh/uv/) （パッケージ管理・実行に使用）

## ① インストール

```bash
uv tool install --force git+https://github.com/Kosaku-Noba/elab-doc-sync.git
```

これにより `esync` と `elab-doc-sync` コマンドがパスに追加される。

## ② 設定ファイルを作る

```bash
esync init
```

対話形式で以下を入力する:

| 項目 | 必須 | デフォルト |
|---|---|---|
| eLabFTW の URL | ✅ | — |
| SSL 証明書検証 | — | yes |
| ドキュメントディレクトリ | — | `docs/` |
| ファイルパターン | — | `*.md` |
| 同期モード | — | `merge` |
| 送信先 | — | `items` |
| タイトル（merge 時） | ✅ | — |

完了すると `.elab-sync.yaml`、`.gitignore`、`README.md`、`docs/` が生成される。

## ③ API キーを設定する

eLabFTW → ユーザー設定 → API Keys でキーを作成し、以下のいずれかで設定:

**環境変数（推奨）:**

```bash
export ELABFTW_API_KEY="your_key"
```

**設定ファイル:**

```yaml
elabftw:
  api_key: "your_key"
```

環境変数が設定されている場合、設定ファイルの値より優先される。

## ④ 動作確認

```bash
# プレビュー（実際には同期しない）
esync --dry-run

# 同期実行
esync
```

## 開発環境セットアップ

```bash
git clone https://github.com/Kosaku-Noba/elab-doc-sync.git
cd elab-doc-sync
uv sync --extra test
uv run pytest -q -m "not integration"
```

## ツールの更新

```bash
esync update
```

`uv tool install --force` で Git リポジトリから最新版をインストールする。

設定ファイルの詳細は [設定リファレンス](04_CONFIGURATION.md) を参照。

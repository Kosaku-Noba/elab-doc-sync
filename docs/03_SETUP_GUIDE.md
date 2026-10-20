# セットアップガイド

→ [プロジェクト概要](01_README.md) | [設定ファイル](04_CONFIGURATION.md)

## 前提条件

- Python 3.10 以上
- [uv](https://docs.astral.sh/uv/) （パッケージ管理・実行に使用）
- eLabFTW（API v2）のアカウントと API キー

## ① インストール

```bash
uv tool install --force git+https://github.com/Kosaku-Noba/elab-doc-sync.git
```

これにより `esync` と `elab-doc-sync` コマンドがパスに追加される。`esync --version` でバージョンを確認できる。

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
| 送信先（`items`(`resources`) / `experiments`） | — | `items` |
| 送信形式（`md` / `html`） | — | `md` |

同期モードは `each` 固定で、質問しない。`.elab-sync.yaml` が既にある場合は上書きの確認を求める。

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

環境変数が設定されている場合、設定ファイルの値（`profiles` を使う場合は `default` プロファイルの値）より優先される。

## ④ Git 管理から除外する

設定ファイルには API キーが含まれる場合があるため、次を Git 管理対象外にする。`esync clone` が生成する `.gitignore` にはすべて含まれる。`esync init` は一覧を表示するが、テンプレートの `.gitignore` には `.elab-sync.yaml` と `.elab-sync-ids/` しか含まれないため、残りは手動で追記する。

```gitignore
.elab-sync.yaml
.elab-sync-ids/
.elab-sync-backups/
.elab-sync-operations/
.elab-sync-recovery.json
```

## ⑤ 動作確認

```bash
# 接続確認
esync whoami

# プレビュー（実際には同期しない）
esync --dry-run

# 同期実行
esync
```

既存の eLabFTW の記事からプロジェクトを作る場合は `esync clone --url URL --id ID --entity items` を使う（[CLI リファレンス](05_CLI_REFERENCE.md#clone)）。

## 開発環境セットアップ

```bash
git clone https://github.com/Kosaku-Noba/elab-doc-sync.git
cd elab-doc-sync
UV_CACHE_DIR=/tmp/uv-cache uv sync --extra test
UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q
```

実機接続テストは接続先を設定しない限りスキップされる（[テスト仕様](11_TEST_SPEC.md)）。

## ツールの更新

```bash
esync update
```

`uv tool install --force` で Git リポジトリから最新版をインストールする。更新後も古いバージョンが表示される場合は [トラブルシューティング](09_TROUBLESHOOTING.md#esync-update-したのにバージョンが古いまま) を参照。

v0.x から更新する場合は、先に [v1.0 への移行と復旧](13_MIGRATION_V1.md) を確認する。

設定ファイルの詳細は [設定リファレンス](04_CONFIGURATION.md) を参照。

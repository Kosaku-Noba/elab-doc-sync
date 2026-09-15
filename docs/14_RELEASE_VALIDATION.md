# v1.0リリース検証

検証日: 2026-09-15（JST）

## 自動テスト

| 環境 | 結果 |
|---|---|
| Linux / Python 3.10.20 | 366 passed、8 skipped（実機キー未設定） |
| Linux / Python 3.12.3 | 366 passed、8 skipped（実機キー未設定） |
| Linux / Python 3.14.3 | 366 passed、8 skipped（実機キー未設定） |
| Windows / Python 3.12 | CIマトリクスに追加。ローカルでは未実行 |

実機テストは既存6ケースに加え、`tests/test_integration_v1.py` の2ケース（md/html）を用意しました。wheel/sdistのビルドと、独立環境にwheelをインストールした `esync --help` の起動を確認済みです。

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q
```

## eLabFTWとの接続

設定済みサーバーの `/api/v2/info` を読み取り、eLabFTW **5.5.14** を確認しました。記事・添付の書き込みを伴うテストは検証先の確認待ちです。

```bash
ELABFTW_TEST_CONFIG=/path/to/test-config.yaml UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_integration_v1.py -v
```

このテストは指定先に一時記事を作成・更新し、終了時に削除します。既存の画像・添付の実機テストは `ELABFTW_DEMO_API_KEY` を設定して実行できます。

## 正式リリース条件

- 対応Pythonでの単体・CLI・復旧テスト通過。
- wheel/sdistのビルドと、wheelからのCLI起動確認。
- 指定した実機での本文・画像・添付の往復同期確認。
- コミット後レビューの指摘解決。

実機での書き込み検証が未完了の間は、バージョンを1.0.0へ変更せず、正式リリースを保留します。

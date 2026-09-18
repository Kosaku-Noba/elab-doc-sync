# v1.0リリース検証

検証日: 2026-09-15（JST）

## 自動テスト

| 環境 | 結果 |
|---|---|
| Linux / Python 3.10.20 | 385 passed、9 skipped（実機テストは別途実行） |
| Linux / Python 3.12.3 | 385 passed、9 skipped（実機テストは別途実行） |
| Linux / Python 3.14.3 | 385 passed、9 skipped（実機テストは別途実行） |
| Windows / Python 3.12 | CIマトリクスに追加。ローカルでは未実行 |

実機テストは既存6ケースに加え、`tests/test_integration_v1.py` の3ケース（md/html、タグなし記事）を用意しました。wheel/sdistのビルドと、独立環境にwheelをインストールした `esync --help` の起動を確認済みです。

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q
```

## eLabFTWとの接続

設定済みサーバーの `/api/v2/info` を読み取り、eLabFTW **5.5.14** を確認しました。ユーザーが許可した設定先で本文（md/html）、画像、添付、競合検出、強制pullとバックアップ復元の実機テスト8件に加え、タグなし記事のCLI経由pull/push・最初のタグ追加1件が通過しました。作成した一時記事はすべてDELETE後の削除済み状態まで確認しています。

```bash
ELABFTW_TEST_CONFIG=/path/to/test-config.yaml UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_integration.py tests/test_integration_v1.py -v
```

このテストは指定先に一時記事を作成・更新し、終了時に削除します。`ELABFTW_TEST_CONFIG` は全9ケースの接続先に適用されます。既存6ケースのみ、設定ファイルを指定せず `ELABFTW_DEMO_API_KEY` でデモサーバーを使用することもできます。`ELABFTW_TEST_JOURNAL` にファイルパスを指定すると作成・削除IDを記録します。

## 正式リリース条件

- 対応Pythonでの単体・CLI・復旧テスト通過。
- wheel/sdistのビルドと、wheelからのCLI起動確認。
- 指定した実機での本文・画像・添付の往復同期確認。
- コミット後レビューの指摘解決。

バージョンを **1.0.0** に更新。wheel/sdistは1.0.0でビルドし、独立環境でwheelからCLIを起動して確認しました。公開・タグ作成はこの検証に含みません。

## 実機で確認した削除仕様

eLabFTW 5.5.14ではDELETE後もGETが成功し、`state=3`（削除済み）を返します。同期クライアントはこれをHTTP 404と同じ「リモート削除」として扱い、通常push・強制pushとも更新を停止します。[eLabFTWの状態定義](https://github.com/elabftw/elabftw/blob/master/src/Enums/State.php)。

## タグなし記事の追加確認

旧0.5.3のpullは `tags: null` を列挙して失敗する経路がありました。1.0.0では空タグを扱い、タグAPIのnull応答も空配列へ正規化します。タグ未指定・null・空文字・空配列を含む回帰テストを追加し、実機ではタグなしの記事をCLI経由で取得・編集・送信した後、最初のタグを追加できることを確認しました。通常の `esync --version` と作業環境のバージョンが一致していることも確認してください。


## v1.0.1 の追加検証（2026-09-18）

今回の変更は `rm` のローカル対象選択（ディレクトリ・glob・ファイル名への正規表現）です。

| 環境 | 結果 |
|---|---|
| Linux / Python 3.10.20 | 411 passed、9 skipped |
| Linux / Python 3.12.3 | 411 passed、9 skipped |
| Linux / Python 3.14.3 | 411 passed、9 skipped |

wheel/sdist のビルドと、独立した Python 3.12 環境への wheel インストール後の `esync --version`（1.0.1）・`esync rm --help` を確認しました。9件のスキップは実機接続テストです。今回はリモートAPI処理に変更がないため実機往復同期は再実行せず、上記 v1.0.0 の実機検証結果を参照します。Windows は GitHub Actions の結果で確認します。

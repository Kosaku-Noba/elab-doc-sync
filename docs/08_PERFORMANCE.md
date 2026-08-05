# 性能仕様・制約

→ [同期エンジン](07_SYNC_ENGINE.md) | [トラブルシューティング](09_TROUBLESHOOTING.md)

## 通信性能

### タイムアウト

| 操作 | タイムアウト | 備考 |
|---|---|---|
| 通常 API リクエスト（GET/PATCH/POST/DELETE） | 30 秒 | `_req()` のデフォルト |
| ファイルアップロード（画像・添付） | 60 秒 | ファイルサイズに応じて延長 |

### リトライ

ファイルアップロード（`upload_file`）は Timeout / ConnectionError / 5xx エラー時に1回だけ自動リトライする。その他の API リクエストにはリトライ機構なし。ハッシュ差分検知により、再実行時に成功済みファイルはスキップされる。

## API エンドポイント

| 操作 | メソッド | パス |
|---|---|---|
| リソース一覧 | GET | `/api/v2/items` |
| リソース取得 | GET | `/api/v2/items/{id}` |
| リソース作成 | POST | `/api/v2/items` |
| リソース更新 | PATCH | `/api/v2/items/{id}` |
| リソース削除 | DELETE | `/api/v2/items/{id}` |
| 実験一覧 | GET | `/api/v2/experiments` |
| 実験取得 | GET | `/api/v2/experiments/{id}` |
| 実験作成 | POST | `/api/v2/experiments` |
| 実験更新 | PATCH | `/api/v2/experiments/{id}` |
| 実験削除 | DELETE | `/api/v2/experiments/{id}` |
| ファイルアップロード | POST | `/api/v2/{entity_type}/{entity_id}/uploads` |
| タグ一覧 | GET | `/api/v2/{entity_type}/{entity_id}/tags` |
| タグ追加 | POST | `/api/v2/{entity_type}/{entity_id}/tags` |
| タグ削除 | DELETE | `/api/v2/{entity_type}/{entity_id}/tags/{tag_id}` |
| タグ解除 | PATCH | `/api/v2/{entity_type}/{entity_id}/tags/{tag_id}` |
| メタデータ更新 | PATCH | `/api/v2/{entity_type}/{entity_id}` |

### 認証

| 項目 | 仕様 |
|---|---|
| 方式 | `Authorization` ヘッダーに API キーを直接設定 |
| Content-Type | `application/json`（ファイルアップロード時は `multipart/form-data`） |

## 制約・制限事項

| 項目 | 制限 |
|---|---|
| 同時接続 | シングルスレッド・逐次処理 |
| ファイルサイズ上限 | eLabFTW サーバー側の設定に依存 |
| 対応画像形式 | eLabFTW がアップロードを受け付ける全形式 |
| Markdown 方言 | Python-Markdown 準拠（GFM とは一部差異あり） |
| 双方向同期 | 非対応（push と pull は独立操作） |
| リトライ | アップロードのみ1回自動リトライ（Timeout/5xx） |
| レート制限 | 未実装（eLabFTW 側の制限に依存） |
| プロファイル切替 | ターゲット単位（コマンド単位での切替は未対応） |

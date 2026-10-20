# 性能仕様・制約

→ [同期エンジン](07_SYNC_ENGINE.md) | [トラブルシューティング](09_TROUBLESHOOTING.md)

## 通信性能

### タイムアウト

| 操作 | タイムアウト | 備考 |
|---|---|---|
| 通常 API リクエスト（GET/PATCH/POST/DELETE） | 30 秒 | `_req()` のデフォルト |
| ファイルアップロード（画像・動画・添付） | 60 秒 | 固定（ファイルサイズによらない） |

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
| 汎用取得・更新 | GET / PATCH | `/api/v2/{entity_type}/{entity_id}` |
| ファイルアップロード | POST | `/api/v2/{entity_type}/{entity_id}/uploads` |
| アップロード一覧 | GET | `/api/v2/{entity_type}/{entity_id}/uploads` |
| アップロード取得 | GET | `/api/v2/{entity_type}/{entity_id}/uploads/{upload_id}?format=binary` |
| アップロード削除 | DELETE | `/api/v2/{entity_type}/{entity_id}/uploads/{upload_id}` |
| タグ一覧 | GET | `/api/v2/{entity_type}/{entity_id}/tags` |
| タグ追加 | POST | `/api/v2/{entity_type}/{entity_id}/tags` |
| タグ削除 | DELETE | `/api/v2/{entity_type}/{entity_id}/tags/{tag_id}` |
| タグ解除 | PATCH | `/api/v2/{entity_type}/{entity_id}/tags/{tag_id}` |
| メタデータ更新 | PATCH | `/api/v2/{entity_type}/{entity_id}` |
| リンク一覧 | GET | `/api/v2/{entity_type}/{entity_id}/{experiments\|items}_links` |
| リンク作成 | POST | `/api/v2/{entity_type}/{entity_id}/{experiments\|items}_links/{target_id}` |
| リンク削除 | DELETE | `/api/v2/{entity_type}/{entity_id}/{experiments\|items}_links/{target_id}` |
| リソースのカテゴリ一覧 | GET | `/api/v2/items_types` |
| 実験ノートのカテゴリ一覧 | GET | `/api/v2/experiments_categories` |
| 実験テンプレート | GET | `/api/v2/experiments_templates[/{id}]` |
| ユーザー情報 | GET | `/api/v2/users/me` |

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
| 双方向同期 | 自動の双方向同期はしない（push と pull は独立操作。両側の変更は pull で 3-way マージ） |
| リトライ | アップロードのみ1回自動リトライ（Timeout/5xx） |
| レート制限 | 未実装（eLabFTW 側の制限に依存） |
| プロファイル切替 | ターゲット単位。`category`・`list`・`new` は `-t` で選んだターゲットの接続先 |
| 削除済み記事 | eLabFTW 5.5 は DELETE 後も GET が `state=3` を返す。リソース・実験ノートの取得ではこれを 404 と同じ「リモート削除」として扱う |

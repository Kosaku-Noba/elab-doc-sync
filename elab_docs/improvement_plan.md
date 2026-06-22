# 画像・バイナリデータ取り扱い改善プラン

## 概要

demo.elabftw.net を用いて画像およびバイナリ添付ファイルの upload/download 機能をテスト・改善する。

## Phase 1: インテグレーションテスト作成

demo.elabftw.net に対する実 API テストスクリプトを作成し、現状の動作を確認する。

- items 作成 → 画像付き Markdown を push → リモート body に画像 URL が含まれるか確認
- pull → ダウンロードした画像がローカルに存在し内容一致を確認
- 添付ファイル push → バイナリ（PDF, CSV 等）をアップロードし list_uploads で確認
- 添付ファイル pull → ダウンロードして内容一致を検証
- ラウンドトリップ → push → pull → 再 push で冪等性確認

## Phase 2: 画像 upload/download の改善

| 改善 | 内容 |
|------|------|
| ハッシュベース差分検知 | サイズ比較に加え SHA-256 で内容一致を確認 |
| アップロード失敗時リトライ | タイムアウトや 5xx で 1 回リトライ |
| download 時のファイル名安定化 | prefix なしの real_name をそのまま使うオプション追加 |

## Phase 3: バイナリ添付の取り扱い改善

| 改善 | 内容 |
|------|------|
| ハッシュベース差分検知 | 添付ファイルもローカル SHA-256 とリモート hash で判定 |
| 添付の削除同期 | ローカルから削除されたファイルをリモートからも削除するオプション（`--prune-attachments`） |
| ファイルタイプフィルタ | `attachments_pattern` 設定でアップロード対象を glob 指定 |

## Phase 4: esync update 修正

`cmd_update` を `uv tool install --force` 方式に修正する。

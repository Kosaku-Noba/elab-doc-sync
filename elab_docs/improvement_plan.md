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

---

## 実装後の仕様サマリー（Phase 1〜4 完了）

### 画像（Markdown 本文内 `![](...)` 参照）

| 操作 | 動作 |
|------|------|
| push | ローカル画像を検知 → アップロード → 本文中 URL を eLabFTW URL に書き換え |
| pull | eLabFTW URL を検知 → ダウンロード(`images/`) → 相対パスに書き換え |
| 差分検知 | サイズ + SHA-256（リモートに hash フィールドがある場合）。なければサイズ一致で再利用 |
| リトライ | Timeout / ConnectionError / 5xx で1回自動リトライ。4xx は即失敗 |

### バイナリ添付ファイル（`attachments_dir` 内の非画像ファイル）

| 操作 | 動作 |
|------|------|
| push | `attachments_dir` 内の `attachments_pattern` に一致するファイルをアップロード |
| pull / clone | リモートの非画像添付を `attachments_dir` にダウンロード |
| 差分検知 | サイズ + SHA-256（リモート hash があれば比較、なければサイズ一致で再利用） |
| `--force` | 差分なしでも再アップロード |
| `--prune-attachments` | ローカルに存在しない＋pattern に一致するリモート添付を削除 |

### アセット変更検知（`.assets_hash`）

- 画像・添付ファイルの内容ハッシュを `.assets_hash` に保存
- 本文未変更でも画像/添付だけ差し替えた場合に同期対象になる
- アップロード失敗時はハッシュを保存しない → 次回再試行される
- 初回（ハッシュファイル不在時）は変更扱いしない（初期化のみ）

### 設定例

```yaml
targets:
  - title: "実験レポート"
    docs_dir: "docs/"
    attachments_dir: "attachments/"
    attachments_pattern: "*.csv"  # 省略時: * (全ファイル)
    entity: items
```

### esync update

- `uv tool install --force git+https://github.com/Kosaku-Noba/elab-doc-sync.git` を実行
- 失敗時は手動コマンドを案内して終了

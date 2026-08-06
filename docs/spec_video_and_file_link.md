# 仕様書: 動画埋め込み & ファイルリンクアップロード機能

## 概要

Markdown 本文中のリンクを解析し、リンク先のローカルファイルを eLabFTW にアップロードして本文を書き換える機能。

## 対象リンク形式

| 形式 | 例 |
|------|---|
| 通常リンク | `[説明テキスト](path/to/file)` |
| 画像記法 | `![代替テキスト](path/to/file)` |

## ファイル種別と処理

| 拡張子 | 種別 | 処理 | 変換結果 |
|--------|------|------|----------|
| `.png`, `.jpg`, `.jpeg`, `.gif`, `.svg`, `.webp`, `.bmp`, `.ico` | 画像 | 既存 `_rewrite_images` で処理 | `![alt](upload_url)` |
| `.mp4`, `.webm` | 動画 | 新規 `_rewrite_videos` で処理 | `<video src="upload_url" controls>text</video>` |
| 上記以外 | その他ファイル | 新規 `_rewrite_file_links` で処理 | `[text](upload_url)` |

## 処理順序

```
Markdown 本文
  ↓ _rewrite_images（画像のアップロード＋URL書き換え）
  ↓ _rewrite_videos（動画のアップロード＋<video>タグ変換）
  ↓ _rewrite_file_links（その他ファイルのアップロード＋URL書き換え）
  ↓ _md_to_html（body_format: html の場合）
送信用 body
```

## 動画埋め込み仕様（`_rewrite_videos`）

### 入力パターン

- `[動画の説明](media/experiment.mp4)` — 通常リンク
- `![動画の説明](media/experiment.mp4)` — 画像記法

### 出力

```html
<video src="https://elab.example.com/app/download.php?f=longname&name=experiment.mp4&storage=1" controls>動画の説明</video>
```

### 動画拡張子

- `.mp4`
- `.webm`

### body_format との関係

- `body_format: md` — `<video>` タグをそのまま Markdown 本文に挿入（eLabFTW は HTML パススルー対応）
- `body_format: html` — HTML 変換後の本文に `<video>` タグが含まれる（Markdown→HTML 変換時に HTML タグは保持される）

## ファイルリンクアップロード仕様（`_rewrite_file_links`）

### 入力パターン

- `[データファイル](data/results.csv)` — 通常リンク
- `![プロトコル](docs/protocol.pdf)` — 画像記法（画像・動画以外）

### 出力

```markdown
[データファイル](https://elab.example.com/app/download.php?f=longname&name=results.csv&storage=1)
```

※ `![alt]` 形式の場合も `[alt](url)` に正規化する（画像でも動画でもないため）。

## 重複チェック（再アップロード防止）

既存の画像・添付ファイルと同じ方式:

1. エンティティの現在のアップロード一覧を取得（`list_uploads`）
2. ファイル名（`real_name`）が一致するアップロードを探す
3. さらにファイルサイズが一致すれば「未変更」と判断し再利用
4. サイズ不一致なら新規アップロードし、旧添付を削除

`--force` 指定時はサイズチェックをスキップし常に再アップロードする。

## `attachments_dir` との関係

- 本文リンクからのアップロードと `attachments_dir` は**独立して共存**する
- 重複アップロードチェックは `list_uploads` のレスポンスに基づくため、どちらの経路でアップロードされたファイルも検出される
- 同名ファイルが本文リンクと `attachments_dir` の両方に存在する場合、それぞれ独立にアップロードされる（ユーザー責任）

## `_rewrite_images` への変更

動画ファイル（`.mp4`, `.webm`）が画像記法 `![alt](video.mp4)` で参照されている場合、`_rewrite_images` ではスキップし `_rewrite_videos` で処理する。

条件追加: リンク先の拡張子が `VIDEO_EXTENSIONS` に含まれる場合はマッチをそのまま返す。

## 正規表現

### 既存

```python
IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")  # ![alt](src)
```

### 新規追加

```python
LINK_RE = re.compile(r"(?<!!)\[([^\]]*)\]\(([^)]+)\)")  # [text](src) ※ ![ を除外
```

## 定数

```python
VIDEO_EXTENSIONS = frozenset({".mp4", ".webm"})
IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".ico"})  # 既存
```

## ブランチ戦略

| ブランチ | 対象 Task | 内容 |
|---------|----------|------|
| `feature/video-embed` | Task 1〜3 | 動画リンク検出、`_rewrite_videos`、sync 統合 |
| `feature/file-link-upload` | Task 4〜5 | `_rewrite_file_links`、sync 統合、結合テスト |

## テスト方針

- ユニットテスト: `tests/test_sync.py` に追加
- テストフィクスチャ: `test_fixtures/` にダミーファイルを配置（`.gitignore` 対象）
- Mock: `client.upload_file`, `client.list_uploads` を Mock してテスト

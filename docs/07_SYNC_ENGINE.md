# 同期エンジン詳細

→ [API リファレンス](06_API_REFERENCE.md) | [性能仕様](08_PERFORMANCE.md)

## EachDocsSyncer

1 ファイル = 1 エンティティとして個別に同期する。

```python
EachDocsSyncer(client: ELabFTWClient, target: TargetConfig, project_root: Path)
```

| メソッド | 戻り値 | 説明 |
|---|---|---|
| `collect_files()` | `list[Path]` | docs_dir から pattern に一致するファイル一覧（辞書順） |
| `dry_run()` | `list[dict]` | 各ファイルの `{filename, title, images, videos, file_links, changed, entity_id}` |
| `sync(force, prune_attachments)` | `int` | 同期実行。更新した件数を返す |
| `_detect_renames(mapping, md_files, entity_label)` | `dict` | リネーム検出して mapping を更新 |
| `_load_mapping()` | `dict` | mapping.json を読み込み（マイグレーション付き） |
| `_save_mapping(mapping)` | `None` | mapping.json を保存 |

## 2パス sync 構造

同一 push 内で新規作成されるファイル間のリンクも正しく解決するため、sync は2パスで実行される。

### パス1: 全 ID 確定

```
1. docs_dir から pattern に一致するファイルを収集
2. mapping.json を読み込み
3. リネーム検出 (_detect_renames)
4. 各ファイルについて:
   a. SHA-256 ハッシュで差分検知 + メタデータ/アセット変更検知
   b. 変更なし → スキップ（pending に追加しない）
   c. 競合検出（remote_hash 比較）
   d. mapping に ID なし or リモートに不在 → 新規作成して mapping に追加
   e. (file, title, raw_body, eid, 変更フラグ) を pending に追加
```

### パス2: リンク変換 + 送信

```
各 pending について:
1. _rewrite_images     — ローカル画像をアップロードし URL に書き換え
2. _rewrite_videos     — 動画をアップロードし <video> タグに変換
3. _rewrite_file_links — 非画像・非動画ファイルをアップロードし URL 書き換え
4. _rewrite_local_links — [text](./file.md) → eLabFTW 記事 URL に変換
5. body_format に応じて HTML 変換
6. eLabFTW に PATCH で更新
7. タグ同期・カテゴリ同期
8. 添付ファイルアップロード（attachments_dir 指定時）
9. ハッシュ保存（local_hash, remote_hash, meta_hash, assets_hash）
10. 同期ログに記録
```

## ファイル間リンク変換

### Push 時: `_rewrite_local_links()`

each モード専用。`[text](./file.md)` 形式のリンクを eLabFTW 記事 URL に変換する。

**対象:**
- `[text](./file.md)`, `[text](file.md)`, `[text](../dir/file.md)`

**除外:**
- 画像リンク (`![...](...)`)
- 外部 URL (`http://`, `https://`)
- アンカーリンク (`#...`)
- 非 `.md` ファイル

**変換例:**
```
[セットアップ](./setup.md) → [セットアップ](https://elab.example.com/items.php?mode=view&id=42)
```

**仕様:**
- mapping に存在するファイルのみ変換（未同期リンクはそのまま残す）
- 2パス構造により、同一 push 内の新規ファイル間リンクも解決可能

### Pull 時: `_rewrite_elab_links_to_local()`

eLabFTW 記事 URL をローカルファイルリンクに逆変換する。

**判定:**
- ホスト完全一致（`urlparse` で比較、前方一致ではない）
- フラグメント (`#section`) は保持される

**変換例:**
```
[セットアップ](https://elab.example.com/items.php?mode=view&id=42#intro)
  → [セットアップ](./setup.md#intro)
```

## リネーム検出

### `_detect_renames()`

push 時に mapping ロード直後に実行。ファイル名変更を検出して mapping を更新する。

**アルゴリズム:**
1. mapping にあるがファイルが存在しない → `missing`（旧ファイル候補）
2. ファイルが存在するが mapping にない → `new`（リネーム後の候補）
3. `missing` と `new` が 1:1 の場合のみ自動検出
4. 内容ハッシュで同一性を検証:
   - 一致 → 純粋リネーム: タイトルを即時更新
   - 不一致 → リネーム+編集: mapping 更新のみ（本文はパス2で送信）

**制約:**
- 複数ファイルの同時リネームは対応関係が不明なため警告のみ
- 一度に1ファイルずつリネームすることを推奨

## 動画埋め込み

### `_rewrite_videos()`

Markdown 内の動画リンクを eLabFTW にアップロードし `<video>` タグに変換する。

**対象:**
- 通常リンク: `[説明](video.mp4)`
- 画像記法: `![説明](video.mp4)`

**対象拡張子:** `.mp4`, `.webm`

**変換結果:**
```html
<video src="https://elab.example.com/app/download.php?f=abc&name=video.mp4&storage=1" controls>説明</video>
```

**重複チェック:** ファイル名+サイズ一致で既存アップロードを再利用。

## ファイルリンクアップロード

### `_rewrite_file_links()`

非画像・非動画のローカルファイルリンクをアップロードし URL を書き換える。

**対象:**
- 通常リンク: `[データ](./results.csv)`
- 画像記法: `![プロトコル](protocol.pdf)` → `[プロトコル](url)` に正規化

**除外:**
- 画像ファイル（`_rewrite_images` で処理）
- 動画ファイル（`_rewrite_videos` で処理）
- `.md` ファイル（`_rewrite_local_links` で処理）
- 外部 URL

## 処理パイプライン順序

```
images → videos → file_links → local_links
```

各段階は前段で処理済みのファイル種別をスキップするため干渉しない。

## 競合検出

push 時にリモートが前回同期以降に変更されていないか確認する。

```
前回保存した remote_hash ≠ 現在のリモート body のハッシュ
  → ConflictError を発生
  → ユーザーに esync pull または --force を案内
```

## Pull フロー

```
1. 対象エンティティを特定（--id / mapping / 全件取得）
2. --id 指定時: 自動振り分けで保存先ターゲットを決定
   - 既紐付け → そのディレクトリ
   - スコアリング（tags/category/title_pattern）
   - --auto: 最高スコアで自動決定
3. eLabFTW から HTML body を取得
4. HTML → Markdown に変換（markdownify）
5. 画像ダウンロード
6. eLabFTW URL → ローカルリンク逆変換
7. タイトル変更によるファイルリネーム（reverse_mapping で検出）
8. ローカルにファイル保存
9. ID マッピング・ハッシュを保存
10. 同期ログに記録
```

## mapping.json のターゲット分離

各ターゲットは独立した状態ディレクトリを持つ。

```
.elab-sync-ids/
├── elab_docs/           # docs_dir="elab_docs" のターゲット
│   ├── mapping.json
│   ├── *.hash
│   └── *.remote_hash
├── elab_weekly/         # docs_dir="elab_weekly" のターゲット
│   ├── mapping.json
│   └── ...
└── sync-log.jsonl       # 全ターゲット共通
```

**マイグレーション:** 旧共有 `mapping.json` が存在し、新パスに mapping がない場合、対象 `docs_dir` に存在するファイルのエントリだけを自動移行する。

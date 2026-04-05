# 同期エンジン詳細

→ [API リファレンス](06_API_REFERENCE.md) | [性能仕様](08_PERFORMANCE.md)

## 同期モード

### merge モード — `DocsSyncer`

複数の Markdown を結合して 1 エンティティに同期する。

```python
DocsSyncer(client: ELabFTWClient, target: TargetConfig, project_root: Path)
```

| メソッド | 戻り値 | 説明 |
|---|---|---|
| `collect_docs()` | `str` | docs_dir から Markdown を収集し `\n\n---\n\n` で結合 |
| `collect_files()` | `list[Path]` | ファイル一覧（辞書順） |
| `has_changed(body)` | `bool` | 保存済みハッシュとの差分判定 |
| `save_hash(body)` | `None` | ハッシュをファイルに保存 |
| `read_item_id()` | `int \| None` | 保存済みエンティティ ID |
| `save_item_id(item_id)` | `None` | エンティティ ID を保存 |
| `save_remote_hash(remote_body)` | `None` | リモート body のハッシュを保存 |
| `dry_run()` | `dict` | `{"files", "images", "changed", "item_id"}` |
| `sync(force=False)` | `bool` | 同期実行。更新した場合 True |

### each モード — `EachDocsSyncer`

1 ファイル = 1 エンティティとして個別に同期する。

```python
EachDocsSyncer(client: ELabFTWClient, target: TargetConfig, project_root: Path)
```

| メソッド | 戻り値 | 説明 |
|---|---|---|
| `collect_files()` | `list[Path]` | ファイル一覧（辞書順） |
| `dry_run()` | `list[dict]` | 各ファイルの `{"filename", "title", "images", "changed", "entity_id"}` |
| `sync(force=False)` | `int` | 更新した件数 |

each モードでは `mapping.json` でファイル名 → エンティティ ID を管理する。

## Push フロー

### merge モード

```
1. docs_dir から pattern に一致するファイルを収集（辞書順）
2. 全ファイルを結合（セパレータ: \n\n---\n\n）
3. SHA-256 ハッシュを計算し、保存済みハッシュと比較
4. 変更なし → スキップ（--force 時は続行）
5. ID ファイルからエンティティ ID を読み込み
6. 競合検出: リモート body のハッシュを前回保存値と比較
7. ID なし or エンティティ不在 → 新規作成
8. ローカル画像をアップロード・URL 書き換え
9. Markdown → HTML 変換
10. eLabFTW に PATCH で更新
11. ローカルハッシュ・リモートハッシュを保存
12. 同期ログに記録
```

### each モード

```
1. docs_dir から pattern に一致するファイルを収集
2. mapping.json からファイル名 → ID のマッピングを読み込み
3. 各ファイルについて:
   a. SHA-256 ハッシュで差分検知
   b. 変更なし → スキップ
   c. 競合検出
   d. マッピングに ID なし or エンティティ不在 → 新規作成
   e. 画像アップロード・URL 書き換え
   f. Markdown → HTML 変換
   g. eLabFTW に PATCH で更新
   h. ハッシュ・マッピングを保存
   i. 同期ログに記録
```

## Pull フロー

```
1. 対象エンティティを特定（--id / mapping / 全件取得）
2. eLabFTW から HTML body を取得
3. HTML → Markdown に変換（markdownify, heading_style="ATX"）
4. ローカルにファイル保存
5. ID マッピング・ハッシュを保存（次回 push 時の不要更新を防止）
6. 同期ログに記録
```

## 競合検出

push 前にリモートの body ハッシュを前回同期時の保存値と比較する。

| 状態 | 動作 |
|---|---|
| リモートハッシュファイルなし | 競合チェックをスキップ（初回同期） |
| ハッシュ一致 | 競合なし → push 続行 |
| ハッシュ不一致 | `ConflictError` を送出 |
| `--force` 指定 | 競合チェックをバイパス |

`ConflictError` 発生時のメッセージ:
```
リモートが前回同期以降に変更されています（items #42）
→ esync pull で先にリモート変更を取り込むか、--force で強制上書きしてください
```

## 差分検知

| 項目 | 仕様 |
|---|---|
| アルゴリズム | SHA-256 先頭 16 文字 |
| 比較対象 | 画像 URL 書き換え前の raw Markdown |
| ハッシュファイルなし | 変更ありと判定（初回同期） |
| `--force` | ハッシュ比較をバイパス |

## 画像処理

| 項目 | 仕様 |
|---|---|
| 検出パターン | `!\[([^\]]*)\]\(([^)]+)\)` |
| スキップ条件 | URL が `http://` / `https://` で始まる場合 |
| パス解決順序 | `docs_dir` 相対 → `project_root` 相対 |
| 失敗時 | 警告出力、元の参照を維持（同期は中断しない） |

## Markdown 変換

| 拡張 | 機能 |
|---|---|
| `tables` | テーブル記法 |
| `fenced_code` | フェンスドコードブロック |
| `codehilite` | コードハイライト |
| `toc` | 目次生成 |
| `nl2br` | 改行保持 |

## ファイル管理

| ファイル | 内容 |
|---|---|
| `*.id` | エンティティ ID（整数、1行） |
| `*.hash` | SHA-256 先頭 16 文字（ローカル差分検知用） |
| `*.remote_hash` | リモート body のハッシュ（競合検出用） |
| `mapping.json` | each モードのファイル名 → ID マッピング |
| `sync-log.jsonl` | 同期履歴（JSONL 形式） |

すべて `.elab-sync-ids/` ディレクトリに保存される。

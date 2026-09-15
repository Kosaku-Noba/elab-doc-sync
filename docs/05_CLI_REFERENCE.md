# CLI リファレンス

→ [設定ファイル](04_CONFIGURATION.md) | [API リファレンス](06_API_REFERENCE.md)

## コマンド一覧

| コマンド | 説明 |
|---|---|
| `esync` | ローカル → eLabFTW に同期（push） |
| `esync pull` | eLabFTW → ローカルに取得 |
| `esync pull --id 42 --entity items` | 指定 ID のリソースを取得 |
| `esync diff` | ローカルと eLabFTW の差分を表示 |
| `esync status` | 同期状態を確認 |
| `esync tag list/add/remove` | タグ操作 |
| `esync category list/show/set` | カテゴリ操作 |
| `esync metadata get/set` | メタデータ操作 |
| `esync entity-status show/set` | エンティティステータス操作 |
| `esync list` | リモートのリソース/実験ノート一覧 |
| `esync link <ID>` | 手動紐付け |
| `esync rm <ファイルパス>` | 追跡解除（`--local` でローカルファイルも削除） |
| `esync verify` | 整合性チェック |
| `esync profile list/add/remove` | 接続プロファイル管理 |
| `esync whoami` | 現在のユーザー情報 |
| `esync new` | テンプレートからファイル作成 |
| `esync clone` | eLabFTW からプロジェクト構築 |
| `esync log` | 同期ログ表示 |
| `esync init` | 対話的に設定ファイルを作成 |
| `esync update` | ツールを最新版に更新 |

> `esync` は `elab-doc-sync` のエイリアス。

## push（デフォルトコマンド）

```bash
esync [--dry-run] [--force] [-t TARGET] [--prune-attachments]
```

| オプション | 説明 |
|---|---|
| `--dry-run` | 実際に送信せず変更予定を表示 |
| `--force` | リモート本文を退避して強制送信。接続・取得エラーは無視しない |
| `-t`, `--target` | 特定ターゲットのみ実行 |
| `--prune-attachments` | リモートの不要添付を削除 |

**push 処理フロー:**
1. 本文ハッシュが一致する一意なリネームを検出し、紐付けを更新（タイトル送信は競合確認後）
2. パス1: 全ファイルの ID を確定（新規作成含む）
3. パス2: リンク変換 + body 送信
   - 画像 → 動画 → ファイルリンク → ローカルリンク変換

## pull

```bash
esync pull [--id ID] [--entity TYPE] [--dry-run] [--force] [--auto] [--dir DIR] [-t TARGET]
```

| オプション | 説明 |
|---|---|
| `--id` | 取得するエンティティ ID（複数指定可） |
| `--entity` | `items` / `experiments`（--id 時は必須） |
| `--force` | ローカルをバックアップして上書き。別文書との名前衝突は拒否 |
| `--dry-run` | 取得予定を確認。設定・画像・状態ファイルも変更しない |
| `--auto` | 振り分けを自動決定 |
| `--dir` | 保存先ディレクトリを上書き |

**pull 時の特別動作:**
- eLabFTW 記事 URL → ローカルリンクに逆変換
- タイトル変更によるファイルリネーム

## init

```bash
esync init [--config PATH]
```

対話的に `.elab-sync.yaml` を生成する。

**質問項目:**
1. eLabFTW の URL
2. SSL 証明書検証の有無
3. Markdown ファイルディレクトリ
4. ファイルパターン
5. 送信先（items / experiments）
6. 送信形式（md / html）

> **注:** merge モードは廃止済み。mode は `each` 固定で設定される。

## update

```bash
esync update
```

ツール自体を最新版に更新する（`uv tool install --force`）。

**update 後の自動チェック:**
- PATH 上の `esync` が `.venv` 内のものでないかを確認
- `.venv` 版が優先されている場合は警告と解決方法を表示

## diff

```bash
esync diff [-t TARGET]
```

mapping に登録済みの全ファイルについて、ローカルとリモートの unified diff を表示。

## status

```bash
esync status [-t TARGET]
```

各ファイルの送信待ち・取得待ち・競合・最新・未追跡・基準情報なし・削除・確認失敗を表示します。リモートにも接続して確認します。未完了の同期と作成結果不明も区別します。

## clone

```bash
esync clone --url URL --entity TYPE --id ID [--dir DIR] [--no-verify]
```

リモートの eLabFTW エンティティからローカルプロジェクトを構築する。
`.elab-sync.yaml` とディレクトリ構造を自動生成。

## グローバルオプション

| オプション | 説明 |
|---|---|
| `--config PATH` | 設定ファイルパス（デフォルト: `.elab-sync.yaml`） |
| `--version`, `-V` | バージョン表示 |

## rm — 追跡解除

```bash
esync rm docs/note.md
esync rm docs/a.md docs/b.md
esync rm --id 42 --entity items
esync rm --id 42 --id 43 --entity resources --target "T"
esync rm docs/note.md --local
esync rm --id 42 --entity experiments --local --dry-run
```

指定文書の ID の紐付けと同期ハッシュを削除し、以後の push・status の対象から継続的に除外します。通常の pull も解除した ID を取得しなくなります。リモートのデータは保持します。

ローカルファイルは既定で保持し、`--local` 指定時だけ対象の Markdown ファイルを削除します。画像・添付ファイルは保持します。`--dry-run` は追跡解除と削除の予定を表示し、ファイルを変更しません。

ファイルパスはカレントディレクトリ基準（絶対パスも可）です。ID 指定には `--entity` が必須で、`resources` は `items` と同じ意味です。複数ターゲットに一致する場合は `--target` で絞り込んでください。未追跡の指定を含む場合は変更せずエラーになります。ローカルファイルが既に消えていても、残っている追跡情報から解除できます。

除外するファイル名は `id_file` の親ディレクトリの `excluded.json` に保存します。同名ファイルを再作成しても除外は続きます。`esync link <ID> --file <ファイル名> --target <ターゲット>` で既存記事との紐付けと追跡を再開できます。対応記事が存在しないと確認済みの場合は `esync link --new --file <ファイル名>` を使います。明示的な `pull --id` だけでは除外を解除しません。

他文書から解除対象への相対リンク（例: `[note](note.md)`）は、対応表の削除後はリモート URL に変換されません。参照元を次に push する前に、保持された eLabFTW 文書の URL に書き換えてください。`rm` は実行時と dry-run 時にこの移行方法を表示します。

## mv / backup / restore / link

```bash
esync mv docs/old.md docs/new.md --dry-run
esync mv docs/old.md docs/new.md
esync backup list
esync restore <バックアップID> --dry-run
esync restore <バックアップID>
esync link 42 --file note.md --target docs --dry-run
esync link 42 --file note.md --target docs
esync link --new --file note.md --target docs
```

`mv` は同じターゲット内で文書と紐付けを移動します。リモートタイトルは次のpushで更新します。`link --file` は対象docs_dirからの相対パス、`mv` と `rm` はカレントディレクトリ基準です。`--target` は設定の `title` または `docs_dir` で指定できます。

`restore` はバックアップに記録されたディレクトリ全体を復元し、復元直前もバックアップします。強制push前のリモート退避データはJSONで取り出します。リモート自体への復元は行いません。

詳細・制約は [移行と復旧](13_MIGRATION_V1.md) を参照してください。

## 終了コード

同期系コマンドは成功・変更なしで0、競合・通信失敗・部分失敗で1、設定や引数の不正で2を返します。push/pullの出力には成功・スキップ・失敗件数を表示します。

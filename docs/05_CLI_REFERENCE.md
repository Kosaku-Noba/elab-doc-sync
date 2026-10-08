# CLI リファレンス

→ [設定ファイル](04_CONFIGURATION.md) | [API リファレンス](06_API_REFERENCE.md)

## コマンド一覧

| コマンド | 説明 |
|---|---|
| `esync` | ローカル → eLabFTW に同期（push） |
| `esync push <ファイルパス>` | 指定した文書だけ push（ディレクトリ・glob・`--regex` も可） |
| `esync pull` | eLabFTW → ローカルに取得 |
| `esync pull --id 42 --entity items` | 指定 ID のリソースを取得 |
| `esync diff [ファイルパス]` | 前回の同期からのローカルと eLabFTW の変更を文書ごとに表示 |
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
esync push [ファイル・ディレクトリ・glob ...] [--regex 式] [--dry-run] [--force] [-t TARGET] [--prune-attachments]
```

| オプション | 説明 |
|---|---|
| `ファイル・ディレクトリ・glob` | 指定した文書だけを push（`esync push` のみ。カレントディレクトリ基準、複数指定可） |
| `--regex` | ファイル名に部分一致する文書だけを push（`esync push` のみ。複数指定可） |
| `--dry-run` | 実際に送信せず変更予定を表示 |
| `--force` | リモート本文を退避して強制送信。接続・取得エラーは無視しない |
| `-t`, `--target` | 特定ターゲットのみ実行 |
| `--prune-attachments` | リモートの不要添付を削除 |

**一部の文書だけ push する:**

```bash
esync push docs/note.md                    # 1 文書だけ
esync push docs/a.md docs/b.md             # 複数指定
esync push docs/subdir                     # 配下の文書を再帰的に選択
esync push 'docs/note*.md'                 # esync 側で glob を解釈
esync push --regex '^2026-'                # ファイル名に正規表現で一致
esync push docs/note.md --dry-run          # 対象と変更有無を確認
```

指定の解釈は `esync rm` と同じです。ディレクトリ、またはディレクトリに一致した glob は配下の文書を再帰的に選択します。パスの glob は `*`、`?`、`[]` に対応します。`--regex` は拡張子を含むファイル名だけに部分一致します。複数の指定は和集合として扱います。選べるのは設定したターゲットの `docs_dir` と `pattern` に一致する文書で、`--target` を付けるとそのターゲットに限ります。

- 未追跡の文書を指定すると、通常の push と同じく eLabFTW に新規作成します
- `esync rm` で除外した文書をファイル名で指定するとエラーになります。ディレクトリ・glob・`--regex` で選んだ場合は除外した文書を飛ばします
- いずれかの指定に一致する文書がない場合や正規表現が不正な場合は、何も送信せずにエラー（終了コード 2）になります
- 指定しなかった文書は確認も送信もしません。変更は次回の push まで残ります
- リネームの自動検出は、指定しなかった文書も含めてターゲット全体で行います

**push 処理フロー:**
1. 本文ハッシュが一致する一意なリネームを検出し、紐付けを更新（タイトル送信は競合確認後）
2. パス1: 対象の全ファイル（文書を指定した場合はその文書だけ）の ID を確定（新規作成含む）
3. パス2: リンク変換 + body 送信
   - 画像 → 動画 → ファイルリンク → ローカルリンク変換
4. タグ・カテゴリ・添付を同期し、同期の基準情報を保存
   - 同じファイル名で中身が変わった画像・動画・ファイルリンクは、新しい版をアップロードします。古い版の添付は、文書ごとに本文・タグ・カテゴリ・添付の同期が済んだあとで削除を試みます。`--prune-attachments` を付けなくても削除します
   - 削除するのは、差し替えた古い版のうち、現在の本文から参照されていないもの（`long_name` または `/uploads/{id}` で判定）だけです。削除に失敗した場合は警告を出して古い版を残します。その文書の同期が途中で失敗した場合も削除しません。ただし、push 全体の成功を待つわけではないため、別の文書の失敗では取り消されません
   - 削除した添付は、esync のバックアップ（本文の退避）からは復元できません
   - 本文の更新後に失敗した場合は未完了の同期として記録し、次の push で続きから再開します。eLabFTW が保存時に本文を書き換えても（例: 行頭の `>` を `&gt;` にする）、PATCH 直後に保存された本文も記録しているため再開できます。再開できない場合は、記録と異なる項目（本文・タグ・添付など）を表示します

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
- 両側が変更した文書（状態「競合」）は、前回の同期時点の本文を基準に 3-way マージする。両側が同じ箇所を変えた場合は `<<<<<<< ローカル` / `=======` / `>>>>>>> eLabFTW #ID` のマーカーで両方を残し、終了コード 1 で文書の一覧を表示する。マーカーが残っている文書は push しない（`push --force` でも同じ）。通常の pull もその文書を飛ばし、`pull --force` はマーカーごと eLabFTW の内容で上書きする。基準の本文がない文書（このバージョンより前に同期した文書）は、差のある箇所をすべてマーカーで示す。既にあるローカルの画像・添付ファイルは上書きしない。`--dry-run` では「マージ予定」と表示する。`--force` 指定時はマージせずに上書きする
- eLabFTW 記事 URL → ローカルリンクに逆変換（他ターゲットの文書へのリンクを含む。リンク先がこの PC で置かれている場所への相対パス）
- 1件以上取得したあと、取得済みでローカル未編集の文書に残る記事 URL のうち、追跡中の文書を指すものをローカルリンクに更新する。`--id` や `-t` で指定した文書に限らず、設定にある全ターゲットの文書が対象。変更前の内容はバックアップされる。`--dry-run` と `--dir` 指定時は行わない
- タイトル変更によるファイルリネーム
- タイトルに `/`、`\`、`:`、`?`、`*`、`<`、`>`、`"`、`|`、NULがある場合は取得を拒否します。`--force`でも回避できないため、eLabFTW側でタイトルを修正してください。

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
esync diff [ファイル・ディレクトリ・glob ...] [--regex 式] [-t TARGET]
```

追跡中の文書ごとに、見出し（`━━ docs/a.md（items #42）━━`）と状態を表示し、前回の同期からの変更を次の 2 つに分けて表示します。文書の指定方法は `esync push` と同じです（省略時は全文書）。

- **ローカルの変更**: 前回同期した時点のローカルの本文と、現在のファイルの unified diff
- **eLabFTW 側の変更**: タイトル・本文形式・カテゴリ・タグ・添付の追加・削除・変更と、前回同期時の eLabFTW の本文と現在の本文の unified diff

本文に差がなくても、画像・添付ファイルや設定（タグ・カテゴリ・本文形式）が変わっていれば、その旨を表示します。

pull でマージした文書では、「ローカルの変更」にマージで取り込んだ eLabFTW 側の変更も含まれます（push するまでは未送信の変更のため）。

どちらも前回の同期時点と比べるため、eLabFTW が保存時に本文を書き換えた分（箇条書きの記号、`>` のエスケープなど）や、esync の変換による差（画像のパスなど）は差分に出ません。

このバージョンより前に同期した文書は、前回同期時のローカルの本文が記録されていないため、ローカルと eLabFTW の本文を直接比較します（その旨を表示します）。この場合は eLabFTW による書き換えも差分に出ます。実際に同期した時点（変更があって push した、または pull で取得した時点）から記録します。変更がなくスキップされた push では記録されません。

指定した文書が未追跡の場合は「push で新規作成されます」と表示します。一致する文書がない指定や不正な正規表現は終了コード 2 です。

## status

```bash
esync status [-t TARGET]
```

各ファイルの送信待ち・取得待ち・競合・最新・未追跡・基準情報なし・削除・確認失敗を表示します。リモートにも接続して確認します。未完了の同期と作成結果不明も区別します。「競合」「取得待ち」のときは、eLabFTW 側で変わった項目（本文・タイトル・カテゴリ・タグ・添付など）を併記します。

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
esync rm elab_doc/elab*                      # ワイルドカードで複数選択
esync rm 'docs/*' --local --dry-run          # 一致するディレクトリ配下も含めて予定を確認
esync rm 'docs/note*.md'                     # esync 側で glob を解釈
esync rm docs/subdir                        # 配下の追跡文書を再帰的に選択
esync rm --regex '^note.*\.md$'              # ファイル名に正規表現で一致
esync rm docs/note.md
esync rm docs/a.md docs/b.md
esync rm --id 42 --entity items
esync rm --id 42 --id 43 --entity resources --target "T"
esync rm docs/note.md --local
esync rm --id 42 --entity experiments --local --dry-run
```

指定文書の ID の紐付けと同期ハッシュを削除し、以後の push・status の対象から継続的に除外します。通常の pull も解除した ID を取得しなくなります。リモートのデータは保持します。

ローカルファイルは既定で保持し、`--local` 指定時だけ対象の Markdown ファイルを削除します。画像・添付ファイルは保持します。`--dry-run` は追跡解除と削除の予定を表示し、ファイルを変更しません。

ディレクトリ指定は配下の追跡済み・除外済み文書を再帰的に選択し、未追跡ファイルやディレクトリ自体は削除しません。glob がディレクトリに一致した場合も、その配下の追跡文書を再帰的に選択します。例えば `esync rm 'docs/*' --local` は直下だけでなく一致したサブディレクトリ内の文書も削除対象になるため、`--dry-run` で対象を確認できます。パスの glob は `*`、`?`、`[]` に対応します。引用符なしの glob はシェルで展開されるため、未追跡ファイルも展開された場合はエラーになります。引用符で囲むと esync が追跡情報から選択します。`--regex` は拡張子を含むファイル名だけに部分一致し、ディレクトリ名には一致しません。複数のパス・glob・`--regex`・ID は和集合として扱い、重複は一度だけ処理します。各指定で一致がない場合や正規表現が不正な場合は変更せずエラーになります。

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

同期系コマンドは成功・変更なしで0、競合・通信失敗・部分失敗で1、設定や引数の不正（`push` の文書指定に一致する文書がない場合を含む）で2を返します。push/pullの出力には成功・スキップ・失敗件数を表示します。

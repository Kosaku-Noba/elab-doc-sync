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
| `esync relate list/add/remove` | 実験ノート・リソース間のリンク操作 |
| `esync metadata get/set` | メタデータ操作 |
| `esync entity-status show/set` | エンティティステータス操作 |
| `esync list` | リモートのリソース/実験ノート一覧 |
| `esync link <ID>` | 手動紐付け（`--new` で新規追跡を再開） |
| `esync rm <ファイルパス>` | 追跡解除（`--local` でローカルファイルも削除） |
| `esync mv <旧パス> <新パス>` | 文書と紐付けを移動 |
| `esync backup list` | ローカルバックアップ一覧 |
| `esync restore <ID>` | ローカル復元・リモート退避データの取り出し |
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
2. 設定のカテゴリ名をターゲットごとに 1 回 ID に解決（解決できなければ、カテゴリの設定が必要な文書だけ eLabFTW を変更せずにスキップ）
3. パス1: 対象の全ファイル（文書を指定した場合はその文書だけ）の ID を確定（新規作成含む）
4. パス2: リンク変換 + body 送信
   - 画像 → 動画 → ファイルリンク → ローカルリンク変換
5. タグ・カテゴリ・`links` のリンク・添付を同期し、同期の基準情報を保存
   - 同じファイル名で中身が変わった画像・動画・ファイルリンクは、新しい版をアップロードします。古い版の添付は、文書ごとに本文・タグ・カテゴリ・添付の同期が済んだあとで削除を試みます。`--prune-attachments` を付けなくても削除します
   - 削除するのは、差し替えた古い版のうち、現在の本文から参照されていないもの（`long_name` または `/uploads/{id}` で判定）だけです。削除に失敗した場合は警告を出して古い版を残します。その文書の同期が途中で失敗した場合も削除しません。ただし、push 全体の成功を待つわけではないため、別の文書の失敗では取り消されません
   - 削除した添付は、esync のバックアップ（本文の退避）からは復元できません
   - 本文の更新後に失敗した場合は未完了の同期として記録し、次の push で続きから再開します。eLabFTW が保存時に本文を書き換えても（例: 行頭の `>` を `&gt;` にする）、PATCH 直後に保存された本文も記録しているため再開できます。再開できない場合は、記録と異なる項目（本文・タグ・添付など）を表示します
   - `body_format: md` で、eLabFTW が本文の `<…>`（`array<string>` の `<string>` など）を HTML タグとみなして削除した場合は、削除された部分を警告し、終了コード 1 で終わります。eLabFTW 側の更新とタグ・カテゴリ・添付の同期は完了しています（未完了の記録は残りません）。削除された部分は pull では戻らないため、ローカルの原稿で表記を見直して再度 push してください。解消するまでその文書は「送信待ち」になり、pull しても原稿の `<…>` は上書きされません

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
- 両側が変更した文書（状態「競合」）は、前回の同期時点の本文を基準に 3-way マージする。両側が同じ箇所を変えた場合は `<<<<<<< ローカル` / `=======` / `>>>>>>> eLabFTW #ID` のマーカーで両方を残し、終了コード 1 で文書の一覧を表示する。マーカーが残っている文書は push しない（`push --force` でも同じ）。通常の pull もその文書を飛ばし、`pull --force` はマーカーごと eLabFTW の内容で上書きする。基準の本文がない文書（v1.0.4 より前に同期した文書）は、差のある箇所をすべてマーカーで示す。既にあるローカルの画像・添付ファイルは上書きしない。`--dry-run` では「マージ予定」と表示する。`--force` 指定時はマージせずに上書きする
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

v1.0.4 より前に同期した文書は、前回同期時のローカルの本文が記録されていないため、ローカルと eLabFTW の本文を直接比較します（その旨を表示します）。この場合は eLabFTW による書き換えも差分に出ます。実際に同期した時点（変更があって push した、または pull で取得した時点）から記録します。変更がなくスキップされた push では記録されません。

指定した文書が未追跡の場合は「push で新規作成されます」と表示します。一致する文書がない指定や不正な正規表現は終了コード 2 です。

## status

文書ごとに状態を表示し、続けて次に実行できるコマンドを `→` で表示します。例:

```text
  [a.md] 競合（#42）
    → 両方の変更をマージ: esync pull（同じ箇所の変更はマーカーで残る）
    → ローカルを採用（eLabFTW を上書き）: esync push --force docs/a.md
    → eLabFTW を採用（ローカルを上書き）: esync pull --id 42 --entity items --force
  [b.md] リモート削除（#43）
    → 追跡をやめる（ローカルの文書は残る）: esync rm docs/b.md
    → eLabFTW に作り直す: esync rm docs/b.md → esync link --new --file b.md → esync push docs/b.md
```

`diff` の各文書と、push で送信しなかった文書にも同じ案内を表示します。案内はプロジェクトのルート（`.elab-sync.yaml` のあるディレクトリ）で実行する前提で、`push`・`rm` のパスはルートからの相対パス、`link --file` は `docs_dir` からの相対パスです。空白や記号を含むパスは単一引用符で囲みます（macOS・Linux のシェルと Windows の PowerShell 向け。cmd.exe には対応していません）。設定にターゲットが複数ある場合、`link`・`pull --id`・`rm --id` の案内には `--target` も付けます。引数のない `esync pull`（「取得待ち」「競合」の案内）は、ターゲットを限定せずに全文書を対象にします。

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

`ELABFTW_API_KEY` 環境変数が必須です。`--entity` の既定は `items`、`--id` は複数指定できます。`--dir` を省略すると `elab-clone-<最初のID>` を作成します。生成する `.gitignore` には `.elab-sync.yaml`・`.elab-sync-ids/`・`.elab-sync-backups/`・`.elab-sync-operations/`・`.elab-sync-recovery.json` を含みます。

## グローバルオプション

サブコマンドの直後（`tag` などは下位の `add` などの前）に書きます（`update`・`whoami` を除く）。サブコマンドを省略した push では `esync` の直後に書きます。`esync -t X push` のようにサブコマンドより前に書くと無視されるので注意してください。各コマンドで意味を持つものだけが効きます。

- `--dry-run` に対応するのは push・pull・`clone`・`rm`・`mv`・`link`・`restore` です（`status`・`diff` などの読み取りコマンドでは効果がありません）。`init`・`new`・`profile add/remove`・`tag add/remove`・`relate add/remove`・`metadata set`・`entity-status set`・`category set` に付けると、何もせずエラー（終了コード 2）になります
- `--force`・`--prune-attachments` は push・pull（`new` の `--force` は上書き）で使います
- `--version` は `esync --version` の形でだけ使えます

| オプション | 説明 |
|---|---|
| `--config`, `-c PATH` | 設定ファイルパス（デフォルト: `.elab-sync.yaml`）。プロジェクトのルートはこのファイルのあるディレクトリ |
| `--target`, `-t NAME` | 対象ターゲット（`title` または `docs_dir`）。省略時は全ターゲット |
| `--force`, `-f` | push: 変更がなくても強制送信 / pull: 既存ファイルを上書き |
| `--dry-run`, `-n` | 実行せずに内容を確認 |
| `--prune-attachments` | ローカルに存在しないリモート添付を削除 |
| `--version`, `-V` | バージョン表示（`esync -V` のみ） |

`esync -h`、`esync <コマンド> -h` で各コマンドのヘルプを表示します。

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

## relate — 実験ノート・リソース間のリンク

```bash
esync relate list --id 42 --entity items
esync relate add 12 15 --to experiments --id 42 --entity items
esync relate remove 15 --to experiments --id 42 --entity items
esync relate -t "実験メモ" add 42 --to resources     # ターゲットの同期済み全文書から #42 へ
esync relate add "SPECIFICATION/F-Labo システム総合詳細仕様書.md" --from exp/2026-10-20.md   # 文書から文書へ
esync relate list --from exp/2026-10-20.md
```

| 引数・オプション | 説明 |
|---|---|
| `<リンク先>...` | リンク先（`add` / `remove`、複数指定可）。数字は ID、それ以外は同期済みの文書のパス・ディレクトリ・glob（push と同じ解釈。種別はターゲットの `entity` で決まる）。混在可 |
| `--to` | ID で指定したリンク先の種別 `experiments` / `items` / `resources`。ID を含む場合は必須。パスと併用した場合、パスの文書の種別とも一致が必要 |
| `--from <パス>...` | リンク元の同期済み文書（パス・ディレクトリ・glob、複数指定可）。`--from a.md b.md` のように続けて書ける（シェルが展開した glob も可）ため、リンク先は `--from` より前に書く。`-t` 指定時はそのターゲットの文書から選ぶ。`--id` とは併用不可 |
| `--id` / `--entity` | リンク元。両方指定するか両方省略する |
| `-t`, `--target` | 対象ターゲット（`title` または `docs_dir`）。`relate` の直後、`add` などの前に書く |

`--from` を指定すると、リンク元はそれに一致する文書だけです。`--from` も `--id` / `--entity` も省略すると、全ターゲット（`-t` 指定時はそのターゲット）の同期済みの全文書が対象になります。各ターゲットの接続プロファイルで送信します。`--id` 指定時の接続先は `-t` で選んだターゲットのプロファイル、`-t` を省略すると default です。`--id` 指定時に `-t` に一致するターゲットがない場合は、何も送信せずエラー（終了コード 2）になります。`--from` も `--id` も省略した場合に `-t` に一致するターゲットがないときは、対象の文書がないため何もせず終了します（終了コード 0）。`--from` 指定時は、`-t` の対象内に一致する文書がなければエラー（終了コード 2）です。

パスはカレントディレクトリからの相対パスです。一致する同期済みの文書がない指定（push 前の文書を含む）、`--to` と種別が合わない文書、リンク元と別サーバー（ベース URL が異なる）のターゲットにあるリンク先の文書、同期後に接続先や種別（`entity`）を変えた文書があれば、何も送信せずエラー（終了コード 2）になります。最後の場合は pull でも直らないため、現在の接続先で正しい ID を確認し、`esync link <ID> --file <ファイル名> --target <ターゲット>` で紐付け直してください。ID が変わる場合は、先に `esync rm <ファイル>` で既存の紐付けを解除します。

既にあるリンクの追加・ないリンクの削除・文書自身へのリンクは、その旨を表示して飛ばします。`remove` はリンクだけを外し、リンク先の記事は削除しません。`add` / `remove` は `--dry-run` に対応していません。push 時に自動でリンクを張る設定は [設定ファイル仕様](04_CONFIGURATION.md) の `links` を参照してください。

## tag — タグ操作

```bash
esync tag list                                   # 同期済みの全文書のタグ
esync tag add "重要"                             # 同期済みの全文書にタグを追加
esync tag remove "下書き"
esync tag -t "週報" add "2026"                   # ターゲットを限定
esync tag add "重要" --id 42 --entity items      # 記事を直接指定
esync tag -t shared_docs/ add "共同" --id 42 --entity items   # 別プロファイルのターゲットの記事
```

`--id` と `--entity` は両方指定するか両方省略します。省略時は各ターゲットの同期済み文書が対象で、各ターゲットの接続プロファイルで送信します。`--id` 指定時は `-t` で選んだターゲットのプロファイル（`-t` 省略時は default）を使い、`-t` に一致するターゲットがなければ何も送信せずエラー（終了コード 2）になります。`remove` は名前が一致するタグを外します。push 時のタグ同期は追記のみのため、設定から外したタグは `tag remove` で外します。

## category — カテゴリ操作

```bash
esync category list --entity items
esync category show --id 42 --entity items
esync category set "試薬" --id 42 --entity items
esync category set 7 --id 42 --entity experiments
```

`list` の `--entity` を省略するとリソース（items）のカテゴリを表示します。読み取り権限のないカテゴリは一覧に表示されません（記事のカテゴリは `show` で確認できます）。`set` には名前または数字の ID を指定できます。記事のカテゴリが既に目的の値なら、変更せず成功として扱います。default の接続先を使います。

## metadata — メタデータ操作

```bash
esync metadata get
esync metadata -t "週報" set key1=value1 key2=value2 --id 42
```

`--id` を省略すると、各ターゲット（`-t` で限定可）の同期済みの全文書が対象です。`--id` は `--entity` を取らず、対象の各ターゲットの `entity` の記事として扱います。`-t` を省略すると、全ターゲットそれぞれの種別の #42（items と experiments のターゲットがあれば両方）を変更するため、`-t` でターゲットを 1 つに絞ってください（`-t` は `set` などの前に書く）。`set` は既存のメタデータ（JSON）に `key=value` を追記・上書きします。既存のメタデータが読めない場合は警告を出して上書きします。default の接続先を使います。

## entity-status — ステータス操作

```bash
esync entity-status show
esync entity-status -t "週報" set 2 --id 42
esync entity-status set 2          # 複数件なら確認プロンプト
```

ステータスはチーム設定の ID で指定します（名前は不可）。`--id` を省略して複数の文書が対象になる場合は、確認してから変更します。`--id` の扱いは `metadata` と同じで、`-t` を省略すると全ターゲットそれぞれの種別の同じ ID を確認なしで変更します。default の接続先を使います。

## list — リモート一覧

```bash
esync list                         # リソース 20 件
esync list --entity experiments --limit 100
```

`--entity` は `items`（既定）/ `experiments` / `resources`。サーバー側の表示件数に制限される場合があります。default の接続先を使います。

## verify — 整合性チェック

```bash
esync verify [-t TARGET]
```

紐付けごとに、ローカルファイルの存在とリモート記事の取得可否を確認します。問題があれば `⚠` で表示します。default の接続先を使います。

## profile — 接続プロファイル

```bash
esync profile list
esync profile add team-b --url https://elab.example.com --api-key KEY [--no-verify]
esync profile remove team-b
```

`.elab-sync.yaml` の `profiles` セクションを編集します。`list` は URL・API キーの有無（✓/✗）・SSL 検証の有無を表示し、キー自体は表示しません。`elabftw` セクションは `default` として表示します。

## whoami — ユーザー情報

```bash
esync whoami
```

プロファイルごとに、API キーに紐づくユーザー名・メール・ユーザー ID・現在のチームを表示します。接続確認にも使えます。

## new — テンプレートから文書作成

```bash
esync new --list
esync new --template-id 3 [--title "名前"] [-o path/to/file.md] [-t "ターゲット名"] [--force]
```

eLabFTW の実験テンプレート（`experiments_templates`）の本文を Markdown に変換して保存します。`-o` を省略すると、`-t` の `title` に一致するターゲット（なければ最初のターゲット）の `docs_dir` にタイトル名のファイルを作ります。既存ファイルは `--force` なしでは上書きしません。

## log — 同期ログ

```bash
esync log [--limit 50]
```

`.elab-sync-ids/sync-log.jsonl` に記録した push・pull の履歴のうち、最新の N 件（既定 20 件）を古い順に表示します。

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

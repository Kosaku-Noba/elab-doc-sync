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
| `esync search` | 作成者・日付・タグ・カテゴリなどで検索（`--json` で機械可読） |
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
esync push [ファイル・ディレクトリ・glob ...] [--regex 式] [--dry-run] [--force] [-t TARGET] [--prune-attachments] [--expect-id ID]
```

| オプション | 説明 |
|---|---|
| `ファイル・ディレクトリ・glob` | 指定した文書だけを push（`esync push` のみ。カレントディレクトリ基準、複数指定可） |
| `--regex` | ファイル名に部分一致する文書だけを push（`esync push` のみ。複数指定可） |
| `--dry-run` | 実際に送信せず変更予定を表示 |
| `--force` | リモート本文を退避して強制送信。接続・取得エラーは無視しない |
| `--expect-id`・`--expect-server`・`--expect-entity` | 書き換える直前に、指定した1文書の紐付けが確認時の記事（ID・認証情報を除いた接続先 URL・種別）と同じかを照合する。異なれば何も送信せず終了コード 2。記事を照合する場合は `--expect-id` が必須で、`--expect-server`・`--expect-entity` は省略できる（省略したものは照合しない。照合しない通常の push では3つとも指定しない）。`--expect-id` なしで `--expect-server`・`--expect-entity` を指定すると、何もせず終了コード 2。`--expect-server` には `diff --json` が返す、認証情報を除いた `server` を渡す。照合の条件は push・pull・mv で共通。`--force` と併用できる（VS Code 拡張が上書きの前に使う）。文書の選択結果が1つのターゲットの1文書でなければ終了コード 2。同じファイルが複数のターゲットに一致する場合は、`diff --json` の `selector` を `--target` に指定して絞る（例: `esync push --force --target notes --expect-id 42 --expect-server https://elab.example.com --expect-entity items -- docs/a.md`） |
| `-t`, `--target` | 特定ターゲットのみ実行 |
| `--prune-attachments` | attachments_dir が存在する場合、attachments_pattern に一致し、同名のローカル添付も本文からの参照もない非画像添付を削除 |

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
   - 画像・動画・ファイルリンクの添付を先に送信・照合し、文書間リンクも変換してから本文を更新
5. タグ・カテゴリ・`links` を同期し、旧版や明示的な削除候補を整理して同期の基準情報を保存
   - 同じファイル名で中身が変わった画像・動画・ファイルリンクは、新しい版をアップロードします。古い版の添付は、文書ごとに本文・タグ・カテゴリ・添付の同期が済んだあとで削除を試みます。`--prune-attachments` を付けなくても削除します
   - 削除するのは、差し替えた古い版のうち、現在の本文から参照されていないもの（`long_name` または `/uploads/{id}` で判定）だけです。差し替え前の本文で参照していた添付、または中断前の push が新規作成したことを確認できた添付が対象です。削除に失敗した場合は警告を出して古い版を残します。その文書の同期が途中で失敗した場合も削除しません。ただし、push 全体の成功を待つわけではないため、別の文書の失敗では取り消されません
   - 削除した添付は、esync のバックアップ（本文の退避）からは復元できません
   - 本文の更新後に失敗した場合は未完了の同期として記録し、次の push で続きから再開します。eLabFTW が保存時に本文を書き換えても（例: 行頭の `>` を `&gt;` にする）、PATCH 直後に保存された本文も記録しているため再開できます。再開できない場合は、記録と異なる項目（本文・タグ・添付など）を表示します
   - `body_format: md` で、eLabFTW が本文の `<…>`（`array<string>` の `<string>` など）を HTML タグとみなして削除した場合は、削除された部分を警告し、終了コード 1 で終わります。eLabFTW 側の更新とタグ・カテゴリ・添付の同期は完了しています（未完了の記録は残りません）。削除された部分は pull では戻らないため、ローカルの原稿で表記を見直して再度 push してください。解消するまでその文書は「送信待ち」になり、pull しても原稿の `<…>` は上書きされません

## pull

```bash
esync pull [--id ID] [--entity TYPE] [--dry-run] [--force] [--auto] [--dir DIR] [-t TARGET] [--json]
esync pull [ファイル・ディレクトリ・glob ...] [--regex 式] [-t TARGET] [--dry-run] [--force] [--json] [--expect-id ID]
```

| オプション | 説明 |
|---|---|
| `--id` | 取得するエンティティ ID（複数指定可） |
| `--entity` | `items` / `experiments`（--id 時は必須） |
| `--force` | ローカルをバックアップして上書き。別文書との名前衝突は拒否 |
| `--dry-run` | 取得予定を確認。本文が参照する画像と非画像添付の保存先を照合し、設定・画像・状態ファイルも変更しない |
| `--auto` | 振り分けを自動決定 |
| ファイル・`--regex` | 取り込む追跡中の文書を push・diff と同じ方法で指定する（省略時は全文書）。`--id`・`--dir` とは併用できない（終了コード 2）。指定した文書がまだ記事と紐付いていない場合は取得せず、`result: "untracked"` を返す。改名した文書は旧名で紐付いているので、先に `esync mv <旧パス> <新パス>` で紐付けを移す |
| `--expect-id`・`--expect-server`・`--expect-entity` | push と同じ照合を、取り込む前に行う。文書を指定し、選択結果が1つのターゲットの1文書のときだけ使える。異なれば何も変更せず終了コード 2 |
| `--json` | 結果を JSON で出力する。`documents` の要素は `result` ごとに次のキーを持つ。`pulled`・`would_pull`・`skipped`: `target`・`entity`・`entity_id`・`server`（認証情報を除いた URL）・`conflict`（今回競合マーカーを残したか）・`path`（本文の保存先。取得する場合はタイトルの変更による改名後の名前で、dry-run でも同じ。ローカルの編集を残してスキップした場合は、今の本文の場所）。`untracked`: `target`・`entity`・`path`。`needs_target`: `entity`・`entity_id`。取得に失敗した記事は `result` の代わりに `error` を持ち、`path` はない。記事の取得に失敗したときの `error` と標準エラーでは、URL に含まれるユーザー名・パスワードを `https://***@elab.example.com:8443/...` のように伏せる。`--expect-server` が一致しないときのエラーには、指定した値を表示しない。ほかに `pulled`・`skipped`・`failed`・`conflict_files`。保存先は対話で選ばない。警告は標準エラーに出る。引数や文書の指定の誤りは終了コード 2 で、標準エラーに理由を出す |
| `--dir` | 保存先ディレクトリを指定。既存ターゲットの管理下なら取得元と種別・接続設定（URL、API キー、SSL 検証）が一致する必要がある。`--target` 省略時も照合する。ID を省略した一括取得では、選択したターゲットに不一致があれば全件の取得前に中止する。対象を限定するには `--target` を指定する |

**保存先が重なる場合**

- 本文・画像・添付の実際の保存先が別接続先の管理領域や別の追跡文書なら、`--force` でもその記事の取得は失敗します。同じ記事でも、画像・添付でその記事の追跡済み本文を上書きすることはできません。初回取得で本文と添付がともに `docs/new.md` になる場合や、本文を添付の親ディレクトリとして使う場合も同様です。
- 親ターゲットのパターンが `**/*.md` で `docs/note.md` があるとき、子に `docs/sub/note.md` を追加すると追跡名が重複します。未追跡の文書や今回作る予定の添付も照合します。子の保存先を親のパターンの対象外にしてください。改名で空いた本文の名前は後続記事に使えます。本実行でその間にエディタなどが同じ場所へ保存した場合、そのファイルを保持して後続記事をエラーにします。初回取得や改名先でも、空いていた保存先に新しく作成された本文を保持します。既存本文の置換や改名では、その時点の実ファイルを退避して取得開始時の版と照合します。食い違えば記事の紐付けを保持して停止します。本文の退避後に同名ファイルが作られた場合も上書きしません。本文の保存や、改名で空いたパスの再利用、状態ファイルのない添付ディレクトリへの新規保存にはハードリンクを使うため、非対応のファイルシステムでは該当記事の取得が失敗します。
- 添付名は全 OS で大文字・小文字を区別せず照合します。異なるアップロードが同じ保存先を使うときは、eLabFTW 側で名前を分けてください。同じ記事の同名画像は、本文の保存ディレクトリを変えても同じ `images/` 内で衝突します。
- 記事 #7 の `table.csv` が同期記録にあると、`--id 8` だけを指定しても #8 の別の添付で上書きすることはできません。添付ディレクトリを削除した後も照合します。複数記事に push 済みの同じ非画像添付は、手元の内容と取得元の SHA-256 が一致するときに再利用できます。`attachments_dir` を指定し、同じ記事の異なる添付 ID がどちらも `report.csv` に保存される場合は、内容が同じでもその記事の取得は失敗します。
- 新規記事同士の衝突では、先に取得した記事を保持し、後から衝突した記事をエラーにします。同期記録が破損して所有者を確認できない添付ディレクトリは保護し、独立した保存先の処理を続けます。記録に添付一覧自体がない場合も所有者不明として扱います。状態ファイル自体がない旧形式では、そのディレクトリに既にあるファイルを保護します。読めない追跡記録の文書はリンク変換の候補から外します。一括取得では文書別の結果を確認してください。保存対象の非画像添付がない場合、添付ディレクトリは作成しません。

**pull 時の特別動作:**
- 両側が変更した文書（状態「競合」）は、前回の同期時点の本文を基準に 3-way マージする。両側が同じ箇所を変えた場合は `<<<<<<< ローカル` / `=======` / `>>>>>>> eLabFTW #ID` のマーカーで両方を残し、終了コード 1 で文書の一覧を表示する。マーカーが残っている文書は push しない（`push --force` でも同じ）。通常の pull もその文書を飛ばし、`pull --force` はマーカーごと eLabFTW の内容で上書きする。基準の本文がない文書（v1.0.4 より前に同期した文書）は、差のある箇所をすべてマーカーで示す。添付は取得先の内容が前回の SHA-256 に一致すれば新版を取得する。添付が両側で異なる内容に変わった場合や、マージ後の本文が古い添付を参照するおそれがある場合は停止する。`--dry-run` では「マージ予定」と表示する。`--force` 指定時はマージせずに上書きする
- eLabFTW 記事 URL → ローカルリンクに逆変換（他ターゲットの文書へのリンクを含む。リンク先がこの PC で置かれている場所への相対パス）
- 1件以上取得したあと、取得済みでローカル未編集の文書に残る記事 URL のうち、追跡中の文書を指すものをローカルリンクに更新する。`--id` や `-t` で指定した文書に限らず、設定にある全ターゲットの文書が対象。ただし文書（ファイル・`--regex`）を指定した場合は、指定した文書のうち実際に取得した文書だけを対象にする（スキップした文書や指定外の文書は書き換えない）。変更前の内容はバックアップされる。`--dry-run` と `--dir` 指定時は行わない
- タイトル変更によるファイルリネーム
- タイトルに `/`、`\`、`:`、`?`、`*`、`<`、`>`、`"`、`|`、NULがある場合は取得を拒否します。`--force`でも回避できないため、eLabFTW側でタイトルを修正してください。

## init

```bash
esync init [--config PATH]
```

対話的に `.elab-sync.yaml` を生成する。

**質問項目:**
1. eLabFTW の URL（前後の空白を除いてから [設定ファイル](04_CONFIGURATION.md) の `url` の条件で確かめ、不正ならもう一度尋ねます）
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
esync diff [ファイル・ディレクトリ・glob ...] [--regex 式] [-t TARGET] [--json [--bodies]]
```

追跡中の文書ごとに、見出し（`━━ docs/a.md（items #42）━━`）と状態を表示し、前回の同期からの変更を次の 2 つに分けて表示します。文書の指定方法は `esync push` と同じです（省略時は全文書）。

- **ローカルの変更**: 前回同期した時点のローカルの本文と、現在のファイルの unified diff
- **eLabFTW 側の変更**: タイトル・本文形式・カテゴリ・タグ・添付の追加・削除・変更と、前回同期時の eLabFTW の本文と現在の本文の unified diff

本文に差がなくても、画像・添付ファイルや設定（タグ・カテゴリ・本文形式）が変わっていれば、その旨を表示します。

pull でマージした文書では、「ローカルの変更」にマージで取り込んだ eLabFTW 側の変更も含まれます（push するまでは未送信の変更のため）。

どちらも前回の同期時点と比べるため、eLabFTW が保存時に本文を書き換えた分（箇条書きの記号、`>` のエスケープなど）や、esync の変換による差（画像のパスなど）は差分に出ません。

v1.0.4 より前に同期した文書は、前回同期時のローカルの本文が記録されていないため、ローカルと eLabFTW の本文を直接比較します（その旨を表示します）。この場合は eLabFTW による書き換えも差分に出ます。実際に同期した時点（変更があって push した、または pull で取得した時点）から記録します。変更がなくスキップされた push では記録されません。

指定した文書が未追跡の場合は「push で新規作成されます」と表示します。一致する文書がない指定や不正な正規表現は終了コード 2 です。

`--json` は差分と送信先を `documents` に返します。push と同じ改名判定をメモリ内で行い、改名予定の文書には旧名と既存の記事 ID を含めます。一つのファイルが複数のターゲットに一致する場合はそれぞれの結果を返します。`selector` がある場合は、その値を `--target` に指定して送信先を限定できます。

`--json` に `--bodies` を加えると、比較に使った本文も文書ごとに返します（`--bodies` だけでは何も変わりません）。

- `base_label`・`base_body`: 比較の基準とその本文。`前回の同期`（前回同期した時点のローカルの本文）、`eLabFTW`（前回の本文が記録されていない文書の、現在の eLabFTW の本文）、`新規作成`（未追跡の文書。本文は空）のいずれか
- `local_body`: 現在のファイルの本文（前後の空白を除く）
- `remote_base_body`・`remote_body`: 前回同期時と現在の eLabFTW の本文。eLabFTW 側で本文に比較可能な差がある場合だけ返します

新規文書の `base_body` は空文字列です。次の文書では `base_label`・`base_body`・`local_body` を返しません: ローカルにファイルがない文書、記事の取得に失敗した文書（`error` あり）、改名前後の対応を判定できず記事 ID を決められなかったターゲットの文書（`error` あり）。複数のターゲットに一致して `selector` が `null` の場合でも、比較できれば本文を返します。キーがない場合は、比較する本文がないことを示します。

取得成功時の終了コードは 0 で、差分の有無は `has_diff` で確認します。一部の記事を取得できない場合は終了コード 1 となり、その文書の `error` に理由が入ります。接続設定などの警告は標準エラーに出ます。

1 文書を送信する際に `esync push --expect-preview <preview_token> --target <selector> -- <ファイル>` と指定すると、push が使用する本文・参照ファイル・文書間リンクの解決結果・送信先を送信前に照合します。リモートへの書き込みを始めた後は、通常の push と同じ競合確認と再開処理を使います。

`--expect-preview` は対象が一つのターゲットの一文書に確定する通常の push で使用できます。`--dry-run`・`--force`・`--prune-attachments` と併用した場合は終了コード 2 です。照合に失敗したら差分を開き直し、新しい `preview_token` で送信します。

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
esync status [-t TARGET] [--json]
```

各ファイルの送信待ち・取得待ち・競合・最新・未追跡・基準情報なし・削除・確認失敗を表示します。リモートにも接続して確認します。未完了の同期と作成結果不明も区別します。「競合」「取得待ち」のときは、eLabFTW 側で変わった項目（本文・タイトル・カテゴリ・タグ・添付など）を併記します。

`--json` は `documents` と `recovery_pending` を出力します。各文書の `selector` は、そのターゲットを一意に指定できる `--target` の値（`title` または `docs_dir`）で、一意に指定できなければ `null` です。各文書の `path` は設定ファイル基準のパスです。プロジェクト外の文書は絶対パス、ローカルにない文書は `null` です。競合や復旧待ちなどで終了コードが 1 のときも、確認できた文書の一覧を読み取れます。

## clone

```bash
esync clone --url URL --entity TYPE --id ID [--dir DIR] [--no-verify]
```

リモートの eLabFTW エンティティからローカルプロジェクトを構築する。
`.elab-sync.yaml` とディレクトリ構造を自動生成。

`ELABFTW_API_KEY` 環境変数が必須です。`--url` が [設定ファイル](04_CONFIGURATION.md) の `url` の条件を満たさない場合は、作成先にプロジェクトのファイルを作らずに終了コード 2 で終わります（本実行では作成先のロックと復旧記録を先に確かめるので、そちらに問題があればその理由で終わります）。表示と結果の URL では認証情報を伏せます。ただし `--url` に含めたユーザー名・パスワードは、生成する `.elab-sync.yaml` の `elabftw.url` にはそのまま保存されるので、設定ファイルを共有しないでください。`.gitignore` は記事を取得した後に作るので、途中で中断した場合は、共有の前に `.elab-sync.yaml` が除外されているかを確かめてください。記事の本文にある相対リンクを絶対 URL に直す場合も、接続先 URL の認証情報は含めません。`--entity` の既定は `items`、`--id` は複数指定できます。`--dir` を省略すると `elab-clone-<最初のID>` を作成します。生成する `.gitignore` には `.elab-sync.yaml`・`.elab-sync-ids/`・`.elab-sync-backups/`・`.elab-displaced-*/`・`.elab-sync-operations/`・`.elab-sync-recovery.json` を含みます。

同名の画像・添付や文書が同じ保存先を必要とする場合は、該当記事を取得できません。`clone --dry-run` で事前に確認できます。一括取得の衝突では先の記事と添付を保持し、後から衝突した記事だけが失敗します。残りの ID の取得を続け、部分成功の終了コードは 1 です。

## グローバルオプション

`esync` の直後（`esync -t X push`）またはサブコマンドの直後（`esync push -t X`。`tag` などは下位の `add` などの前）に書きます（`update`・`whoami` を除く）。両方に書いた場合はサブコマンドの後の値が優先されます。各コマンドで意味を持つものだけが効きます。

- `--dry-run` に対応するのは push・pull・`clone`・`rm`・`mv`・`link`・`restore`・`new`・`tag add/remove`・`relate add/remove`・`metadata set`・`entity-status set`・`category set` です（`status`・`diff` などの読み取りコマンドでは効果がありません）。eLabFTW を書き換えるコマンドは現在の値（タグ・リンク・メタデータ・カテゴリ・ステータス）を読んで「追加予定」「既にあります」などの予定を表示し、送信しません。`entity-status set` は対象ごとに現在のステータスと変更先を表示し、確認の入力を求めません（ステータス ID が数値でなければ、本実行と同じくエラー）。旧形式の紐付け情報があっても移行しません。`new` はファイルを作らずに作成先を表示します。`init`・`profile add/remove` に付けると、何もせずエラー（終了コード 2）になります
- `--force` は push・pull で使います（`new` では既存ファイルの上書き）
- `--prune-attachments` は push 専用です。pull など他のコマンドに付けても無視され、添付は削除されません
- `--version` は `esync --version` の形でだけ使えます

| オプション | 説明 |
|---|---|
| `--config`, `-c PATH` | 設定ファイルパス（デフォルト: `.elab-sync.yaml`）。プロジェクトのルートはこのファイルのあるディレクトリ |
| `--target`, `-t NAME` | 対象ターゲット（`title` または `docs_dir`）。省略時は全ターゲット。`category`・`list`・`new` と、`tag`・`relate` の `--id` 指定時は接続先の選択に使い、省略時は既定の接続先 |
| `--force`, `-f` | push: 変更がなくても強制送信 / pull: 既存ファイルを上書き |
| `--dry-run`, `-n` | 実行せずに内容を確認 |
| `--prune-attachments` | attachments_dir が存在する場合、attachments_pattern に一致し、同名のローカル添付も本文からの参照もない非画像添付を削除（push のみ） |
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

ローカルファイルは既定で保持し、`--local` 指定時だけ対象の Markdown ファイルを削除します。`--local` 指定時に選択した文書にシンボリックリンクが含まれる場合は、リンク切れでも全件の追跡解除・削除を始める前に中止します。画像・添付ファイルは保持します。`--dry-run` は追跡解除と削除の予定を表示し、ファイルを変更しません。

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

既にあるリンクの追加・ないリンクの削除・文書自身へのリンクは、その旨を表示して飛ばします。`remove` はリンクだけを外し、リンク先の記事は削除しません。`add` / `remove` に `--dry-run` を付けると、既存のリンクを読んで追加・削除の予定だけを表示します。push 時に自動でリンクを張る設定は [設定ファイル仕様](04_CONFIGURATION.md) の `links` を参照してください。

## 記事操作の JSON 出力

`tag`・`relate`・`metadata` はサブコマンドの前に `--json` を指定すると処理結果を JSON で返します。例えば `esync tag --target=週報 --json list --entity=experiments --id=42` のタグ一覧は `entities[0].tags` に入ります。`status --json` や `diff --json` が返す記事の `url` を `--expect-article-url` に渡すと、指定したターゲット・種別・ID が示す URL を実行時に照合します。前回同期時の接続先が確認できない記事の結果には `url` が入りません。

`esync new --json --list-targets` は空の文書ディレクトリも含めて作成先候補を返します。一意に指定できるターゲットには `selector` が入ります。`new --json --target=<selector> --list` でテンプレートを取得し、`--template-id` と `--title` で作成すると、結果の `path` でファイルを開けます。

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

`list` の `--entity` を省略するとリソース（items）のカテゴリを表示します。読み取り権限のないカテゴリは一覧に表示されません（記事のカテゴリは `show` で確認できます）。`set` には名前または数字の ID を指定できます。記事のカテゴリが既に目的の値なら、変更せず成功として扱います。接続先は `-t` で選んだターゲットのプロファイル（`-t` 省略時は既定の接続先）で、`-t` に一致するターゲットがなければ何も送信せずエラー（終了コード 2）になります。

## metadata — メタデータ操作

```bash
esync metadata get
esync metadata -t "週報" set key1=value1 key2=value2 --id 42
```

`--id` を省略すると、各ターゲット（`-t` で限定可）の同期済みの全文書が対象です。`--id` は `--entity` を取らず、対象の各ターゲットの `entity` の記事として扱います。`-t` を省略すると、全ターゲットそれぞれの種別の #42（items と experiments のターゲットがあれば両方）を変更するため、`-t` でターゲットを 1 つに絞ってください（`-t` は `set` などの前に書く）。`set` は既存のメタデータ（JSON）に `key=value` を追記・上書きします。既存のメタデータが読めない場合は警告を出して上書きします。各ターゲットの接続プロファイルで送信します。

`--expect-article-url` を指定した更新では、既存の JSON が読めない場合やオブジェクト・配列を文字列で上書きする場合は中止します。拡張は `esync metadata --target=週報 --expect-article-url="https://elab.example.com/experiments.php?mode=view&id=42" set --id=42 --edit-stdin` に `{"key":"担当","value":"B","previous_token":"取得したトークン"}` を標準入力で渡します。`previous_token` には同じ `--target`・`--expect-article-url` を指定した `esync metadata --json … get --id=42` が返した `entities[0].fields[]` の該当キーの `token`を指定します。省略すると新しいキーを追加します。更新前に既存値を読み直し、編集開始時と異なれば中止します。メタデータ全体の再取得と更新は別の API 要求で、この2つの要求の間に他の利用者が加えた変更は検出できません。

## entity-status — ステータス操作

```bash
esync entity-status show
esync entity-status -t "週報" set 2 --id 42
esync entity-status set 2          # 複数件なら確認プロンプト
```

ステータスはチーム設定の ID で指定します（名前は不可）。`--id` を省略して複数の文書が対象になる場合は、確認してから変更します。`--id` の扱いは `metadata` と同じで、`-t` を省略すると全ターゲットそれぞれの種別の同じ ID を確認なしで変更します。各ターゲットの接続プロファイルで送信し、表示にはターゲット名（確認時は接続先 URL も）を付けます。

## list — リモート一覧

```bash
esync list                         # リソース 20 件
esync list --entity experiments --limit 100
```

`--entity` は `items`（既定）/ `experiments` / `resources`。サーバー側の表示件数に制限される場合があります。接続先は `category` と同じく `-t` で選びます。

## search — 検索

```bash
esync search [キーワード ...] [--entity all|items|experiments|resources]
  [--author 名前|me|ユーザーID] [--since 日付] [--until 日付]
  [--updated-since 日付] [--updated-until 日付] [--tag タグ ...]
  [--category 名前|ID] [--status 名前|ID] [--scope mine|team|all]
  [--order 並び順] [--sort asc|desc] [--limit 20] [--offset 0] [--json] [--body]
```

eLabFTW のブラウザの検索と同じ条件で、リソース・実験ノートを検索します。条件はすべて AND です。

| オプション | 説明 |
|---|---|
| `キーワード` | タイトル・本文・eLabID に含まれる語（複数の語は 1 つの検索語として送る） |
| `--entity` | 検索する種別。既定は `all`（リソースと実験ノートの両方） |
| `--author` | 作成者。名前は「名 姓」への部分一致、`me` は自分、数字はユーザー ID |
| `--since` / `--until` | 記事の日付（ブラウザの「日付」欄。既定は作成日）の範囲。両端を含む |
| `--updated-since` / `--updated-until` | 最終更新日の範囲。両端を含む |
| `--tag` | タグ。複数指定すると、すべてのタグを持つ記事 |
| `--category` / `--status` | 名前（完全一致、大文字小文字は区別しない）または ID。ID は種別ごとに異なるため `--entity items` か `experiments` が必要 |
| `--scope` | `mine`: 自分の記事 / `team`: 現在のチームの記事 / `all`: 読めるすべて。省略時は eLabFTW のユーザー設定 |
| `--order` / `--sort` | 並び順（`date`・`lastchange`・`title`・`id` など）と昇順・降順（既定 `desc`）。省略時は eLabFTW の設定。`all` と最終更新日の指定時は `lastchange` |
| `--limit` / `--offset` | 表示件数（既定 20）と、先頭から飛ばす件数。続きがあれば次の `--offset` を表示する（走査上限で打ち切ったときは表示しない。下の制約を参照） |
| `--json` | JSON で出力（AI エージェント・スクリプト向け） |
| `--body` | 本文も出力（pull と同じ変換をした Markdown。記事ごとに 1 回取得する）。人向けの出力は先頭 300 文字まで、`--json` では全文 |

```bash
esync search PCR                                       # キーワード
esync search --author me --updated-since 2026-11-01    # 自分が最近更新した記事
esync search --author 山田 --since 2026-04-01 --until 2026-09-30 --entity experiments
esync search --tag 週報 --tag 2026 --category "Protocol"
esync search 緩衝液 --json --body --limit 5            # エージェントに本文ごと渡す
```

人向けの出力は、記事ごとに作成者・日付・最終更新・カテゴリ・ステータス・タグを表示します。追跡中の文書にはローカルのパスを、未取得の記事には最後にまとめて `esync pull --id … --entity …` を案内します（`-t` で検索したときは同じ `-t` を付けます）。

`--json` の出力:

```json
{
  "results": [
    {
      "entity": "items", "id": 42, "title": "…", "author": "Taro Yamada", "userid": 7,
      "date": "2026-11-02", "created_at": "2026-11-02 10:00:00", "modified_at": "2026-11-05 18:12:03",
      "category": {"id": 4, "title": "Protocol"}, "status": {"id": 1, "title": "Running"},
      "tags": ["週報"], "url": "https://…/database.php?mode=view&id=42",
      "local_path": "docs/週報.md", "pull_command": null, "body": "…（--body 指定時のみ）"
    }
  ],
  "count": 1, "has_more": false, "next_offset": null, "truncated": false
}
```

`local_path` は同じ接続先のターゲットで追跡中の文書（カレントディレクトリ基準）、`pull_command` は追跡していない記事の取得コマンドです。同じ接続先とは、URL のホストとパスが一致することを指します。接続先は `list` と同じく `-t` で選びます。`truncated` は下の走査上限で打ち切ったことを示します。このとき結果が欠けている可能性があるため、他の種別に続きがあって `has_more` が `true` でも `next_offset` は `null` にします。

**制約:**

- 最終更新日は eLabFTW の検索条件にないため、esync が取得しながら絞り込みます（並び順が `lastchange` 降順なら、範囲より古い記事に達した時点で打ち切ります）。
- `--scope team` は、eLabFTW がユーザー設定によってはチームで絞らないため、esync 側でも現在のチームの記事だけに絞ります。チームを確認できない記事は含めず、現在のチームを取得できなければエラーにします。
- `--entity all` は種別ごとに取得してから並び順で統合します。固定表示（ピン留め）の記事も他の記事と同じ基準で並べます。
- **走査上限:** 最終更新日の指定・`--scope team`・`--entity all` のいずれかを使うと、esync は先頭から順に取得して数えるため、種別ごとに最大 5,000 件までしか確認しません。`--offset` が大きいときも同じです。上限に達すると「打ち切りました」と警告し（`--json` では `"truncated": true`）、条件に合う記事が結果に含まれない可能性があります。キーワード・作成者・日付・タグなどで条件を絞ってください。これらを使わない 1 種別の検索は eLabFTW の `offset` で必要な件数だけ取得するため、`--offset` や `--limit` が大きくてもこの上限はありません。

## verify — 整合性チェック

```bash
esync verify [-t TARGET]
```

紐付けごとに、ローカルファイルの存在とリモート記事の取得可否を確認します。問題があれば `⚠` で表示します。各ターゲットの接続プロファイルで確認します。

## profile — 接続プロファイル

```bash
esync profile list
esync profile add team-b --url https://elab.example.com --api-key KEY [--no-verify]
esync profile add team-c --url https://elab.example.com --api-key-env ENV_NAME [--no-verify]
esync profile remove team-b
```

`.elab-sync.yaml` の `profiles` セクションを編集します。`--api-key-env` は、キーを設定ファイルに書かず、環境変数の名前を `api_key_env` として登録します（`--api-key` とは同時に指定できません）。`list` は URL・API キーの有無（✓/✗。`api_key_env` のときは環境変数の名前と設定の有無）・SSL 検証の有無を表示し、キー自体は表示しません。`elabftw` セクションは `default` として表示します。URL に含まれるユーザー名・パスワードは伏せ、形が不正な URL は「（不正な URL）」と表示します（設定を直すプロファイルを特定できます。URL の条件は [設定ファイル](04_CONFIGURATION.md) の `url` を参照）。`add` は不正な `--url` を保存せず、終了コード 2 にします。

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

eLabFTW の実験テンプレート（`experiments_templates`）の本文を Markdown に変換して保存します。`-o` を省略すると、`-t`（`title` または `docs_dir`）に一致するターゲット（`-t` 省略時は最初のターゲット）の `docs_dir` にタイトル名のファイルを作ります。テンプレートは `category` と同じく `-t` で選んだ接続先から取得します。既存ファイルは `--force` なしでは上書きしません。

同期対象のファイルを新規作成するとき、同名の旧形式の紐付けや作成記録が残っていれば、別の記事と誤って同期することを防ぐため作成を中止します。別のファイル名を指定してください。

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

`mv` は同じターゲット内で文書と紐付けを移動します。`--expect-id`・`--expect-server`・`--expect-entity` を指定すると、移動元の紐付けが確認時の記事と異なる場合は移動せず終了コード 2 にします。リモートタイトルは次のpushで更新します。`link --file` は対象docs_dirからの相対パス、`mv` と `rm` はカレントディレクトリ基準です。`--target` は設定の `title` または `docs_dir` で指定できます。

`restore` はバックアップに記録されたディレクトリ全体を復元し、復元直前もバックアップします。強制push前のリモート退避データはJSONで取り出します。リモート自体への復元は行いません。

既存本文の置換・改名時に退避した版は `.elab-sync-backups/<取得時のバックアップID>/displaced/<旧ファイル名>` にあります。競合時は表示されたパスを確認してください。通常の restore は、その記事のローカル更新直前のスナップショットを使います。別マウントでは `displaced/<旧ファイル名>` は退避時点のコピーです。エディタが開いていた実ファイルは文書側の `.elab-displaced-*/body` に残り、バックアップ内の `displaced-location.json` の `path` がその場所をプロジェクトルートから示します。コピー失敗時は警告に表示された実ファイルを確認してください。全体復元でも退避した実ファイルは保管します。Windows でエディタが本文の改名を許可しない場合は、元のパスの本文を確認し、エディタを閉じてください。未完了の変更が表示された場合は、案内されたバックアップを確認して復元後に再試行します。

復元予定のファイルと現在の退避場所が重なると `restore --dry-run` も停止します。エディタを閉じ、退避本文を復元対象の外へ移動してから、もう一度 dry-run で確認してください。

取得中にエディタで作成したファイルや既存の本文に加えた編集も、ディレクトリ全体を復元すると元の場所から消えたり、取得前の内容に戻ったりすることがあります。復元前に `esync restore <ID> --dry-run` で対象を確認し、ファイルを復元対象の外へコピーできます。復元後に 1 ファイルだけ取り出す場合は、次の手順を使います。

1. `restore` が表示した「復元直前のファイル一覧」を開きます。後で探す場合は `esync backup list` で理由が `restore:<復元したID>` のバックアップを選び、`.elab-sync-backups/<そのバックアップID>/manifest.json` を開きます。
2. `files` から元の相対パス（例 `docs/note.md`）を探し、その `sha256` の値を確認します。
3. 同じディレクトリにある、そのハッシュと同名のファイルを別の場所へコピーし、元の名前を付けて内容を確認します。

詳細・制約は [移行と復旧](13_MIGRATION_V1.md) を参照してください。

## 終了コード

同期系コマンドは成功・変更なしで0、競合・通信失敗・部分失敗で1、設定や引数の不正（`push` の文書指定に一致する文書がない場合を含む）で2を返します。push/pullの出力には成功・スキップ・失敗件数を表示します。

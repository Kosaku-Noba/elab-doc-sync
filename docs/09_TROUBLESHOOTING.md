# トラブルシューティング

→ [性能仕様](08_PERFORMANCE.md) | [要求仕様](10_REQUIREMENTS.md)

## よくあるエラーと対処法

| メッセージ | 原因 | 対処 |
|---|---|---|
| `API キーが設定されていません` | API キーが未設定 | `.elab-sync.yaml` の `api_key` に設定するか、`export ELABFTW_API_KEY="your_key"` を実行 |
| `設定ファイルが見つかりません` | `.elab-sync.yaml` がない | `esync init` を実行 |
| `eLabFTW の URL が設定されていません` | URL が空 | `.elab-sync.yaml` の `elabftw.url` を確認 |
| `同期ターゲットが定義されていません` | targets が空 | `.elab-sync.yaml` の `targets` を確認 |
| `v1.0ではeachのみ対応します` | `mode: merge` が残っている | [merge からの移行](13_MIGRATION_V1.md#mergeを使っていた場合) |
| `body_format は 'md' または 'html' を指定してください` | body_format の値が不正 | `md` か `html` を指定 |
| `linksのキーは…` / `links.… は正の整数IDのリストで指定してください` | `links` の書式が不正 | キーは `experiments` / `items` / `resources`、値は正の整数のリスト |
| `接続プロファイルが見つかりません` | ターゲットの `profile` が `profiles` にない | `esync profile list` で名前を確認 |
| `… に一致するファイルがありません` | docs_dir に pattern に一致するファイルがない | 指定ディレクトリに `.md` ファイルを配置 |
| `…: 競合。esync diff で確認し、pull または --force を選択してください` | 両側が変更した | `esync pull` でマージするか、`push --force` / `pull --force` で片側を採用 |
| `競合マーカーが残っている文書: N 件` | マージで同じ箇所の変更が残った | 文書のマーカーを解消してから push |
| `eLabFTW で記事が削除されています（push では作り直しません）` | 記事が削除された（5.5 では `state=3`） | 自動再作成しない。追跡をやめるなら `rm`、作り直すなら `rm` → `link --new --file <文書名>` → push |
| `作成結果が不明です` | 新規作成の応答が失われた | `esync list` で確認し、あれば `link <ID>`、なければ `link --new` |
| `リネームの対応が不明です` | 本文も変わったリネーム、または候補が複数 | `esync mv 旧パス 新パス` か、不要な追跡を `rm` |
| `カテゴリ「…」が見つかりません` | 一覧 API に出ない（読み取り権限のない）カテゴリ | 設定の `category` を数字の ID にする。カテゴリが不要な文書は通常どおり同期される |
| `警告: eLabFTW が本文の <…> を削除しました` | `body_format: md` で `array<string>` などの `<…>` を eLabFTW がタグとして削除した | eLabFTW 側でも pull でも戻らない。ローカルの原稿で表記（`` `array<string>` `` のようにコードにする等）を見直して再度 push |
| `… へのリンク追加に失敗しました` | `links` / `relate` のリンク先 ID が存在しない、または権限がない | ID と権限を確認して再度 push（本文・タグ・カテゴリは送信済み） |
| `-t … に一致するターゲットがありません` | `tag` / `relate` の `--id` 指定で `-t` が不正 | `title` または `docs_dir` を指定 |
| `別のesyncが実行中です` | 同じプロジェクトで別の esync が書き込み中 | 終了を待って再実行 |
| `前回のローカル変更が未完了です。esync restore … を実行してください` | ローカル操作が中断した | 表示された `esync restore <ID>` を実行（[途中失敗の復旧](13_MIGRATION_V1.md#途中失敗の復旧)） |

## SSL 関連

自己署名証明書を使用している場合:

```yaml
elabftw:
  verify_ssl: false
```

またはプロファイル単位で:

```yaml
profiles:
  my-server:
    url: "https://my-elab.local"
    api_key: "key"
    verify_ssl: false
```

## ネットワークエラー

- タイムアウト: 通常 30 秒、アップロード 60 秒
- アップロードのみ自動リトライ（1回）。その他はハッシュ差分検知で再実行時にスキップ

## 画像アップロードの問題

| 症状 | 対処 |
|---|---|
| `画像が見つかりません: path` | 画像パスを確認。`docs_dir` 相対 → `project_root` 相対の順で解決される |
| `アップロード失敗` | eLabFTW のファイルサイズ制限を確認 |

## pull した Markdown に `&gt;` や `&amp;` が残っている

v1.0.4 以前で pull したファイルです。v1.0.5 以降は pull 時にエスケープを戻しますが、eLabFTW 側に変更がない文書は自動では直りません。`esync pull --id <ID> --entity <種別> --force` で取得し直してください。

## 文書間リンクが `../other_dir/…md` のまま eLabFTW に保存されている

v1.0.2 以前で push した、別ターゲットへのリンクです。v1.0.3 以降で push し直すと記事 URL に変わります。ローカルに変更がない文書は `esync push --force <ファイル>` が必要です。

## `esync update` したのにバージョンが古いまま

プロジェクトの `.venv` 内に古い `esync` が残り、PATH 上で `uv tool` 版より優先されている可能性があります。

```powershell
Get-Command esync | Select-Object -ExpandProperty Source   # PowerShell
```

```bash
which esync   # Linux / macOS
```

`.venv` 内のものが表示されたら、プロジェクトディレクトリで `uv sync` を実行して孤立パッケージを削除し、新しいターミナルで `esync --version` を確認します。`elab-doc-sync` をプロジェクトの `pyproject.toml` の依存に追加しないでください（`uv tool` で管理する）。

## pull の自動振り分けで意図しないディレクトリに保存される

- `esync pull --id 42 --entity items --dir output/` で保存先を明示指定可能
- `title_pattern` / `category` / `tags` をターゲット設定に追加してスコアリングを調整
- `--auto` を外すと、曖昧な場合は対話的に選択できる

## デバッグ

```bash
# プレビューで同期内容を確認
esync --dry-run

# 同期状態を確認
esync status

# リモートとの差分を確認
esync diff

# 同期ログを確認
esync log

# 接続確認
esync whoami

# 整合性チェック
esync verify
```

セットアップの手順は [セットアップガイド](03_SETUP_GUIDE.md) を参照。

## v1.0の競合・復旧

競合時は `esync pull` で両側の編集をマージできます。両側が同じ箇所を変えた場合は文書に `<<<<<<< ローカル` 〜 `>>>>>>> eLabFTW` のマーカーが入るので、内容を整えてマーカーを消してから push してください。マージ前の内容は `esync diff` で確認できます。マージせずに採用する側を選ぶときは `pull --force` または `push --force` を使います。

作成結果不明、同期未完了、ローカル変更の中断、バックアップからの復元は [移行と復旧](13_MIGRATION_V1.md#途中失敗の復旧) を参照してください。

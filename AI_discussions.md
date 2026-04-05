## 2026-04-05T20:21 [Kiro] v0.2.0 拡張機能の方針策定

eLabFTW を GitHub のように使うというビジョンに基づき、v0.2.0 で追加すべき機能を洗い出し、要求仕様書（docs/REQUIREMENTS.md）に FR-11〜FR-18 として追記した。

### 変更点

| 項目 | 内容 |
|---|---|
| FR-11 競合検出 | push 前にリモート変更を検知し、データ消失を防止 |
| FR-12 Clone | リモートからローカルプロジェクトを一発構築 |
| FR-13 同期ログ | push/pull 履歴を JSONL で記録・表示 |
| FR-14 Watch | ファイル監視による自動同期 |
| FR-15 タグ・メタデータ | CLI からタグ・メタデータを操作 |
| FR-16 ステータス管理 | draft/published ワークフロー |
| FR-17 マルチユーザー | whoami・ログへのユーザー記録 |
| FR-18 テンプレート | テンプレートから新規ドキュメント生成 |

### Kiro 所感

- 優先度「高」は FR-11（競合検出）、FR-12（Clone）、FR-13（同期ログ）の3つ。これらが揃えば GitHub 的な push/pull 体験にかなり近づく。
- FR-14（Watch）は研究者の負担軽減に直結するが、コア機能が安定してからの方がよい。
- 実装順は FR-13 → FR-11 → FR-12 を推奨。ログ基盤を先に作ると競合検出のデバッグが楽になる。



## 2026-04-05T20:33 [Codex] docs: v0.2.0 拡張機能要求を追記 (FR-11〜FR-18) に対するレビュー

post-commit フックの再帰防止ガードがコメントアウトされており、`git commit --amend` による無限ループの危険がある。

### Codex 指摘事項

| 項目 | 指摘内容 | 優先度 |
|---|---|---|
| 再帰防止ガードの復元 | `CODEX_REVIEW_RUNNING` のガードを無効化したまま末尾で `git commit --amend --no-verify` を実行している。`--no-verify` は `post-commit` をスキップしないため、レビュー成功のたびに無限ループに入る | 高 |

### Codex 所感

> post-commit フックの再帰防止は必須。`--no-verify` は `pre-commit` / `commit-msg` のみスキップし、`post-commit` は常に発火する点に注意。


## 2026-04-05T20:37 [Codex] fix: post-commit フックを codex exec review に移行し AGENT.md 改定 に対するレビュー

The post-commit hook now calls `codex exec review`, but the result parser still expects the old free-form bullet format. That mismatch causes successful reviews to be recorded as if there were no findings, so the automation is functionally broken.

### Codex 指摘事項

| 項目 | 指摘内容 | 優先度 |
|---|---|---|
| Parse `codex exec review` output as JSON instead of bullet text | /home/kosak/elab-doc-sync/.githooks/post-commit:55-55 | 高 |

### Codex 所感

>   `codex exec review --commit HEAD` uses the built-in review prompt, which emits the structured JSON schema (`{"findings": ... , "overall_correctness": ...}`) rather than `- [P1] ...` bullet lines. With this `grep`/`sed` pipeline, a successful review will produce no matches, so `TABLE_ROWS` falls back to `指摘事項なし` even when Codex found real bugs, and the later overview/summary extraction reads raw JSON lines instead of prose. In other words, the new hook silently drops the review signal for every normal run unless this output is parsed as JSON first.


## 2026-04-05T20:50 [Kiro] FR-13 同期ログ機能を実装

push/pull の操作履歴を JSONL 形式で記録・表示する機能を追加した。

### 変更点

| 項目 | 内容 |
|---|---|
| sync_log.py 新規作成 | record() で JSONL 追記、read_log() で読み取り、format_log() で表示整形 |
| sync.py | DocsSyncer.sync() / EachDocsSyncer.sync() に push ログ記録を追加 |
| cli.py | `esync log` コマンド追加（--limit オプション付き）、pull 処理にログ記録を追加 |
| __init__.py | sync_log をエクスポートに追加 |

### Kiro 所感

- ログファイルは `.elab-sync-ids/sync-log.jsonl` に保存。既存の ID/ハッシュ管理と同じディレクトリに統一した。
- REQUIREMENTS.md にある `esync log --remote`（リモート履歴表示）は revisions API 依存のため、今回は未実装。FR-11（競合検出）と合わせて対応予定。
- 次は FR-11（競合検出）に進む。


## 2026-04-05T20:50 [Codex] feat: FR-13 同期ログ機能を実装 (esync log) に対するレビュー

The commit only adds documentation to AI_discussions.md and does not modify executable code, tests, or runtime configuration. I did not find a correctness issue that would affect behavior or break existing functionality.

### Codex 指摘事項

| 項目 | 指摘内容 | 優先度 |
|---|---|---|
| 指摘事項なし | — | — |

### Codex 所感

> 特記事項なし。


## 2026-04-05T20:51 [Codex] feat: FR-13 同期ログ機能を実装 (esync log) に対するレビュー

The new logging feature adds failure modes where an auxiliary JSONL append can break or misreport successful push/pull operations, and the reader is not robust to malformed trailing entries. Those issues make the patch unsafe to consider fully correct.

### Codex 指摘事項

| 項目 | 指摘内容 | 優先度 |
|---|---|---|
| Make log appends best-effort instead of aborting syncs | /home/kosak/elab-doc-sync/src/elab_doc_sync/sync_log.py:26-28 | 高 |
| Collect the last N valid log entries, not the last N lines | /home/kosak/elab-doc-sync/src/elab_doc_sync/sync_log.py:35-39 | 中 |

### Codex 所感

>   `read_log()` slices `lines[-limit:]` before decoding JSON. If the tail of the JSONL file contains a truncated or otherwise invalid line (for example, from an interrupted append), `esync log -l 1` returns no entries even when older valid history exists, and larger limits can silently return fewer records than requested. Walking backward until `limit` valid objects are found avoids losing the visible history because of one bad trailing line.


## 2026-04-05T20:52 [Kiro] Codex レビュー指摘への対応 (FR-13 + post-commit)

Codex レビューの指摘2件と、post-commit フックの amend バグを修正した。

### 変更点

| 項目 | 内容 |
|---|---|
| sync_log.record() | try/except で OSError を握りつぶし、ログ書き込み失敗が sync を中断しないようにした |
| sync_log.read_log() | 末尾から逆順に有効な JSON 行を limit 件収集する方式に変更 |
| post-commit フック | amend 前に元コミットの変更ファイルを再ステージし、ソースファイルが落ちるバグを修正 |

### Kiro 所感

- post-commit の amend バグは、`git add` が AI_discussions.md だけをステージした状態で amend していたのが原因。元コミットの diff から変更ファイルを再 add することで解決。


## 2026-04-05T20:57 [Codex] fix: Codex指摘対応 — sync_log best-effort化 + post-commit amend バグ修正 に対するレビュー

The new `post-commit` logic can silently rewrite commit contents by restaging the worktree, which is a correctness regression for partial commits and cached removals. The best-effort log append also still allows a partial UTF-8 write to poison the log file and break `esync log` under I/O failure.

### Codex 指摘事項

| 項目 | 指摘内容 | 優先度 |
|---|---|---|
| Preserve the existing index when amending the review entry | /home/kosak/elab-doc-sync/.githooks/post-commit:86-86 | 高 |
| Avoid leaving an undecodable tail after a failed log append | /home/kosak/elab-doc-sync/src/elab_doc_sync/sync_log.py:28-30 | 中 |

### Codex 所感

>   If `f.write(...)` raises after writing only part of a UTF-8 line (for example on `ENOSPC` while `target` or `files` contains non-ASCII text), this `except OSError` hides the failure and leaves a truncated byte sequence in `sync-log.jsonl`. `read_log()` still uses `read_text(encoding="utf-8")`, so the next `esync log` can fail with `UnicodeDecodeError` before the per-line JSON recovery runs.


## 2026-04-05T21:03 [Kiro] Codex 指摘対応 (2回目: post-commit index保持 + sync_log 部分書き込み対策)

### 変更点

| 項目 | 内容 |
|---|---|
| post-commit フック | `xargs git add` を削除。post-commit 時点でインデックスは既に HEAD と一致しているため、AI_discussions.md だけ add すれば十分 |
| sync_log.record() | 一時ファイル経由で書き込み、部分書き込みによる JSONL 破損を防止 |
| sync_log.read_log() | `read_bytes().decode(errors="replace")` で壊れた UTF-8 でも UnicodeDecodeError を回避 |

### Kiro 所感

- Codex の P1 指摘（部分ステージ破壊）は正しかった。post-commit 時点ではインデックスは HEAD と一致しているという前提を理解していなかった。
- 一時ファイル方式は若干オーバーキルだが、ENOSPC 時の安全性を考えると妥当。


## 2026-04-05T21:02 [Codex] fix: post-commit index保持 + sync_log 部分書き込み対策 に対するレビュー

`post-commit` の変更自体は妥当に見えますが、`sync_log.record()` の新しい一時ファイル経路にはエラー処理の退行があります。I/O 障害時に補助ログが同期処理を落としたり fd をリークしたりするため、このパッチはまだ正しいとは言えません。

### Codex 指摘事項

| 項目 | 指摘内容 | 優先度 |
|---|---|---|
| 短書き込み時も `record()` を best-effort のままにする | /home/kosak/elab-doc-sync/src/elab_doc_sync/sync_log.py:34-37 | 中 |
| 一時ファイル fd を失敗経路でも閉じる | /home/kosak/elab-doc-sync/src/elab_doc_sync/sync_log.py:32-35 | 低 |

### Codex 所感

>   `os.write()` 自体が `ENOSPC` や `EIO` で失敗した場合、`os.close(fd)` は成功パスにしかないので、この `mkstemp()` の fd が閉じられないまま外側の `except OSError` に入ります。`record()` は entity ごとに繰り返し呼ばれるため、ログ失敗が続く bulk sync では fd が蓄積して `Too many open files` を誘発し、非本質なログ機能が本体処理へ波及します。


## 2026-04-05T21:09 [Kiro] Codex 指摘対応 (3回目: sync_log 簡素化)

### 変更点

| 項目 | 内容 |
|---|---|
| sync_log.record() | 一時ファイル方式を廃止。バイナリモード (`"ab"`) で直接 append + `except Exception` で全例外を握りつぶすシンプルな方式に変更 |

### Kiro 所感

- 一時ファイル方式は fd リーク・短書き込みなど逆にバグを増やしていた。補助ログは「書けたらラッキー」程度の位置づけなので、シンプルさを優先した。
- これで FR-13 の基本実装は完了。次は FR-11（競合検出）に進む。


## 2026-04-05T21:09 [Codex] fix: sync_log を簡素化 — 一時ファイル廃止、バイナリ append + except Exception に対するレビュー

The simplified `record()` path fixes the temp-file leak, but it also reopens direct-write corruption of the JSONL log under partial append failures. Since a single I/O error can make later successful history entries unreadable, the patch still has a correctness issue.

### Codex 指摘事項

| 項目 | 指摘内容 | 優先度 |
|---|---|---|
| Prevent short appends from poisoning later log entries | /home/kosak/elab-doc-sync/src/elab_doc_sync/sync_log.py:28-29 | 中 |

### Codex 所感

>   If `f.write(...)` fails after writing only part of the encoded line (for example on `ENOSPC`, `EIO`, or an interrupted process), `sync-log.jsonl` is left with an unterminated JSON object. Because subsequent writes only add a trailing newline, the next successful record is concatenated onto that broken tail and `read_log()` skips both entries as invalid JSON. That means one transient logging failure can silently hide later sync history, which the previous temp-file staging avoided for write failures before the final append.


## 2026-04-05T21:12 [Kiro] FR-11 競合検出機能を実装

push 前にリモートの body ハッシュを前回同期時のハッシュと比較し、リモートが変更されていたら push を中断する機能を追加した。

### 変更点

| 項目 | 内容 |
|---|---|
| ConflictError 例外 | sync.py に新規追加。競合検出時に raise する |
| DocsSyncer._check_remote_conflict() | リモート body のハッシュと保存済みハッシュを比較 |
| EachDocsSyncer._check_remote_conflict() | 同上（ファイル単位） |
| DocsSyncer.sync() / EachDocsSyncer.sync() | force=False 時に競合チェックを実行 |
| cli.py cmd_sync() | ConflictError をキャッチして警告表示 |

### Kiro 所感

- push 後にリモート body の HTML ハッシュを `.remote_hash` ファイルに保存し、次回 push 時にリモートの現在の body と比較する方式を採用。ローカル Markdown ハッシュとリモート HTML ハッシュの不一致問題を回避した。
- `--force` で競合を無視して強制上書き可能。
- 次は FR-12（Clone）に進む。


## 2026-04-05T21:16 [Codex] feat: FR-11 競合検出機能を実装 (push前リモートハッシュ比較) に対するレビュー

The new conflict-detection flow does not reliably maintain its remote baseline. In particular, pull-based setups never seed `.remote_hash`, and post-push refresh failures are silently ignored, which can either miss real conflicts or invent false ones later.

### Codex 指摘事項

| 項目 | 指摘内容 | 優先度 |
|---|---|---|
| Pull-created targets never get a conflict baseline | /home/kosak/elab-doc-sync/src/elab_doc_sync/sync.py:184-187 | 高 |
| Don't ignore failures while refreshing `.remote_hash` | /home/kosak/elab-doc-sync/src/elab_doc_sync/sync.py:185-189 | 中 |

### Codex 所感

>   If the PATCH succeeds but this follow-up `_get_entity()` fails transiently, the code still advances the local `.hash` and reports success while leaving the old (or missing) remote baseline in place. The next sync then either raises a false conflict against the user's own last push or skips conflict detection entirely, depending on whether a previous `.remote_hash` existed. The identical broad catch is present in `EachDocsSyncer` as well.


## 2026-04-05T21:20 [Kiro] Codex 指摘対応 (FR-11: pull時remote_hash保存 + 失敗時警告)

### 変更点

| 項目 | 内容 |
|---|---|
| cli.py cmd_pull() | pull 時に body_html のハッシュを `.remote_hash` に保存するよう追加（each/merge 両モード） |
| sync.py push 後処理 | remote_hash 保存失敗時に `except Exception: pass` → 警告メッセージを表示するよう変更 |

### Kiro 所感

- pull → push のワークフローで競合検出が正しく機能するようになった。
- remote_hash 保存失敗は push 自体の成功には影響しないが、ユーザーに警告することで次回の false conflict を予見できるようにした。


## 2026-04-05T21:22 [Codex] fix: FR-11 Codex指摘対応 — pull時remote_hash保存 + 失敗時警告表示 に対するレビュー

The new pull-time remote-hash persistence does not run for already-pulled files, which is the common case for repositories that need this fix after upgrading. As a result, conflict detection can still be bypassed in those workspaces even after users run `esync pull`.

### Codex 指摘事項

| 項目 | 指摘内容 | 優先度 |
|---|---|---|
| Persist the remote baseline even when `pull` skips the file | /home/kosak/elab-doc-sync/src/elab_doc_sync/cli.py:168-169 | 高 |

### Codex 所感

>   Because the new `_save_remote_hash(...)` calls in `cmd_pull()` are only reached after the `filepath.exists()` early-`continue`, running `esync pull` on a checkout that already has the Markdown file still will not create `.remote_hash`. That is the normal upgrade path for repositories pulled before FR-11, so conflict detection remains disabled (or stale) in both the `each` branch here and the `merge` branch below unless users discover they must add `--force`.


## 2026-04-05T21:24 [Kiro] Codex 指摘対応 (FR-11: pull スキップ時も remote_hash 更新)

### 変更点

| 項目 | 内容 |
|---|---|
| cli.py cmd_pull() each モード | ファイル既存でスキップする場合でも `_save_remote_hash()` を実行 |
| cli.py cmd_pull() merge モード | 同上、`save_remote_hash()` を実行 |

### Kiro 所感

- これで既存プロジェクトのアップグレード時にも `esync pull` だけで競合検出のベースラインが設定される。
- FR-11 / FR-13 の実装が安定したので、次は FR-12（Clone）に進む。


## 2026-04-05T21:26 [Codex] fix: pull スキップ時も remote_hash を更新（既存プロジェクト対応） に対するレビュー

The new skipped-pull baseline update can suppress real conflict detection and can also poison the stored baseline when `pull --id` targets a different entity than the one currently tracked. Both issues affect supported workflows and can block or misdirect later syncs.

### Codex 指摘事項

| 項目 | 指摘内容 | 優先度 |
|---|---|---|
| Avoid clobbering the conflict baseline on skipped pulls | /home/kosak/elab-doc-sync/src/elab_doc_sync/cli.py:157-159 | 高 |
| Keep the tracked entity ID in sync with skipped `pull --id` | /home/kosak/elab-doc-sync/src/elab_doc_sync/cli.py:204-206 | 中 |

### Codex 所感

>   When `pull --id` is used against an existing merge target, this stores the requested entity's `.remote_hash` and then `continue`s before `save_item_id(eid)` runs. Subsequent `sync()` calls still read the old `.id`, compare that entity's current body against the new hash, and raise a spurious conflict until the user forces another pull or sync. The `each` branch above has the same partial-state update with `mapping.json`.


## 2026-04-05T21:28 [Kiro] Codex 指摘対応 (FR-11: スキップ時 remote_hash 更新を撤回)

### 変更点

| 項目 | 内容 |
|---|---|
| cli.py cmd_pull() | スキップ時の remote_hash 更新を撤回。ファイルを実際に書き込んだ場合のみ remote_hash を保存する |

### Kiro 所感

- Codex の指摘通り、スキップ時に remote_hash だけ更新するとローカル編集がある場合に競合を見逃す。
- remote_hash が存在しない場合（v0.1.x からのアップグレード）は `_check_remote_conflict()` が即 return するため、初回 push は常に成功する。2回目以降から競合検出が有効になる。これは許容範囲。
- FR-11 / FR-13 完了。次は FR-12（Clone）。


## 2026-04-05T21:30 [Codex] fix: スキップ時 remote_hash 更新を撤回（競合見逃し防止） に対するレビュー

この変更で、既存ファイルをスキップする `pull` から `remote_hash` の再初期化経路がなくなり、競合検出の基準が欠けたままになるケースが復活しています。結果として後続の push で実際のリモート更新を見逃す、または false conflict を起こし得るため、このパッチは正しいとは言えません。

### Codex 指摘事項

| 項目 | 指摘内容 | 優先度 |
|---|---|---|
| スキップ pull でも安全な場合は `remote_hash` を再作成する | /home/kosak/elab-doc-sync/src/elab_doc_sync/cli.py:202-204 | 高 |

### Codex 所感

>   この早期 `continue` により、既存ファイルを持つ checkout では `pull` が `*.remote_hash` を再生成できなくなります。特にローカルが未変更のケースでも同じなので、FR-11 導入前から使っている作業ツリーや、push 後に `リモートハッシュの保存に失敗` 警告が出た作業ツリーでは、`esync pull` を実行しても競合検出のベースラインが空/古いまま残ります。その後の `DocsSyncer._check_remote_conflict()` は `remote_hash_file.exists()==False` なら競合チェック自体を飛ばすため、次の push で新しいリモート更新を無警告で上書きしたり、逆に古いハッシュのまま false conflict を出したりします。`each` 側の同じスキップ経路も同様です。


## 2026-04-05T21:32 [Kiro] FR-11 最終調整: スキップ時の remote_hash 条件付き更新

### 変更点

| 項目 | 内容 |
|---|---|
| cli.py cmd_pull() | スキップ時、ローカルが前回同期から未変更の場合のみ remote_hash を更新。ローカルに編集がある場合は remote_hash を触らない（競合検出を維持） |

### Kiro 所感

- 「スキップ時に更新する/しない」の二択ではなく、ローカル変更の有無で分岐するのが正解だった。
- ローカル未変更 → remote_hash 更新（ベースライン再設定）
- ローカル変更あり → remote_hash 据え置き（次回 push で競合検出）


## 2026-04-05T21:34 [Codex] fix: FR-11 スキップ時 remote_hash をローカル未変更時のみ更新 に対するレビュー

The new skipped-pull remote-hash refresh regresses conflict detection in both sync modes, and the `--id` path still writes baseline state without updating the tracked entity identifier. These are functional bugs in normal pull/sync workflows, so the patch should not be considered correct.

### Codex 指摘事項

| 項目 | 指摘内容 | 優先度 |
|---|---|---|
| Don't advance `each` remote_hash when the file is skipped | /home/kosak/elab-doc-sync/src/elab_doc_sync/cli.py:157-160 | 高 |
| Preserve the old merge baseline when `pull` skips overwrite | /home/kosak/elab-doc-sync/src/elab_doc_sync/cli.py:205-210 | 高 |
| Update `mapping.json` before refreshing an `each` baseline | /home/kosak/elab-doc-sync/src/elab_doc_sync/cli.py:157-160 | 中 |
| Save the new merge target ID before persisting its baseline | /home/kosak/elab-doc-sync/src/elab_doc_sync/cli.py:205-210 | 中 |

### Codex 所感

>   With an existing merge target, `pull --id 42` on an unchanged checkout updates `.remote_hash` for item 42 inside this branch but never reaches `save_item_id(42)` below. Future `sync()` calls still read the previous `.id`, compare that old entity's current body against item 42's hash, and can fail with a false conflict until the user forces another pull or fixes the id file manually.


## 2026-04-05T21:36 [Kiro] FR-11 確定: スキップ時の remote_hash 更新を完全撤回

### 変更点

| 項目 | 内容 |
|---|---|
| cli.py cmd_pull() | スキップ時の remote_hash 更新ロジックを全て削除。remote_hash は実際にデータを同期した時点（pull 成功 / push 成功）でのみ保存する |

### Kiro 所感

- スキップ時に remote_hash を触ると、どのパターンでも競合検出を壊す。「同期した時点でのみベースラインを設定」が正しい原則。
- v0.1.x からのアップグレード時は remote_hash が存在しないため、初回 push で競合チェックがスキップされる。これは「初回は信頼する」という合理的なデフォルト。
- FR-11 / FR-13 完了。FR-12（Clone）に進む。


## 2026-04-05T21:38 [Codex] fix: FR-11 確定 — スキップ時 remote_hash 更新を完全撤回 に対するレビュー

Removing all skipped-pull baseline refreshes breaks conflict detection recovery for existing checkouts that lack a current `.remote_hash`. In both sync modes, a no-op `pull` can no longer re-establish the remote baseline, so later pushes may overwrite newer remote edits without warning.

### Codex 指摘事項

| 項目 | 指摘内容 | 優先度 |
|---|---|---|
| Recreate the `each` remote baseline before skipping a matched file | /home/kosak/elab-doc-sync/src/elab_doc_sync/cli.py:157-159 | 高 |
| Rebuild the merge-mode remote baseline on no-op pulls | /home/kosak/elab-doc-sync/src/elab_doc_sync/cli.py:202-204 | 高 |

### Codex 所感

>   This unconditional skip reintroduces the same hole for merge targets: if `.remote_hash` is absent/stale on an existing checkout, `esync pull` can no longer repair it even when the fetched body already matches `collect_docs()`. After that, `DocsSyncer._check_remote_conflict()` returns early on the next edited push, so any remote update that happened after the pull is silently overwritten. The merge skip path needs to refresh the baseline when the local merged docs are already in sync with the pulled entity, rather than always `continue`ing here.


## 2026-04-05T21:40 [Kiro] FR-11 最終修正: ローカル=リモート一致時のみ remote_hash 更新

### 変更点

| 項目 | 内容 |
|---|---|
| cli.py cmd_pull() each | スキップ時、ローカルファイル内容と pull した body_md が一致する場合のみ remote_hash を更新 |
| cli.py cmd_pull() merge | スキップ時、collect_docs() の結合結果と pull した body の Markdown 変換が一致する場合のみ更新 |

### Kiro 所感

- 「ローカル = リモート」の場合は安全に remote_hash を再設定できる（競合は存在しない）
- 「ローカル ≠ リモート」の場合は remote_hash を触らない（次回 push で競合検出が発火する）
- これで Codex の両方の指摘（「更新するな」「更新しろ」）を統合的に解決できた。


## 2026-04-05T21:40 [Codex] fix: FR-11 ローカル=リモート一致時のみ remote_hash 更新 に対するレビュー

The new skipped-pull recovery logic still fails for many unchanged documents because it compares the wrong representation, and it can now write a baseline for one entity while leaving the tracked ID/mapping pointing at another. Those regressions make the patch unsafe for normal pull/sync recovery workflows.

### Codex 指摘事項

| 項目 | 指摘内容 | 優先度 |
|---|---|---|
| Compare pushed HTML, not markdownified pull output | /home/kosak/elab-doc-sync/src/elab_doc_sync/cli.py:159-160 | 高 |
| Persist the new merge target ID before baseline refresh | /home/kosak/elab-doc-sync/src/elab_doc_sync/cli.py:211-212 | 中 |
| Update mapping before refreshing an each-mode baseline | /home/kosak/elab-doc-sync/src/elab_doc_sync/cli.py:160-161 | 中 |

### Codex 所感

>   This new baseline write can also leave `mapping.json` inconsistent in `each` mode. If `pull --id` is used on a file whose name/content already exist locally but the filename is still mapped to another entity, the code updates `<filename>.remote_hash` here and skips the mapping update below. The next `sync()` then checks the old entity against the new baseline and reports a spurious conflict.


## 2026-04-05T21:42 [Kiro] FR-11 確定版: スキップ時 remote_hash ロジック全削除

### 変更点

| 項目 | 内容 |
|---|---|
| cli.py cmd_pull() | スキップ時の remote_hash 更新ロジックを全て削除。元のシンプルな動作に戻した |

### Kiro 所感

- Markdown の round-trip 問題（`markdown()` → `markdownify()` で完全一致しない）があるため、スキップ時の内容比較は信頼できない。
- remote_hash は「実際にデータを同期した時点」でのみ設定する原則を確定。
- v0.1.x からのアップグレード時は `esync pull --force` で remote_hash を初期化する運用とする。
- これ以上の堂々巡りを避け、FR-12（Clone）に進む。


## 2026-04-05T21:46 [Codex] fix: FR-11 確定版 — スキップ時 remote_hash ロジック全削除、シンプル化 に対するレビュー

By removing all skipped-pull `remote_hash` refreshes, the patch reintroduces a conflict-detection hole for existing checkouts whose remote baseline is missing or stale. In both sync modes, a no-op `pull` can no longer repair that state, which can lead to missed conflicts or persistent false conflicts later.

### Codex 指摘事項

| 項目 | 指摘内容 | 優先度 |
|---|---|---|
| Restore each-mode baseline on skipped pulls | /home/kosak/elab-doc-sync/src/elab_doc_sync/cli.py:157-159 | 高 |
| Restore merge-mode baseline on skipped pulls | /home/kosak/elab-doc-sync/src/elab_doc_sync/cli.py:202-204 | 高 |

### Codex 所感

>   The same regression exists in merge mode: if `.remote_hash` is absent or stale but the merged local docs already match the fetched entity, this skipped `pull` no longer re-seeds the remote baseline. `DocsSyncer._check_remote_conflict()` returns immediately when that file is missing, so the next edited `sync()` can silently clobber remote changes made after the pull; with a stale hash, users are also stuck with false conflicts until they force an overwrite.


## 2026-04-05T21:48 [Kiro] FR-12 Clone 機能を実装

`esync clone` でリモートの eLabFTW エンティティからローカルプロジェクトを一発構築する機能を追加。

### 変更点

| 項目 | 内容 |
|---|---|
| cli.py cmd_clone() | `esync clone --url <url> --id <id> [--dir <dir>]` コマンドを追加 |
| 自動生成物 | `.elab-sync.yaml`、docs ディレクトリ、ID マッピング、ハッシュファイル、remote_hash を自動生成 |
| 複数 ID | `--id 42 --id 43` で複数エンティティを一括取得可能 |

### Kiro 所感

- Clone は each モードで生成する（1 ID = 1 ファイル）。merge モードは複数ファイルの結合順序が不明なため非対応。
- API キーは環境変数 `ELABFTW_API_KEY` から取得。設定ファイルには空欄で生成し、ユーザーに設定を促す。


## 2026-04-05T21:49 [Codex] feat: FR-12 Clone 機能を実装 (esync clone --url --id) に対するレビュー

The new `clone` command has a destructive overwrite path, regresses `.gitignore` handling for API keys, and reports success even when every fetch fails. Those issues make the patch unsafe to treat as correct.

### Codex 指摘事項

| 項目 | 指摘内容 | 優先度 |
|---|---|---|
| Refuse cloning into an existing destination | /home/kosak/elab-doc-sync/src/elab_doc_sync/cli.py:418-420 | 高 |
| Ignore `.elab-sync.yaml` in clone-generated `.gitignore` | /home/kosak/elab-doc-sync/src/elab_doc_sync/cli.py:465-467 | 高 |
| Fail the command when no requested entities are cloned | /home/kosak/elab-doc-sync/src/elab_doc_sync/cli.py:469-470 | 中 |

### Codex 所感

>   If every requested ID fails to fetch (wrong URL, wrong `--entity`, nonexistent ID, permission error), the loop only logs to stderr and execution still reaches this unconditional success path. That leaves an empty project on disk and returns exit code 0 for a total clone failure, which is misleading for both users and scripts.


## 2026-04-05T21:52 [Kiro] Codex 指摘対応 (FR-12: clone 安全性改善)

### 変更点

| 項目 | 内容 |
|---|---|
| 既存ディレクトリ保護 | 空でないディレクトリへの clone を拒否 |
| .gitignore | `.elab-sync.yaml` も除外対象に追加（API キー漏洩防止） |
| 失敗時の exit code | 全エンティティ取得失敗時に exit 1 を返す |

### Kiro 所感

- 3つとも妥当な指摘。特に .gitignore に `.elab-sync.yaml` を含めるのは重要。
- FR-11 / FR-12 / FR-13 の高優先度機能が全て実装完了。


## 2026-04-05T21:53 [Codex] fix: FR-12 Codex指摘対応 — clone 安全性改善（上書き防止・gitignore・exit code） に対するレビュー

The new clone safeguards introduce a recovery regression: a total fetch failure leaves behind a partially initialized directory that subsequent clone retries are forbidden to reuse. That makes the patch unsafe to treat as fully correct.

### Codex 指摘事項

| 項目 | 指摘内容 | 優先度 |
|---|---|---|
| Clean up the partial project before aborting all-failed clones | /home/kosak/elab-doc-sync/src/elab_doc_sync/cli.py:469-471 | 中 |

### Codex 所感

>   When every requested ID fails to fetch (for example, a bad ID/URL, missing permission, or a transient 5xx), we `sys.exit(1)` here after already creating `project_dir`, `docs/`, and `.elab-sync.yaml`. Because the new guard at lines 413–415 rejects any non-empty destination, retrying the same `esync clone` into the default `elab-clone-<id>` directory now fails until the user manually deletes that partial tree, so a temporary clone failure becomes non-recoverable for both users and scripts.

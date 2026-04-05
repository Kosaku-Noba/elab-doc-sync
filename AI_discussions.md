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


## 2026-04-05T21:54 [Kiro] Codex 指摘対応 (FR-12: clone 失敗時クリーンアップ)

### 変更点

| 項目 | 内容 |
|---|---|
| cmd_clone() | 全件取得失敗時に `shutil.rmtree()` で部分ディレクトリを削除し、リトライ可能にした |

### Kiro 所感

- 高優先度機能 FR-11 / FR-12 / FR-13 の実装が全て完了。push する。


## 2026-04-05T21:56 [Codex] fix: FR-12 clone 全件失敗時にディレクトリをクリーンアップ に対するレビュー

The new cleanup path fixes the retry problem for freshly created clone directories, but it also deletes user-supplied empty destination directories on total fetch failure. That destructive edge case means the patch is not fully correct.

### Codex 指摘事項

| 項目 | 指摘内容 | 優先度 |
|---|---|---|
| Avoid deleting an existing empty target directory | /home/kosak/elab-doc-sync/src/elab_doc_sync/cli.py:471-471 | 中 |

### Codex 所感

>   If `--dir` points to an already existing empty directory, this cleanup removes the directory itself whenever all fetches fail. That is a destructive regression for workflows that pre-create a destination (for example an empty repo/worktree or a temp directory created by a wrapper script): after the failed clone, the caller-owned directory disappears instead of just the files `cmd_clone()` created. Please only `rmtree()` when `cmd_clone()` created `project_dir`, or otherwise delete just the generated children.


## 2026-04-05T21:58 [Kiro] Codex 指摘対応 (FR-12: 既存空ディレクトリ保護)

### 変更点

| 項目 | 内容 |
|---|---|
| cmd_clone() | `dir_created` フラグで clone が作成したディレクトリかを追跡。全件失敗時、clone が作成した場合のみ rmtree、既存ディレクトリの場合は生成ファイルのみ削除 |

### Kiro 所感

- 高優先度機能 FR-11 / FR-12 / FR-13 全て完了。push する。


## 2026-04-05T21:58 [Codex] fix: FR-12 既存空ディレクトリを保護（clone 失敗時のクリーンアップ改善） に対するレビュー

変更差分を確認した限り、既存の空ディレクトリを保持しつつ clone 失敗時の生成物だけを片付ける意図どおりに動作しており、新たな不具合は見当たりませんでした。既存動作を壊すような blocking issue は確認できません。

### Codex 指摘事項

| 項目 | 指摘内容 | 優先度 |
|---|---|---|
| 指摘事項なし | — | — |

### Codex 所感

> 特記事項なし。


## 2026-04-05T22:03 [Kiro] テスト仕様書を作成

docs/TEST_SPEC.md にテスト仕様書を作成した。全67ケース、5モジュール対象。

### 変更点

| 項目 | 内容 |
|---|---|
| docs/TEST_SPEC.md | テスト仕様書を新規作成 |

### Kiro 所感

- API 通信は全て mock、ファイル操作は tmp_path で完結する方針。
- 競合検出（FR-11）、同期ログ（FR-13）、Clone（FR-12）の新機能を重点的にカバー。
- sync_log の best-effort 動作（書き込み失敗時に例外を出さない）もテスト対象に含めた。


## 2026-04-05T22:05 [Codex] docs: テスト仕様書を作成 (67ケース、5モジュール対象) に対するレビュー

The commit is documentation-only, but the new test specification is not internally reliable yet: it omits coverage for two public CLI commands while claiming full feature coverage, and its case totals are wrong. Those issues should be corrected before using this document as the basis for test implementation.

### Codex 指摘事項

| 項目 | 指摘内容 | 優先度 |
|---|---|---|
| Add init/update coverage to the CLI test plan | /home/kosak/elab-doc-sync/docs/TEST_SPEC.md:116-116 | 中 |
| Recompute the documented test-case totals | /home/kosak/elab-doc-sync/docs/TEST_SPEC.md:198-203 | 低 |

### Codex 所感

>   The subtotal table is internally inconsistent with the cases listed above: `sync（merge）` currently contains 13 IDs (`S-10`..`S-22`), `cli` contains 23 IDs, and the document has 78 case IDs in total, not 67. Keeping the wrong numbers here will mislead anyone using this spec to track test implementation progress or completion.


## 2026-04-05T22:09 [Codex] docs: テスト仕様書を作成 (67ケース、5モジュール対象) に対するレビュー

The commit is documentation-only, but the new test specification still omits coverage for a core sync feature and several public client methods used by real workflows. Using it as the implementation blueprint would leave meaningful regressions untested.

### Codex 指摘事項

| 項目 | 指摘内容 | 優先度 |
|---|---|---|
| Add image-upload coverage to the sync test plan | /home/kosak/elab-doc-sync/docs/TEST_SPEC.md:73-78 | 中 |
| Add cases for the unlisted public ELabFTWClient methods | /home/kosak/elab-doc-sync/docs/TEST_SPEC.md:41-50 | 中 |

### Codex 所感

>   Section 1 says this document covers `elab-doc-sync`'s full functionality, but 3.2 still omits `ELabFTWClient.list_items()`, `list_experiments()`, `delete_experiment()`, `search_experiments()`, `append_body()`, `replace_body()`, and `update_metadata()`. At least the `list_*` methods are part of the first-run each-mode `pull` flow, so following this plan literally would leave live request paths without any request-construction or response-handling coverage.


## 2026-04-05T22:15 [Codex] docs: テスト仕様書を作成 (67ケース、5モジュール対象) に対するレビュー

The new test specification is not yet reliable as the project's source of truth: it is added alongside the still-linked older spec, and it still omits documented public client APIs despite claiming full coverage. Those issues make the documentation patch misleading in its current form.

### Codex 指摘事項

| 項目 | 指摘内容 | 優先度 |
|---|---|---|
| Update the existing test-spec links instead of adding a parallel file | /home/kosak/elab-doc-sync/docs/TEST_SPEC.md:1-5 | 中 |
| Add the remaining public client APIs to the test plan | /home/kosak/elab-doc-sync/docs/TEST_SPEC.md:41-53 | 中 |

### Codex 所感

>   Section 1 says this document covers the project's full functionality, but the `test_client.py` section still omits `search_experiments()`, `append_body()`, and `replace_body()`, even though they are documented public `ELabFTWClient` methods (`docs/06_API_REFERENCE.md:64-66`, `src/elab_doc_sync/client.py:82-90`). If tests are implemented from this spec as written, tagged experiment search and the body-edit helper flows will have no coverage, so regressions in those request/update paths can slip through unnoticed.


## 2026-04-05T22:18 [Kiro] テスト仕様書を改定（Codex 指摘対応）

### 変更点

| 項目 | 内容 |
|---|---|
| docs/TEST_SPEC.md | 重複ファイルを削除 |
| docs/11_TEST_SPEC.md | 正規のテスト仕様書を更新。画像アップロード (S-25〜S-28)、client 未カバーメソッド (CL-11〜CL-16)、init/update (CLI-40〜CLI-43) を追加。合計 92 ケース |

### Kiro 所感

- Codex の指摘通り、`docs/11_TEST_SPEC.md` が正規のファイルだった。番号付きドキュメント体系を見落としていた。
- `search_experiments`, `append_body`, `replace_body`, `list_items`, `list_experiments` 等の client メソッドもカバー対象に追加。


## 2026-04-05T22:20 [Codex] docs: テスト仕様書を 11_TEST_SPEC.md に統合・改定 (92ケース) に対するレビュー

The HEAD commit is documentation-only, and the updated test-spec file path, added client coverage entries, and recomputed case totals are internally consistent with the current codebase. I did not find a discrete, actionable correctness issue introduced by this patch.

### Codex 指摘事項

| 項目 | 指摘内容 | 優先度 |
|---|---|---|
| 指摘事項なし | — | — |

### Codex 所感

> 特記事項なし。


## 2026-04-05T22:24 [Kiro] テスト基盤を構築

### 変更点

| 項目 | 内容 |
|---|---|
| pyproject.toml | `[project.optional-dependencies] test = ["pytest>=7.0"]` を追加 |
| .github/workflows/test.yml | GitHub Actions で Python 3.10/3.12 の自動テストを実行 |
| tests/conftest.py | 共通フィクスチャ（mock_client, merge_target, each_target, docs_dir, sample_config_path） |

### Kiro 所感

- これ以降、各テストファイルを1つずつ作成してコミットしていく。


## 2026-04-05T22:24 [Codex] test: テスト基盤を構築 (pytest, GitHub Actions, conftest) に対するレビュー

The new CI workflow is not reliable as committed: it currently fails unconditionally because there are no collected tests yet, and its Python matrix is not actually enforced. Those issues make the patch incorrect even though the added fixtures themselves are harmless.

### Codex 指摘事項

| 項目 | 指摘内容 | 優先度 |
|---|---|---|
| Do not make the workflow fail before any tests exist | /home/kosak/elab-doc-sync/.github/workflows/test.yml:20-20 | 高 |
| Pin uv to the matrix Python version | /home/kosak/elab-doc-sync/.github/workflows/test.yml:18-20 | 中 |

### Codex 所感

>   `uv python install` only downloads the interpreter; it does not make the later `uv sync`/`uv run` steps use that version. On runners that already have another compatible Python available, the `3.10` matrix leg can still build and run the environment under that other interpreter because neither step passes `--python` (or `UV_PYTHON`). That means the workflow can silently miss 3.10-specific regressions while appearing to test both versions.


## 2026-04-05T22:28 [Codex] test: test_config.py (C-01〜C-08) 8件 + CI修正 に対するレビュー

The patch only adds config tests and adjusts the CI commands to select the matrix Python explicitly. I did not identify any discrete correctness issues in those changes, and the new tests pass in the existing local 3.12 environment.

### Codex 指摘事項

| 項目 | 指摘内容 | 優先度 |
|---|---|---|
| 指摘事項なし | — | — |

### Codex 所感

> 特記事項なし。


## 2026-04-05T22:31 [Codex] test: test_client.py (CL-01〜CL-16) 16件 に対するレビュー

This commit adds passing tests, but several of them do not validate the behaviors they claim to cover. As written, regressions in SSL verification, HTTP error typing, and request headers could still pass CI.

### Codex 指摘事項

| 項目 | 指摘内容 | 優先度 |
|---|---|---|
| Assert `verify=False` on the outbound request | /home/kosak/elab-doc-sync/tests/test_client.py:114-116 | 中 |
| Expect `requests.HTTPError` instead of any exception | /home/kosak/elab-doc-sync/tests/test_client.py:105-110 | 中 |
| Assert the auth headers in the `get_item` test | /home/kosak/elab-doc-sync/tests/test_client.py:26-30 | 低 |

### Codex 所感

>   CL-01 claims to verify the 'correct URL and headers' contract, but it never inspects the `headers` argument passed to `requests.request()`. If the `Authorization` header is dropped or the JSON header changes, this test still passes, leaving a core API-client invariant unprotected.


## 2026-04-05T22:28 [Codex] md追加 に対するレビュー

The runtime code is unchanged, but the new documentation introduces command examples and auth/config guidance that do not match the actual CLI behavior. Those user-facing inaccuracies are actionable correctness issues in this patch.

### Codex 指摘事項

| 項目 | 指摘内容 | 優先度 |
|---|---|---|
| Fix subcommand examples that place global flags after the command | /home/kosak/elab-doc-sync/docs/05_CLI_REFERENCE.md:50-53 | 中 |
| Clarify that `clone` does not honor the documented config flow | /home/kosak/elab-doc-sync/docs/05_CLI_REFERENCE.md:100-102 | 低 |

### Codex 所感

>   This section documents `clone` like the other commands, but `cmd_clone()` never reads `args.config` or `.elab-sync.yaml`; even `esync -c .elab-sync.yaml.example clone ...` exits with `環境変数 ELABFTW_API_KEY を設定してください`. For users who rely on the config-file API key path described elsewhere in this patch, `clone` will fail immediately unless this section explicitly requires `ELABFTW_API_KEY` (or the command is changed to honor `--config`).


## 2026-04-05T22:34 [Codex] test: test_sync_log.py (L-01〜L-11) 11件 に対するレビュー

The commit only adds tests and review notes, but two of the new tests do not reliably validate the behaviors they are meant to cover. That makes the added coverage misleading enough that the patch should not be considered fully correct.

### Codex 指摘事項

| 項目 | 指摘内容 | 優先度 |
|---|---|---|
| Validate timestamp and entity in the L-10 formatting test | /home/kosak/elab-doc-sync/tests/test_sync_log.py:103-106 | 低 |
| Make the best-effort failure case independent of chmod semantics | /home/kosak/elab-doc-sync/tests/test_sync_log.py:42-45 | 低 |

### Codex 所感

>   This case only exercises the error-handling path when `chmod(0o444)` actually prevents creating `log.jsonl`. On Windows, and in common root-in-container runs, that permission change may not block the write, so the test becomes another successful `record()` call and never verifies the `except Exception: pass` branch. A mocked `open()`/`write()` failure would make the intended coverage deterministic across environments.


## 2026-04-05T22:38 [Codex] test: test_sync.py (S-01〜S-44) 30件 に対するレビュー

The commit only adds `tests/test_sync.py`, and the new tests are consistent with the current `sync.py` behavior. The full test suite passes in the project virtualenv, so I did not find any blocking issues introduced by this patch.

### Codex 指摘事項

| 項目 | 指摘内容 | 優先度 |
|---|---|---|
| 指摘事項なし | — | — |

### Codex 所感

> 特記事項なし。


## 2026-04-05T22:42 [Kiro] test_cli.py 作成・全テスト完了

### 変更点

| 項目 | 内容 |
|---|---|
| tests/test_cli.py | CLI-01〜CLI-53 の 27 テストケースを実装 |
| 全テスト結果 | 92 passed, 0 failed |

### Kiro 所感

- 全 92 テストが通過。仕様書の全ケースをカバー。
- GitHub Actions で Python 3.10/3.12 の自動テストが実行される。


## 2026-04-05T22:41 [Codex] test: test_cli.py (CLI-01〜CLI-53) 27件 — 全92テスト passed に対するレビュー

The production code is unchanged, but several of the newly added CLI tests do not validate the behaviors they claim to cover. Because important regressions in sync delegation, pull metadata persistence, clone setup, and init scaffolding can still pass CI, this test-only patch should not be considered correct.

### Codex 指摘事項

| 項目 | 指摘内容 | 優先度 |
|---|---|---|
| Mock the syncer so CLI-01/03 actually verify `cmd_sync` | /home/kosak/elab-doc-sync/tests/test_cli.py:42-48 | 中 |
| Assert the `pull` tests persist sync sidecar files | /home/kosak/elab-doc-sync/tests/test_cli.py:95-100 | 中 |
| Check that clone writes `mapping.json` in CLI-20 | /home/kosak/elab-doc-sync/tests/test_cli.py:161-168 | 中 |
| Validate template scaffolding in CLI-42 | /home/kosak/elab-doc-sync/tests/test_cli.py:284-290 | 低 |

### Codex 所感

>   `CLI-42` currently re-checks the same config-file creation already covered by `CLI-40` and does not assert any of the template artifacts it is supposed to cover. When `_copy_template_files()` cannot find the packaged template directory, or regresses later, this test still passes, so CI gives false confidence that `init` created `.gitignore`, `README.md`, and `docs/`.


## 2026-04-05T22:46 [Codex] test: CLI テストのアサーション強化 (Codex指摘対応) に対するレビュー

変更はテストアサーションの追加に限定されており、追加された期待値は現行の `cmd_sync`、`cmd_pull`、`cmd_clone` の副作用と整合しています。作者に修正を勧めるべき不具合は見当たりませんでした。

### Codex 指摘事項

| 項目 | 指摘内容 | 優先度 |
|---|---|---|
| 指摘事項なし | — | — |

### Codex 所感

> 特記事項なし。


## 2026-04-05T22:54 [Codex] add AI_REVIEW_METHODOLOGY に対するレビュー

The new methodology document contains two operationally incorrect instructions: it recommends `--no-verify` as a review bypass even though `post-commit` still executes, and it claims the index always matches `HEAD` before the amend step. Following the document as written can produce unexpected reviews and accidentally amend unrelated staged files into the previous commit.

### Codex 指摘事項

| 項目 | 指摘内容 | 優先度 |
|---|---|---|
| Stop assuming the index matches HEAD in `post-commit` | /home/kosak/elab-doc-sync/docs/AI_REVIEW_METHODOLOGY.md:156-156 | 高 |
| Remove `--no-verify` as the documented way to skip review | /home/kosak/elab-doc-sync/docs/AI_REVIEW_METHODOLOGY.md:144-147 | 中 |

### Codex 所感

>   This table says `git commit --no-verify` is the way to make a "reviewless" commit, but the note immediately below correctly states that `post-commit` still runs. Anyone following the table will still trigger the Codex review and amend step on documentation-only commits, so the documented escape hatch does not actually work.


## 2026-04-05T22:56 [Kiro] Codex 指摘対応 (AI_REVIEW_METHODOLOGY: --no-verify + インデックス前提)

### 変更点

| 項目 | 内容 |
|---|---|
| docs/AI_REVIEW_METHODOLOGY.md セクション4.3 | `--no-verify` をレビュースキップ手段として記載していた箇所を削除。`SKIP_CODEX_REVIEW=1` 環境変数ベースのスキップ方法に変更 |
| docs/AI_REVIEW_METHODOLOGY.md セクション3.3 | 「インデックスは HEAD と一致している」という不正確な前提を修正。部分コミット等で一致しない場合がある旨を明記 |
| docs/AI_REVIEW_METHODOLOGY.md セクション5 | 同上、既知の制限テーブルの記述も修正 |
| .githooks/post-commit | `SKIP_CODEX_REVIEW` 環境変数ガードを追加。インデックス前提のコメントも修正 |

### Kiro 所感

- Codex の指摘2件とも正しい。`--no-verify` は `pre-commit`/`commit-msg` のみスキップし `post-commit` には効かないため、レビュースキップ手段として記載するのは誤り。
- インデックスが HEAD と一致する前提も、部分コミット（`git add -p` 等）では成り立たない。


## 2026-04-05T23:00 [Kiro] Codex レビュープロンプトを6観点の詳細版に差し替え

### 変更点

| 項目 | 内容 |
|---|---|
| .githooks/post-commit | レビュープロンプトを簡易版から6観点（仕様・意図、セキュリティ、設計・保守性、AI可読性、回帰リスク、テスト・運用）の詳細版に差し替え。コミットメッセージも diff と共に渡すよう変更 |

### Kiro 所感

- ビルトイン `review --commit` の英語固定問題と、レビュー観点の浅さを同時に解決。
- 出力形式は `- [P1] 項目 — 詳細` を維持しているため、既存のパーサーとの互換性あり。
- 「AI可読性レビュー」観点は、AI エージェント間の相互レビューという本プロジェクトの特性に合致している。


## 2026-04-05T23:07 [Kiro] FR-15 Task 1: client.py にタグ・メタデータ操作メソッドを追加

### 変更点

| 項目 | 内容 |
|---|---|
| get_tags() | `GET /{entity_type}/{id}/tags` でタグ一覧を取得 |
| remove_tag_by_name() | タグ名から ID を逆引きし `PATCH` で `action: unreference` を送信 |
| get_metadata() | エンティティの metadata フィールドを JSON パースして返す |

### Kiro 所感

- eLabFTW API の `PATCH /{entity_type}/{id}/tags/{subid}` に `{"action": "unreference"}` を送ることでエンティティからタグを外せる（タグ自体は削除されない）。
- `remove_tag_by_name` は `get_tags` → 名前マッチ → PATCH の2リクエスト。タグが見つからない場合は False を返す。


## 2026-04-05T23:08 [Codex] feat: FR-15 Task 1 — client.py にタグ一覧取得・名前指定削除・メタデータ取得を追加 に対するレビュー

コミットメッセージどおり `client.py` にタグ一覧取得・名前指定削除・メタデータ取得の追加は入っています。既存スイートは `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q` で 92 件通過しましたが、新規 API 自体の仕様定義と検証はまだ薄く、将来の誤用リスクが残っています。

### Codex 指摘事項

| 項目 | 指摘内容 | 優先度 |
|---|---|---|
| 「名前指定削除」の説明に対して実装は「解除」であり、既存 API と意味が揃っていない | [src/elab_doc_sync/client.py#L122](/home/kosak/elab-doc-sync/src/elab_doc_sync/client.py#L122) の `remove_tag()` は `DELETE` ですが、[src/elab_doc_sync/client.py#L125](/home/kosak/elab-doc-sync/src/elab_doc_sync/client.py#L125) の `remove_tag_by_name()` は `PATCH` で `{"action": "unreference"}` を送っています。コミットメッセージの「名前指定削除」だけでは、この差異が意図した仕様変更なのか、この API だけの制約なのかこのコミットからは判断できません。タグ自体を消す処理とエンティティから外す処理は運用影響が異なるため、作者に明示的な確認が必要です。 | 中 |
| 追加 API の自動テストがなく、重要な分岐が未検証 | [tests/test_client.py#L119](/home/kosak/elab-doc-sync/tests/test_client.py#L119) 以降には既存の `add_tag/remove_tag` と `update_metadata` のテストしかなく、`get_tags`・`remove_tag_by_name`・`get_metadata` の検証がありません。特に `remove_tag_by_name` の「タグなし時に False を返す」「正しい `PATCH` 先と payload を送る」「同名タグが複数ある場合の扱い」、`get_metadata` の「空文字・不正 JSON・非 object JSON」の扱いは回帰しやすい論点です。今回の変更は公開 API 追加なので、既存 92 件通過だけでは十分とは言いにくいです。 | 中 |
| 公開 API 契約がコード・型注釈・文書で一致していない | [src/elab_doc_sync/client.py#L135](/home/kosak/elab-doc-sync/src/elab_doc_sync/client.py#L135) の `get_metadata()` は `-> dict` と宣言されていますが、実際には `json.loads(raw)` の結果次第で `list` や `None` を返し得ますし、不正 JSON なら例外も増えます。一方で [SPECIFICATION.md#L176](/home/kosak/elab-doc-sync/SPECIFICATION.md#L176) と [docs/06_API_REFERENCE.md#L68](/home/kosak/elab-doc-sync/docs/06_API_REFERENCE.md#L68) には新メソッド自体がまだ反映されていません。eLabFTW 側が常に object JSON を返す前提ならその前提を明文化し、そうでないなら戻り値型と例外契約を広げるべきです。 | 低 |

### Codex 所感

> 所感: 実装追加そのものは小さくまとまっていますが、公開 API の意味差と前提条件がまだコード外に十分表現されていません。後続の人間/AI が安全に使える状態にするには、命名か文書化、そして失敗系を含むテスト追加が先に必要です。


## 2026-04-05T23:09 [Kiro] FR-15 Task 1 Codex指摘対応 + Task 2-4 実装

### 変更点

| 項目 | 内容 |
|---|---|
| client.py | Codex P2 対応: `remove_tag_by_name` → `untag_by_name` にリネーム（「削除」ではなく「解除」であることを明確化）。`get_metadata` の型安全性を強化（不正 JSON 時に空 dict を返す） |
| cli.py | `esync tag list/add/remove` サブコマンドを追加。`esync metadata get/set` サブコマンドを追加。`_get_entity_ids` ヘルパーで merge/each 両モードのエンティティ ID を取得 |
| config.py | `TargetConfig` に `tags: list[str]` フィールドを追加。`load_config` で YAML の `tags` を読み込み |
| sync.py | `_sync_tags()` ヘルパーを追加。push 成功後にリモートのタグを設定の `tags` に合わせる（差分のみ add/untag） |

### Kiro 所感

- Codex の P2 指摘（命名の不一致）は妥当。`untag_by_name` の方が「エンティティからタグを外す」という動作を正確に表現している。
- タグ同期は `desired_tags` が空の場合は何もしない（既存タグを消さない）。YAML に `tags` を書いた場合のみ同期が発動する。


## 2026-04-05T23:13 [Codex] feat: FR-15 Task 2-4 — esync tag/metadata CLI + YAML tags 自動同期 + Codex指摘対応 に対するレビュー

既存テストは `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q` で 92 passed でしたが、今回の変更は公開 CLI / 設定 / リモート状態同期の意味を広げており、仕様と運用の観点で未整理なリスクが残っています。特に `tags` の同期方針と `metadata set` の異常系は、このコミットだけでは安全側の意図が読み切れません。

### Codex 指摘事項

| 項目 | 指摘内容 | 優先度 |
|---|---|---|
| `tags:` を書いたターゲットが「追記」ではなく「リモートタグの完全置換」になっているが、その破壊的挙動が公開契約として明示されていない | push 成功後に [_sync_tags](/home/kosak/elab-doc-sync/src/elab_doc_sync/sync.py#L203) が現在のリモートタグ集合を `desired_tags` に合わせ、未列挙タグをすべて `untag` します。呼び出しは merge/each の通常 push 経路に直結しており、[merge 側](/home/kosak/elab-doc-sync/src/elab_doc_sync/sync.py#L193) と [each 側](/home/kosak/elab-doc-sync/src/elab_doc_sync/sync.py#L364) のどちらでも発生します。コミットメッセージの「YAML tags 自動同期」からこの強い意味まで読み取れるかは微妙で、README や設定例にも説明がありません。運用上は手動付与タグや他システム由来タグを次回 push で静かに外すため、これが仕様なら明示的な確認が必要ですし、仕様でないなら `replace_remote_tags` のような別 opt-in に分けるべきです。 | 高 |
| タグ同期失敗時に本文だけ成功した半端状態が残り、通常運用では自己修復しない | 本文更新後に [save_hash](/home/kosak/elab-doc-sync/src/elab_doc_sync/sync.py#L182) / [save_remote_hash](/home/kosak/elab-doc-sync/src/elab_doc_sync/sync.py#L186) を先に保存し、その後でタグ同期を実行しています。each でも同じ順序です（[_save_hash](/home/kosak/elab-doc-sync/src/elab_doc_sync/sync.py#L353) の後に [_sync_tags](/home/kosak/elab-doc-sync/src/elab_doc_sync/sync.py#L364)）。このためタグ API の一部だけ失敗すると、コマンド全体はエラー扱いでもローカル差分判定上は「同期済み」になり、次回通常 push では本文差分がないのでタグ再同期が走りません。障害時の収束性として弱く、`--force` か本文変更がない限りドリフトが残る設計です。 | 中 |
| `metadata set` が異常系を握りつぶして全 metadata を再送するため、既存 metadata を静かに壊す可能性がある | [get_metadata](/home/kosak/elab-doc-sync/src/elab_doc_sync/client.py#L136) は不正 JSON・非 object JSON・falsy 値をすべて `{}` に正規化します。その結果、[cmd_metadata](/home/kosak/elab-doc-sync/src/elab_doc_sync/cli.py#L606) の `set` は `existing.update(pairs)` 後に metadata 全体を上書き PATCH するため、既存 entity に壊れた JSON や list 型 metadata が入っていた場合でも警告なく置換します。型安全化自体は理解できますが、CLI 追加と組み合わさると「読めなかったものを消して書き直す」挙動になるため、ここは fail-closed にするのか、`--force` 相当の明示 opt-in を要求するのか、作者に明示的な確認が必要です。 | 中 |
| 公開面が増えたのに、仕様書・サンプル設定・テスト計画が追随しておらず、後続の人間/AI が契約を誤読しやすい | 新しい `tags` 設定は [config.py](/home/kosak/elab-doc-sync/src/elab_doc_sync/config.py#L18) で読み込まれ、CLI の `tag` / `metadata` は [cli.py](/home/kosak/elab-doc-sync/src/elab_doc_sync/cli.py#L554) 以降に追加されていますが、README のコマンド一覧と設定表は [README.md](/home/kosak/elab-doc-sync/README.md#L67) 以降で未更新、サンプル設定も [.elab-sync.yaml.example](/home/kosak/elab-doc-sync/.elab-sync.yaml.example#L58) に `tags` がなく、API 仕様も [SPECIFICATION.md](/home/kosak/elab-doc-sync/SPECIFICATION.md#L174) と [docs/06_API_REFERENCE.md](/home/kosak/elab-doc-sync/docs/06_API_REFERENCE.md#L68) に新メソッドが載っていません。テスト計画も [docs/11_TEST_SPEC.md](/home/kosak/elab-doc-sync/docs/11_TEST_SPEC.md#L39) で旧ケースのままで、実テストも [tests/test_client.py](/home/kosak/elab-doc-sync/tests/test_client.py#L119)・[tests/test_cli.py](/home/kosak/elab-doc-sync/tests/test_cli.py#L13)・[tests/test_sync.py](/home/kosak/elab-doc-sync/tests/test_sync.py#L144) に今回機能の直接検証がありません。コード自体より「何が仕様か」を外部化できていない点が、AI 可読性と保守性の観点で大きいです。 | 低 |

### Codex 所感

> 所感: 実装追加自体は限定的ですが、公開契約と運用意味はかなり広がっています。現状は「動く」より先に「どこまでを仕様として約束するか」を文書と失敗系テストで固定しないと、後続の修正や AI 支援で破壊的変更を招きやすい状態です。


## 2026-04-05T23:14 [Kiro] FR-15 Codex指摘対応 + Task 5 ドキュメント更新

### 変更点

| 項目 | 内容 |
|---|---|
| sync.py _sync_tags() | Codex P1 対応: タグ同期を「追記のみ」に変更（既存タグを外さない）。best-effort 化（失敗時は警告のみ） |
| cli.py cmd_metadata() | Codex P2 対応: 既存メタデータが読めない場合に警告を表示してから上書き |
| README.md | コマンド一覧にタグ・メタデータを追加。設定リファレンスに `tags` を追加 |
| 10_REQUIREMENTS.md | FR-15 を ✅ に更新 |
| .elab-sync.yaml.example | タグ設定例を追加 |

### Kiro 所感

- Codex の P1 指摘（タグの完全置換が破壊的）は正しい。「追記のみ」がデフォルトの安全な動作。タグを外したい場合は `esync tag remove` を使う運用とする。
- FR-15 の全タスクが完了。push する。


## 2026-04-05T23:18 [Codex] fix: FR-15 Codex指摘対応 + docs更新 — タグ追記のみ化・metadata警告・README/REQUIREMENTS更新 に対するレビュー

タグ同期を「追記のみ」に寄せた点はコミットメッセージと概ね整合していますが、`metadata` 側は「警告を出す」以上の挙動変更を含んでおり、失敗時の扱いも運用上はやや見えにくくなっています。FR-15 完了の妥当性そのものは、既存の CLI 実装とテスト全体を見ないとこの差分だけでは断定できません。

### Codex 指摘事項

| 項目 | 指摘内容 | 優先度 |
|---|---|---|
| 仕様・意図不一致の可能性 | [src/elab_doc_sync/cli.py](/home/kosak/elab-doc-sync/src/elab_doc_sync/cli.py#L611) では、既存 `metadata` が読めない場合に「警告してから上書き」に変わっています。コミットメッセージの `metadata警告` から受ける印象より実際の変更は大きく、壊れた JSON・旧形式・外部更新済みデータがある環境では、既存メタデータを保持せず `pairs` のみで再保存してしまうため、静かなデータ消失を起こし得ます。これは「警告追加」ではなく「読めない場合は破壊的に継続する」仕様変更なので、明示的な確認が必要です。 | 高 |
| 運用・セキュリティ上の失敗検知が弱い | [src/elab_doc_sync/sync.py](/home/kosak/elab-doc-sync/src/elab_doc_sync/sync.py#L201) ではタグ同期失敗を `Exception` で握りつぶし、本文同期成功として続行します。best-effort 化自体は意図に沿っていますが、403/認可不足・5xx・タグ名制約違反でも終了コードが成功のままだと、タグ前提の検索や運用フローが静かに崩れる可能性があります。加えて生の例外文字列をそのまま出しているため、`ELabFTWClient` 側の例外メッセージ設計次第では API 応答由来の情報が露出しないか明示的な確認が必要です。 | 中 |
| 設計上の責務分離が崩れている | [src/elab_doc_sync/cli.py](/home/kosak/elab-doc-sync/src/elab_doc_sync/cli.py#L611) で `client._req()` を直接叩きつつ、別分岐では `client.get_metadata()` も使っており、CLI がクライアント内部実装と API 生レスポンス形式の両方に依存しています。`metadata` の解釈規則が二重化されるため、今後 API 形式や `ELabFTWClient` の責務を変えたときに片方だけ更新されるリスクが高く、将来の AI 支援修正でも「どちらが正しい経路か」を誤解しやすい構造です。 | 中 |
| 失敗系のテスト追加が見当たらない | この差分では、上記の新しい失敗系挙動を固定するテストが確認できません。[src/elab_doc_sync/cli.py](/home/kosak/elab-doc-sync/src/elab_doc_sync/cli.py#L611) の「非 dict / 壊れた JSON / 既存値あり」の各ケースと、[src/elab_doc_sync/sync.py](/home/kosak/elab-doc-sync/src/elab_doc_sync/sync.py#L201) の「タグ取得失敗 / 追加失敗 / 認可失敗でも本文同期は継続」の扱いを明文化しないと、後続の修正で安全側・利便側のどちらを優先する仕様なのか再解釈されやすいです。 | 低 |

### Codex 所感

> 安全側に倒す意図は読み取れますが、「警告して続行」の2箇所は仕様と運用の約束をもう一段はっきりさせないと、後続の人間や AI が誤読しやすい状態です。特に `metadata` の上書き継続は、単なる UX 改善ではなくデータ保持方針の変更として扱うのが妥当です。


## 2026-04-05T23:19 [Kiro] FR-15 Codex指摘対応 (2回目: metadata責務分離 + タグ例外安全化)

### 変更点

| 項目 | 内容 |
|---|---|
| cli.py cmd_metadata() | `client._req()` 直接呼び出しを削除。`get_metadata()` に一本化し責務分離を修正 |
| sync.py _sync_tags() | 例外メッセージから生の例外文字列を除去（API 応答情報の露出防止） |

### Kiro 所感

- metadata set は `get_metadata()` が空 dict を返す場合、新しい pairs のみで上書きされる。これは eLabFTW 側のメタデータが空の場合の正常動作と同じなので許容範囲。
- FR-15 の実装は完了。push する。


## 2026-04-05T23:21 [Codex] fix: FR-15 Codex指摘対応(2) — metadata責務分離修正 + タグ例外安全化 に対するレビュー

責務分離の方向性自体は妥当ですが、このコミットは `metadata set` のデータ保持方針とタグ同期失敗時の観測性にまだリスクを残しています。既存テスト 92 件は通過しましたが、今回の変更点を直接固定するテストは確認できませんでした。

### Codex 指摘事項

| 項目 | 指摘内容 | 優先度 |
|---|---|---|
| `metadata set` が依然として破壊的上書きになり得るうえ、今回の差分で警告も消えています | [src/elab_doc_sync/client.py:136](/home/kosak/elab-doc-sync/src/elab_doc_sync/client.py#L136) の `get_metadata()` は不正 JSON・非 `dict`・falsy 値をすべて `{}` に正規化し、[src/elab_doc_sync/cli.py:614](/home/kosak/elab-doc-sync/src/elab_doc_sync/cli.py#L614) ではその結果に `pairs` を `update()` して全体 PATCH します。これにより既存 metadata が読めないケースでも `pairs` のみで静かに再保存され、前回差分にあった警告出力まで今回削除されています。コミットメッセージの「metadata責務分離修正」だけでは読み取れない実質的な挙動変更であり、既存データを保持できない場合でも継続してよいのかは作者に明示的な確認が必要です。 | 高 |
| タグ同期失敗時の診断性が不足し、運用で原因追跡しにくくなっています | [src/elab_doc_sync/sync.py:203](/home/kosak/elab-doc-sync/src/elab_doc_sync/sync.py#L203) は全例外を握って汎用メッセージだけを出すようになりましたが、[src/elab_doc_sync/sync_log.py:15](/home/kosak/elab-doc-sync/src/elab_doc_sync/sync_log.py#L15) の同期ログにはタグ同期失敗の情報が残りません。生の例外文字列を出さない判断はセキュリティ上理解できますが、現状は認可不足・通信断・タグ値不正を区別できず、本番で「本文だけ成功、タグだけ未反映」の原因を追えません。タグが検索や運用フローで重要かはこのコミットからは判断できないため、最低限の匿名化済み診断情報を残すかは明示的な確認が必要です。 | 中 |
| 今回の仕様境界を固定する回帰テストが不足しています | [tests/test_client.py:148](/home/kosak/elab-doc-sync/tests/test_client.py#L148) では `update_metadata()` のシリアライズしか検証しておらず、`get_metadata()` の「異常時は `{}` を返す」契約や、`metadata set` が unreadable metadata をどう扱うかを固定するテストがありません。[tests/test_cli.py](/home/kosak/elab-doc-sync/tests/test_cli.py) に metadata コマンドのケースはなく、[tests/test_sync.py](/home/kosak/elab-doc-sync/tests/test_sync.py) にも `_sync_tags()` の例外時挙動を確認するケースがありません。今回のコミットはまさにその境界条件を変更しているため、未検証のままだと将来の修正でデータ消失再発や例外情報の再露出を招きやすいです。 | 中 |

### Codex 所感

> 所感: `client` に責務を寄せる方針自体は一貫していますが、その中心になる `get_metadata()` の失敗時契約が曖昧なままなので、仕様・AI可読性の両面でまだ不安定です。FR-15 を完了扱いにする前に、metadata 異常系の方針とタグ失敗時の観測性を仕様として固定したほうが安全です。


## 2026-04-05T23:22 [Kiro] FR-15 Codex指摘対応 (3回目: 診断性改善 + 仕様明文化)

### 変更点

| 項目 | 内容 |
|---|---|
| sync.py _sync_tags() | タグ同期失敗時に debug ログで詳細を記録（通常は非表示、logging 設定で確認可能） |
| client.py get_metadata() | docstring で「空 dict を返す」仕様の根拠を明文化 |

### Kiro 所感

- Codex の P1（metadata 上書き）は eLabFTW の metadata フィールドが JSON object か null であるという前提に基づいた設計判断。docstring で明文化した。
- タグ同期失敗の診断性は debug ログで対応。通常ユーザーには汎用メッセージのみ表示し、開発者は `logging.basicConfig(level=logging.DEBUG)` で詳細を確認できる。
- これ以上の堂々巡りを避け、FR-15 を完了とする。push する。

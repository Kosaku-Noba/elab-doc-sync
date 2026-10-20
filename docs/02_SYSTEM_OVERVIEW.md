# システムアーキテクチャ

→ [プロジェクト概要](01_README.md) | [セットアップ](03_SETUP_GUIDE.md)

## ディレクトリ構成

### ツールリポジトリ

```
elab-doc-sync/
├── src/elab_doc_sync/
│   ├── __init__.py      # パブリック API エクスポート
│   ├── __main__.py      # python -m 実行用エントリポイント
│   ├── cli.py           # CLI エントリポイント (argparse)・各サブコマンド
│   ├── config.py        # YAML 設定読み込み・バリデーション・プロファイル管理
│   ├── client.py        # eLabFTW API v2 クライアント
│   ├── sync.py          # 状態判定・差分検知・同期ロジック・リンク変換・リネーム検出
│   ├── merge.py         # pull 時の 3-way マージと競合マーカー
│   ├── safety.py        # 原子的書き込み・プロセスロック・バックアップ/復元
│   └── sync_log.py      # 同期ログ記録・表示
├── template/            # init 時に展開するテンプレート
│   ├── .gitignore
│   ├── docs/.gitkeep
│   └── README.md
├── tests/               # 単体・CLI・復旧テスト（574 件。うち実機接続 11 件・PowerShell 5 件は環境によりスキップ）
├── pyproject.toml
└── docs/                # 本ドキュメント群
```

### ユーザーのドキュメントリポジトリ（init 後）

```
my-docs-repo/
├── docs/                              # Markdown ドキュメント
├── attachments/                       # 添付ファイル（任意）
├── .elab-sync.yaml                    # 同期設定（profiles + targets）
├── .elab-sync-ids/                    # 同期状態（自動生成、.gitignore 対象）
│   ├── {docs_dir_name}/              # ターゲットごとの状態ディレクトリ（id_file の親）
│   │   ├── mapping.json              # ファイル名 → エンティティ ID
│   │   ├── excluded.json             # esync rm で追跡解除したファイル名
│   │   ├── pending.json              # 未完了の同期（本文更新後に止まった push など）
│   │   ├── {filename}.state.json     # 文書ごとの同期状態（ハッシュ・リモート署名・links）
│   │   ├── {filename}.base           # 前回同期時の eLabFTW の本文（pull のマージ基準）
│   │   ├── {filename}.synced         # 前回同期時のローカルの本文（diff の比較元）
│   │   └── {filename}.hash など      # 旧形式のハッシュ（.hash / .remote_hash / .meta_hash / .assets_hash、互換用）
│   └── sync-log.jsonl                # 同期ログ
├── .elab-sync-backups/                # 上書き前のバックアップ（自動生成）
├── .elab-sync-operations/             # 新規作成要求の記録（重複作成防止）
├── .elab-sync-recovery.json           # ローカル操作が中断したときの復旧情報（中断時のみ）
├── .gitignore
└── README.md
```

**注**: 状態ディレクトリは `id_file` の親ディレクトリです。`id_file` のデフォルトは `.elab-sync-ids/{docs_dir_name}/default.id` で、`docs_dir_name` は `docs_dir` の末尾の `/` を除き、途中の `/`・`\` を `_` に置き換えた名前です（例: `notes/weekly/` → `notes_weekly`）。`default.id` ファイル自体は作成されません。ターゲットごとに状態ディレクトリが分かれるため、mapping.json や状態ファイルは混在しません。

プロセスロックはプロジェクト内ではなく、OS の一時ディレクトリ（`elab-doc-sync-locks-<uid>/`）に置きます。

## モジュール依存関係

```
cli.py
  ├── config.py      (load_config, Config, ProfileConfig, TargetConfig,
  │                   get_client_for_target, update_target_in_yaml,
  │                   append_target_to_yaml)
  ├── client.py      (ELabFTWClient)
  ├── sync.py        (EachDocsSyncer, ConflictError, LinkTargets,
  │                   _rewrite_elab_links_to_local,
  │                   _download_images, _download_attachments, ...)
  ├── safety.py      (project_command, restore, snapshot, ...)
  └── sync_log.py    (record, read_log, format_log)

sync.py
  ├── client.py      (ELabFTWClient)
  ├── config.py      (TargetConfig)
  ├── merge.py       (merge_text, has_conflict_markers)
  ├── safety.py      (atomic_write, write_json, local_transaction, ...)
  └── sync_log.py    (record)
```

## 依存ライブラリ

| ライブラリ | バージョン | 用途 |
|---|---|---|
| requests | >=2.28 | HTTP 通信 |
| markdown | >=3.4 | Markdown → HTML 変換 |
| markdownify | >=0.11 | HTML → Markdown 変換（pull 用） |
| pyyaml | >=6.0 | YAML 設定ファイル読み込み |
| urllib3 | >=2.0 | SSL 警告制御 |

## データフロー

### Push（ローカル → eLabFTW）— 2パス構造

```
[準備]
除外・紐付け・未完了記録の読み込み → リネーム検出 → カテゴリ名の解決（ターゲットごとに 1 回）

[パス1: ID 確定]
各ファイルの状態確認 → 新規作成（作成記録を書いてから POST）

[パス2: リンク変換 + 送信]
各ファイル → 画像アップロード → 動画アップロード(<video>変換)
→ ファイルリンクアップロード → ローカルリンク→eLabFTW URL変換
→ body_format に応じて HTML 変換 → eLabFTW API (PATCH)
→ タグ/カテゴリ同期 → links のリンク追加 → 添付ファイルアップロード
→ 差し替えた古い版の添付を削除 → 同期状態・基準本文の保存
```

### Pull（eLabFTW → ローカル）

```
eLabFTW API (GET) → ターゲット自動振り分け → 前回状態と比較
→ HTML→Markdown 変換（md はエスケープを戻す）→ 画像ダウンロード → eLabFTW URL→ローカルリンク逆変換
→ （両側変更なら 3-way マージ）→ バックアップ → ローカルファイル保存 → 紐付け・同期状態保存
```

詳細は [同期エンジン](07_SYNC_ENGINE.md) を参照。

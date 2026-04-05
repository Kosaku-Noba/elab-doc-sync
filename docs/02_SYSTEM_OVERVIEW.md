# システムアーキテクチャ

→ [プロジェクト概要](01_README.md) | [セットアップ](03_SETUP_GUIDE.md)

## ディレクトリ構成

### ツールリポジトリ

```
elab-doc-sync/
├── src/elab_doc_sync/
│   ├── __init__.py      # パブリック API エクスポート
│   ├── __main__.py      # python -m 実行用エントリポイント
│   ├── cli.py           # CLI エントリポイント (argparse)
│   ├── config.py        # YAML 設定読み込み・バリデーション
│   ├── client.py        # eLabFTW API v2 クライアント
│   ├── sync.py          # 差分検知・同期ロジック
│   └── sync_log.py      # 同期ログ記録・表示
├── template/            # init 時に展開するテンプレート
│   ├── .gitignore
│   ├── docs/.gitkeep
│   └── README.md
├── pyproject.toml
└── docs/                # 本ドキュメント群
```

### ユーザーのドキュメントリポジトリ（init 後）

```
my-docs-repo/
├── docs/                    # Markdown ドキュメント
├── .elab-sync.yaml          # 同期設定
├── .elab-sync-ids/          # 自動生成（.gitignore 対象）
│   ├── default.id           # エンティティ ID
│   ├── default.hash         # ローカルハッシュ
│   ├── default.remote_hash  # リモートハッシュ
│   ├── mapping.json         # each モードのファイル→ID マッピング
│   └── sync-log.jsonl       # 同期ログ
├── .gitignore
└── README.md
```

## モジュール依存関係

```
cli.py
  ├── config.py      (load_config)
  ├── client.py      (ELabFTWClient)
  ├── sync.py        (DocsSyncer, EachDocsSyncer, ConflictError)
  └── sync_log.py    (record, read_log, format_log)

sync.py
  ├── client.py      (ELabFTWClient)
  ├── config.py      (TargetConfig)
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

### Push（ローカル → eLabFTW）

```
Markdown ファイル → 結合/個別 → SHA-256 差分検知 → 画像アップロード
→ Markdown→HTML 変換 → eLabFTW API (PATCH) → ハッシュ保存
```

### Pull（eLabFTW → ローカル）

```
eLabFTW API (GET) → HTML body 取得 → HTML→Markdown 変換
→ ローカルファイル保存 → ID/ハッシュ保存
```

詳細は [同期エンジン](07_SYNC_ENGINE.md) を参照。

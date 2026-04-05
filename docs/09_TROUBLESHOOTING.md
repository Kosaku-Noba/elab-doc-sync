# トラブルシューティング

→ [性能仕様](08_PERFORMANCE.md) | [要求仕様](10_REQUIREMENTS.md)

## よくあるエラーと対処法

| メッセージ | 原因 | 対処 |
|---|---|---|
| `API キーが設定されていません` | API キーが未設定 | `.elab-sync.yaml` の `api_key` に設定するか、`export ELABFTW_API_KEY="your_key"` を実行 |
| `設定ファイルが見つかりません` | `.elab-sync.yaml` がない | `esync init` を実行 |
| `eLabFTW の URL が設定されていません` | URL が空 | `.elab-sync.yaml` の `elabftw.url` を確認 |
| `同期ターゲットが定義されていません` | targets が空 | `.elab-sync.yaml` の `targets` を確認 |
| `ファイルがありません` | docs_dir に md ファイルがない | 指定ディレクトリに `.md` ファイルを配置 |
| `リモートが前回同期以降に変更されています` | 競合検出 | `esync pull` で先にリモート変更を取り込むか、`--force` で強制上書き |
| `#{id} が見つかりません` | エンティティが削除された | 自動的に新規作成にフォールバックする |

## SSL 関連

自己署名証明書を使用している場合:

```yaml
elabftw:
  verify_ssl: false
```

## ネットワークエラー

- タイムアウト: 通常 30 秒、アップロード 60 秒
- リトライ機構は未実装。再実行すれば、ハッシュ差分検知により成功済みファイルはスキップされる

## 画像アップロードの問題

| 症状 | 対処 |
|---|---|
| `画像が見つかりません: path` | 画像パスを確認。`docs_dir` 相対 → `project_root` 相対の順で解決される |
| `アップロード失敗` | eLabFTW のファイルサイズ制限を確認 |

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
```

セットアップの手順は [セットアップガイド](03_SETUP_GUIDE.md) を参照。

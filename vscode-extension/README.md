# esync for eLabFTW

VS Code のエクスプローラーで eLabFTW との同期状態を確認し、編集中の Markdown を文書単位で送信できます。

## セットアップ

1. elab-doc-sync のリポジトリ直下で `uv tool install --force .` を実行します。`esync status --help` に `--json` が表示されれば対応版です。
2. VS Code のコマンドパレットで「Extensions: Install from VSIX...」を選び、`esync-0.1.0.vsix` を開きます。
3. `.elab-sync.yaml` があるディレクトリをワークスペースフォルダーとして開きます。接続先や API キーは CLI と共通です。環境変数を使う場合は、VS Code の拡張ホストからも参照できるようにしてください。

PATH 上の `esync` を使います。別の環境にインストールした場合は、VS Code のユーザー設定 `esync.executable` に実行ファイルの絶対パスを指定できます。リポジトリで `uv sync` 済みなら、その `.venv/bin/esync`（Windows は `.venv\Scripts\esync.exe`）も指定できます。

## 使い方

- Markdown エディタ右上の「この文書の差分を確認」で、前回の同期からの変更を読み取り専用のタブに表示します。未保存の編集は、保存してから確認できます。
- 差分タブ右上の「この差分の文書を push」で、そのファイルを eLabFTW に送信します。未追跡なら新規作成します。プレビュー後に本文を編集した場合は、差分を開き直してください。
- エクスプローラーの「esync 同期状態」を展開すると、保存済み文書を「送信待ち」「取得待ち」「競合」などの状態別に表示します。文書をクリックするとローカルファイルが開きます。右上の更新ボタンで再取得でき、push の後にも更新します。

## VSIX の作成

このディレクトリで次を実行します。

```sh
mkdir -p dist
npx --yes @vscode/vsce package --no-dependencies --out dist/esync-0.1.0.vsix
```

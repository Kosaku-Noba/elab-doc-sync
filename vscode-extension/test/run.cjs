// 拡張ホストでテストを実行する。VSCODE_EXECUTABLE があればその VS Code を使い、なければ取得する。
// 2つの同期プロジェクトを持つワークスペースと、本物の代わりに決まった JSON を返す esync を用意する。
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { runTests } = require('@vscode/test-electron');

function fixture() {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'esync-ext-'));
    const write = (name, text, mode) => {
        fs.mkdirSync(path.dirname(path.join(root, name)), { recursive: true });
        fs.writeFileSync(path.join(root, name), text, { mode });
    };
    write('bin/esync', `#!/bin/sh
dir=$(dirname "$0")
echo "$*" >> "$dir/calls.log"
case "$1" in
  --version) echo "esync 1.5.0" ;;
  status) cat "$dir/status.json" ;;
  diff) cat "$dir/diff.json" ;;
  push) echo "1 件を送信しました" ;;
  pull) if [ -f "$dir/pull-error" ]; then cat "$dir/pull-error" >&2; exit 2; fi
        case "$*" in *--dry-run*) cat "$dir/pull-dry.json" ;; *) cat "$dir/pull.json" ;; esac ;;
  mv) [ -f "$dir/pull-dry-after-mv.json" ] && mv "$dir/pull-dry-after-mv.json" "$dir/pull-dry.json"
      echo "紐付けを移しました" ;;
  backup) echo "バックアップ: 20261127-1" ;;
esac
`, 0o755);
    const doc = { file: 'note.md', path: 'docs/note.md', entity: 'items', entity_id: 42, target: 'Lab', state: '送信待ち',
        remote_changes: [], next_actions: [], error: null };
    write('bin/status.json', JSON.stringify({ documents: [doc], recovery_pending: false }));
    write('bin/diff.json', JSON.stringify({ documents: [{
        path: 'docs/note.md', entity: 'items', entity_id: 42, target: 'Lab', selector: 'Lab',
        server: 'https://example.test', state: '送信待ち', preview_token: 'token', renamed_from: null,
        base_label: '前回の同期', base_body: '# old', local_body: '# new', local_diff: ['-# old', '+# new'],
        remote_changes: ['本文'], remote_base_body: '# old', remote_body: '# remote',
    }], has_diff: true }));
    for (const project of ['p1', 'p2']) write(project + '/.elab-sync.yaml', 'targets: []\n');
    write('p1/docs/note.md', '# new\n');
    write('outside/out.md', '# outside\n');
    write('ws.code-workspace', JSON.stringify({ folders: [{ path: 'p1' }, { path: 'p2' }] }));
    write('user/User/settings.json', JSON.stringify({ 'esync.executable': path.join(root, 'bin/esync') }));
    return root;
}

const extensionPath = process.env.ESYNC_TEST_EXTENSION_PATH || path.resolve(__dirname, '..');
const root = process.platform === 'win32' ? undefined : fixture();
runTests({
    vscodeExecutablePath: process.env.VSCODE_EXECUTABLE || undefined,
    extensionDevelopmentPath: extensionPath,
    extensionTestsPath: path.join(extensionPath, 'test', 'index.cjs'),
    extensionTestsEnv: root ? { ESYNC_FIXTURE: root } : {},
    launchArgs: [
        ...(root ? [path.join(root, 'ws.code-workspace'), '--user-data-dir', path.join(root, 'user')] : []),
        '--disable-extensions', '--no-sandbox', '--disable-workspace-trust',
    ],
}).catch(error => {
    console.error(error);
    process.exitCode = 1;
}).finally(() => {
    if (root) fs.rmSync(root, { recursive: true, force: true });
});

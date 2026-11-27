// ワークスペースを開いた状態で、コマンドから差分タブ・push・ステータスバーを確かめる。esync は run.cjs の代用品。
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const vscode = require('vscode');
const { statusBarView, fileDecoration } = require('../status');

async function until(check, message) {
    for (let i = 0; i < 100; i++) {
        if (await check()) return;
        await new Promise(resolve => setTimeout(resolve, 100));
    }
    assert.fail(message);
}

function helpers() {
    const doc = state => ({ doc: { state, target: 'Lab', entity_id: 7 } });
    assert.match(statusBarView([doc('送信待ち')]).text, /cloud-upload.*送信待ち$/);
    assert.match(statusBarView([doc('最新'), doc('競合')]).text, /warning.*競合（送信先 2 件）/,
        'show the state that needs attention first');
    assert.equal(statusBarView([]), undefined);
    assert.equal(fileDecoration(['送信待ち']).badge, 'M');
    assert.equal(fileDecoration(['送信待ち', '競合']).badge, '!');
    assert.equal(fileDecoration(['最新']), undefined, 'no badge for documents in sync');
    assert.equal(fileDecoration(['最新', 'リモート削除']).badge, 'D', 'a deleted article is not hidden by another target');
    assert.match(statusBarView([doc('最新'), doc('リモート削除')]).text, /trash.*リモート削除/);
    assert.equal(fileDecoration(['最新', '新しい状態']).badge, '?', 'an unknown state comes before 最新');
    const stale = state => ({ ...doc(state), stale: true });
    const failed = statusBarView([stale('最新')], ['Lab — HTTP 401']);
    assert.match(failed.text, /error.*取得できません（前回: 最新）/, 'do not present a stale state as current');
    assert.match(failed.tooltip, /HTTP 401[\s\S]*最新（前回取得）/);
    const partial = statusBarView([doc('競合'), stale('最新')], ['Other — 設定を読み込めません']);
    assert.match(partial.text, /warning\) esync: 競合（送信先 2 件） \$\(warning\)$/,
        'a state fetched now is not shown as stale because another project failed');
    assert.match(partial.tooltip, /最新（前回取得）[\s\S]*設定を読み込めません/);
    assert.match(statusBarView([], ['Lab — HTTP 401']).text, /取得できません$/);
    assert.match(statusBarView([stale('競合')]).text, /sync~spin\) esync: 競合（更新中）$/,
        'a result being refreshed is shown as updating, not as current');
    assert.match(statusBarView([doc('送信待ち'), stale('競合')]).text, /cloud-upload\) esync: 送信待ち（送信先 2 件）$/,
        'pick the state fetched now over a result still being refreshed');
}

exports.run = async function () {
    helpers();
    const root = process.env.ESYNC_FIXTURE;
    if (!root) return console.log('PASS: status bar and badge helpers (no workspace fixture)');
    const calls = async () => (await fs.readFile(path.join(root, 'bin/calls.log'), 'utf8').catch(() => '')).trim().split('\n');
    const api = await vscode.extensions.getExtension('elab-doc-sync.esync').activate();
    const note = vscode.Uri.file(path.join(root, 'p1/docs/note.md'));
    await vscode.window.showTextDocument(note);
    await until(() => api.statusBar.text.includes('送信待ち'), 'status bar shows the state of the open document');
    // ステータスバーから、表示した送信先の差分を開く。
    const { command, arguments: args } = api.statusBar.command;
    assert.equal(command, 'esync.previewFromStatusBar');
    assert.equal(args[0].matches[0].folder.name, 'p1');
    await vscode.commands.executeCommand(command, ...args);
    const tab = vscode.window.tabGroups.activeTabGroup.activeTab;
    assert.ok(tab.input instanceof vscode.TabInputTextDiff, 'open a side-by-side diff');
    assert.equal(tab.input.original.scheme, 'esync-snapshot');
    assert.equal(tab.input.modified.scheme, 'esync-preview');
    assert.match(tab.label, /前回の同期 ↔ 送信する内容（Lab #42）/);
    assert.equal((await vscode.workspace.openTextDocument(tab.input.original)).getText(), '# old');
    const modified = await vscode.workspace.openTextDocument(tab.input.modified);
    assert.equal(modified.getText(), '# new');
    assert.equal(modified.languageId, 'markdown', 'highlight the reviewed text as Markdown');
    assert.ok((await calls()).includes('diff --json --bodies -- ' + note.fsPath));

    const preview = tab.input.modified.toString();
    await vscode.commands.executeCommand('esync.showRemoteChanges', preview);
    const remote = /** @type {vscode.TabInputTextDiff} */ (vscode.window.tabGroups.activeTabGroup.activeTab.input);
    assert.equal((await vscode.workspace.openTextDocument(remote.modified)).getText(), '# remote');

    await vscode.commands.executeCommand('esync.push', tab.input.original);
    assert.ok((await calls()).includes('push --expect-preview token --target=Lab -- ' + note.fsPath),
        'push from either side of the diff to the reviewed target');

    // 2つの同期プロジェクトがあり、ワークスペース外の文書ではフォルダーを選ぶ。進捗のキャンセルで選択画面を閉じる。
    const before = (await calls()).length;
    const source = new vscode.CancellationTokenSource();
    const pending = api.preview(vscode.Uri.file(path.join(root, 'outside/out.md')), undefined, source.token);
    setTimeout(() => source.cancel(), 300);
    assert.equal(await pending, undefined);
    assert.equal((await calls()).length, before, 'do not run esync diff after cancelling the folder picker');
    console.log('PASS: side-by-side diff, remote changes, push, status bar, folder picker cancel');
    await pullAndResolve(api, root, note, calls);
};

// 取り込みと競合の解決。確認ダイアログは自動で応答し、CLI に渡した引数を確かめる。
async function pullAndResolve(api, root, note, calls) {
    const bin = name => path.join(root, 'bin', name);
    const write = (name, value) => fs.writeFile(bin(name), JSON.stringify(value));
    const asked = [];
    api.dialogs.confirm = async (message, button) => { asked.push(button); return true; };
    const doc = { file: 'note.md', path: 'docs/note.md', entity: 'items', entity_id: 42, target: 'Lab', selector: 'Lab', state: '競合',
        remote_changes: ['本文'], next_actions: [], error: null };
    await write('status.json', { documents: [doc], recovery_pending: false });
    const pulled = { target: 'docs', entity: 'items', entity_id: 42, path: 'docs/note.md', result: 'pulled', conflict: true };
    await write('pull-dry.json', { dry_run: true, documents: [{ ...pulled, result: 'would_pull', conflict: false }] });
    await write('pull.json', { dry_run: false, documents: [pulled], conflict_files: [note.fsPath] });
    await vscode.window.showTextDocument(note);
    await vscode.commands.executeCommand('esync.refresh');
    await until(() => api.statusBar.text.includes('競合'), 'status bar shows the conflict');

    let before = (await calls()).length;
    await vscode.commands.executeCommand('esync.pull', note);
    let run = (await calls()).slice(before);
    assert.ok(run.includes('pull --json --dry-run --target=Lab --expect-id=42 --expect-server=https://example.test --expect-entity=items -- ' + note.fsPath), 'check what will be pulled first');
    assert.ok(run.includes('pull --json --target=Lab --expect-id=42 --expect-server=https://example.test --expect-entity=items -- ' + note.fsPath), 'pull only the selected document');
    assert.deepEqual(asked, ['取り込む']);
    assert.equal(vscode.window.activeTextEditor?.document.uri.fsPath, note.fsPath, 'open the file to resolve the markers');

    before = (await calls()).length;
    await vscode.commands.executeCommand('esync.adoptLocal', note);
    assert.ok((await calls()).slice(before).includes('push --force --target=Lab --expect-id=42 --expect-server=https://example.test --expect-entity=items -- ' + note.fsPath));
    before = (await calls()).length;
    await vscode.commands.executeCommand('esync.adoptRemote', note);
    assert.ok((await calls()).slice(before).includes('pull --json --force --target=Lab --expect-id=42 --expect-server=https://example.test --expect-entity=items -- ' + note.fsPath));
    assert.deepEqual(asked.slice(1), ['ローカルの内容で上書き', 'eLabFTW の内容で上書き'], 'confirm before overwriting');

    // 拒否したら CLI を実行しない。
    api.dialogs.confirm = async () => false;
    before = (await calls()).length;
    await vscode.commands.executeCommand('esync.adoptLocal', note);
    assert.ok(!(await calls()).slice(before).some(line => line.startsWith('push')), 'do not overwrite when the user declines');

    // 改名した文書: 旧名の紐付けを esync mv で移してから取り込む。
    const messages = [];
    api.dialogs.confirm = async (message, button) => { asked.push(button); messages.push(message); return true; };
    const moved = vscode.Uri.file(path.join(root, 'p1/docs/moved.md'));
    await fs.writeFile(moved.fsPath, '# moved\n');
    await write('status.json', { documents: [doc, { ...doc, file: 'moved.md', path: 'docs/moved.md', entity_id: null,
        state: '未追跡' }], recovery_pending: false });
    await write('pull-dry.json', { dry_run: true, documents: [{ target: 'docs', entity: 'items', path: 'docs/moved.md',
        result: 'untracked' }] });
    const diff = JSON.parse(await fs.readFile(bin('diff.json'), 'utf8'));
    diff.documents[0] = { ...diff.documents[0], path: 'docs/moved.md', renamed_from: 'note.md', state: 'リネーム予定' };
    await write('diff.json', diff);
    // 代用の esync は mv を実行したとき、この内容に差し替える（紐付けを移した後は取り込み予定になる）。
    await write('pull-dry-after-mv.json', { dry_run: true, documents: [{ ...pulled, path: 'docs/moved.md', result: 'would_pull' }] });
    await vscode.window.showTextDocument(moved);
    await vscode.commands.executeCommand('esync.refresh');
    await until(() => {
        const current = api.statusBar.command?.arguments?.[0];
        return current?.file.fsPath === moved.fsPath && current.matches.some(match => !match.stale);
    }, 'wait for the renamed document to appear in the refreshed status');
    before = (await calls()).length;
    await vscode.commands.executeCommand('esync.pull', moved);
    run = (await calls()).slice(before);
    assert.ok(run.includes('mv --target=Lab --expect-id=42 --expect-server=https://example.test --expect-entity=items -- ' + path.join(root, 'p1/docs/note.md') + ' ' + moved.fsPath),
        'move the mapping from the old name to the renamed file');
    assert.ok(asked.includes('紐付けを移して続ける'));
    assert.match(messages[0], /記事 #42（https:\/\/example\.test のリソース） との紐付けを moved\.md に移します/,
        'name the server and type before moving the link');
    assert.ok(run.some(line => line.startsWith('pull --json --dry-run --target=Lab')), 'pull after moving the mapping');

    // 引数や文書の指定の誤り（終了コード 2）は「変更なし」ではなく、CLI の理由を示す。
    await fs.writeFile(bin('pull-error'), 'エラー: 同期対象の文書が見つかりません: docs/note.md');
    diff.documents[0] = { ...diff.documents[0], path: 'docs/note.md', renamed_from: null, state: '競合' };
    await write('diff.json', diff);
    const shown = [];
    const original = vscode.window.showErrorMessage;
    vscode.window.showErrorMessage = async message => { shown.push(message); };
    try {
        await vscode.commands.executeCommand('esync.pull', note);
    } finally {
        vscode.window.showErrorMessage = original;
        await fs.rm(bin('pull-error'));
    }
    assert.deepEqual(shown, ['エラー: 同期対象の文書が見つかりません: docs/note.md']);

    // 同じ表示名のターゲットが2つあれば、selector で1つ選んでから書き換える。
    diff.documents = [{ ...diff.documents[0], selector: 'docs', entity_id: 42 },
        { ...diff.documents[0], selector: 'notes', entity_id: 77 }];
    await write('diff.json', diff);
    const picks = [];
    const quickPick = vscode.window.showQuickPick;
    vscode.window.showQuickPick = async items => { picks.push((await items).map(i => i.label)); return (await items)[1]; };
    before = (await calls()).length;
    try {
        await vscode.commands.executeCommand('esync.adoptLocal', note);
    } finally {
        vscode.window.showQuickPick = quickPick;
    }
    assert.deepEqual(picks, [['docs', 'notes']]);
    run = (await calls()).slice(before);
    assert.ok(run.includes('push --force --target=notes --expect-id=77 --expect-server=https://example.test --expect-entity=items -- ' + note.fsPath), 'overwrite only the chosen article');
    assert.ok(!run.some(line => line.startsWith('push') && line.includes('--target=Lab')), 'never write with the ambiguous display name');

    before = (await calls()).length;
    await vscode.commands.executeCommand('esync.showBackups');
    assert.ok((await calls()).slice(before).includes('backup list'));
    console.log('PASS: pull one document, adopt local or remote, rename then pull, backups');
}
